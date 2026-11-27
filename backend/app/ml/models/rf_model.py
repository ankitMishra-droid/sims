import time
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from sklearn.ensemble import RandomForestRegressor
from ..base_model import BaseForecastingModel
from ..feature_service import FeatureEngineeringService

class RandomForestForecaster(BaseForecastingModel):
    """
    Random Forest Regressor Forecaster.
    Ensemble of decision trees trained on engineered lag features and rolling window statistics.
    Uses multi-step recursive forecasting for future horizons.
    """

    def __init__(self, n_estimators: int = 100, max_depth: int = 10):
        super().__init__(model_name="RandomForest")
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.model_ = RandomForestRegressor(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            random_state=42,
            n_jobs=-1
        )
        self.feature_cols_: List[str] = []
        self.last_known_data_: Optional[pd.DataFrame] = None
        self.residual_std_: float = 1.0

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df_feat = FeatureEngineeringService.create_features(train_df, target_col=target_col)
        self.feature_cols_ = FeatureEngineeringService.get_feature_columns(df_feat, target_col=target_col)
        self.last_date = train_df["date"].max()
        self.last_known_data_ = train_df.sort_values("date").copy()

        X = df_feat[self.feature_cols_].values
        y = df_feat[target_col].values

        self.model_.fit(X, y)
        preds = self.model_.predict(X)
        self.residual_std_ = float(np.std(y - preds)) if len(y) > 0 else 1.0

        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 3)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_known_data_ is None:
            raise RuntimeError("RandomForestForecaster must be fitted before predict.")

        # Multi-step autoregressive simulation
        current_data = self.last_known_data_.copy()
        predictions = []
        future_dates = []

        for step in range(horizon_days):
            next_date = self.last_date + pd.Timedelta(days=step + 1)
            future_dates.append(next_date.strftime("%Y-%m-%d"))

            # Append placeholder for next day to compute features
            temp_row = pd.DataFrame([{"date": next_date, "demand": 0.0}])
            sim_df = pd.concat([current_data, temp_row], ignore_index=True)

            sim_feat = FeatureEngineeringService.create_features(sim_df, target_col="demand")
            X_next = sim_feat.iloc[[-1]][self.feature_cols_].values

            next_pred = float(np.maximum(self.model_.predict(X_next)[0], 0.0))
            predictions.append(round(next_pred, 2))

            # Update simulated history with predicted value
            current_data = pd.concat([current_data, pd.DataFrame([{"date": next_date, "demand": next_pred}])], ignore_index=True)

        lower_bounds = [max(0.0, round(p - 1.96 * self.residual_std_, 2)) for p in predictions]
        upper_bounds = [round(p + 1.96 * self.residual_std_, 2) for p in predictions]

        return {
            "dates": future_dates,
            "predictions": predictions,
            "lower_bounds": lower_bounds,
            "upper_bounds": upper_bounds,
        }
