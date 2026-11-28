import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from ..base_model import BaseForecastingModel
from ..feature_service import FeatureEngineeringService
from .rf_model import _FastRecursiveTreeMixin


class XGBoostForecaster(BaseForecastingModel, _FastRecursiveTreeMixin):
    """
    XGBoost Gradient Boosted Trees Forecaster trained on strictly causal features
    with optional chronological internal validation early stopping.
    """

    is_baseline = False
    MIN_TRAIN_DAYS = 28
    MIN_NON_ZERO_DAYS = 10

    def __init__(self, n_estimators: int = 80, learning_rate: float = 0.08, max_depth: int = 4):
        super().__init__(model_name="XGBoost")
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.model_ = XGBRegressor(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=1.5,
            random_state=42,
            n_jobs=1,
        )
        self.feature_cols_: List[str] = []
        self.history_vals_: List[float] = []
        self.residual_std_: float = 1.0

    @classmethod
    def check_eligibility(
        cls,
        train_df: pd.DataFrame,
        profile: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        n = len(train_df) if train_df is not None else 0
        if n < cls.MIN_TRAIN_DAYS:
            return False, f"Requires >= {cls.MIN_TRAIN_DAYS} training days for XGBoost supervised lag features (got {n})."
        vals = pd.to_numeric(train_df["demand"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
        non_zero = int(np.count_nonzero(vals > 0.0))
        if non_zero < cls.MIN_NON_ZERO_DAYS:
            return False, f"Requires >= {cls.MIN_NON_ZERO_DAYS} non-zero demand days (got {non_zero})."
        if float(vals.std()) < 1e-6:
            return False, "Zero variance in historical demand; constant baseline is sufficient."
        return True, "Eligible for chronological XGBoost training."

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        ordered = train_df.sort_values("date").copy()
        df_feat = FeatureEngineeringService.create_features(ordered, target_col=target_col)
        self.feature_cols_ = FeatureEngineeringService.get_feature_columns(df_feat, target_col=target_col)
        self.last_date = pd.Timestamp(ordered["date"].max())
        self.history_vals_ = [float(v) for v in ordered[target_col].astype(float).values]

        X = df_feat[self.feature_cols_].values
        y = df_feat[target_col].astype(float).values

        # Chronological internal validation split (never random!) when series has >= 56 observations
        if len(X) >= 56:
            val_len = max(7, int(len(X) * 0.15))
            X_tr, y_tr = X[:-val_len], y[:-val_len]
            X_val, y_val = X[-val_len:], y[-val_len:]
            self.model_ = XGBRegressor(
                n_estimators=max(self.n_estimators, 120),
                learning_rate=self.learning_rate,
                max_depth=self.max_depth,
                subsample=0.9,
                colsample_bytree=0.9,
                reg_lambda=1.5,
                early_stopping_rounds=12,
                eval_metric="rmse",
                random_state=42,
                n_jobs=1,
            )
            self.model_.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
            val_preds = self.model_.predict(X_val)
            self.residual_std_ = float(np.std(y_val - val_preds)) if len(y_val) > 1 else 1.0
        else:
            self.model_.fit(X, y)
            preds = self.model_.predict(X)
            self.residual_std_ = float(np.std(y - preds)) if len(y) > 0 else 1.0

        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 3)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_date is None:
            raise RuntimeError("XGBoostForecaster must be fitted before predict.")

        history = list(self.history_vals_)
        predictions: List[float] = []
        future_dates: List[str] = []

        for step in range(horizon_days):
            next_date = self.last_date + pd.Timedelta(days=step + 1)
            future_dates.append(next_date.strftime("%Y-%m-%d"))
            X_next = self._build_next_feature_vector(history, next_date, self.feature_cols_)
            next_pred = float(np.maximum(self.model_.predict(X_next)[0], 0.0))
            predictions.append(round(next_pred, 2))
            history.append(next_pred)

        lower_bounds = [max(0.0, round(p - 1.96 * self.residual_std_, 2)) for p in predictions]
        upper_bounds = [round(p + 1.96 * self.residual_std_, 2) for p in predictions]

        return {
            "dates": future_dates,
            "predictions": predictions,
            "lower_bounds": lower_bounds,
            "upper_bounds": upper_bounds,
        }
