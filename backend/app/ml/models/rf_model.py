import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from ..base_model import BaseForecastingModel
from ..feature_service import FeatureEngineeringService


class _FastRecursiveTreeMixin:
    """Computes strictly causal lag/rolling/calendar features in-memory for recursive forecasts."""

    @staticmethod
    def _build_next_feature_vector(
        history_vals: List[float],
        next_date: pd.Timestamp,
        feature_cols: List[str],
        last_stockout_rate: float = 0.0,
    ) -> np.ndarray:
        n = len(history_vals)
        expanding_mean = float(np.mean(history_vals)) if n > 0 else 0.0
        dow = next_date.day_of_week
        month = next_date.month
        day_of_month = next_date.day
        quarter = (month - 1) // 3 + 1
        week = next_date.isocalendar().week
        is_festive = 1.0 if ((month == 10 and day_of_month >= 10) or (month == 11 and day_of_month <= 20) or (month == 12 and day_of_month >= 20)) else 0.0

        feat_map: Dict[str, float] = {
            "day_of_week": float(dow),
            "is_weekend": 1.0 if dow >= 5 else 0.0,
            "day_of_month": float(day_of_month),
            "week_of_year": float(week),
            "month": float(month),
            "quarter": float(quarter),
            "is_festive_window": is_festive,
            "dow_sin": float(np.sin(2.0 * np.pi * dow / 7.0)),
            "dow_cos": float(np.cos(2.0 * np.pi * dow / 7.0)),
            "month_sin": float(np.sin(2.0 * np.pi * month / 12.0)),
            "month_cos": float(np.cos(2.0 * np.pi * month / 12.0)),
            "prior_stockout_flag": 0.0,
            "rolling_stockout_7": float(last_stockout_rate),
            "prior_price_change_pct": 0.0,
            "prior_promo_flag": 0.0,
        }
        for lag in FeatureEngineeringService.LAG_WINDOWS:
            feat_map[f"lag_{lag}"] = float(history_vals[-lag]) if n >= lag else expanding_mean
        for win in FeatureEngineeringService.ROLLING_WINDOWS:
            window_slice = history_vals[-win:] if n > 0 else [0.0]
            feat_map[f"rolling_mean_{win}"] = float(np.mean(window_slice))
            feat_map[f"rolling_std_{win}"] = float(np.std(window_slice, ddof=1)) if len(window_slice) > 1 else 0.0

        return np.array([[feat_map.get(col, 0.0) for col in feature_cols]], dtype=float)


class RandomForestForecaster(BaseForecastingModel, _FastRecursiveTreeMixin):
    """
    Random Forest Regressor Forecaster trained chronologically on strictly causal features.
    """

    is_baseline = False
    MIN_TRAIN_DAYS = 28
    MIN_NON_ZERO_DAYS = 10

    def __init__(self, n_estimators: int = 80, max_depth: int = 8):
        super().__init__(model_name="RandomForest")
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.model_ = RandomForestRegressor(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            min_samples_leaf=2,
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
            return False, f"Requires >= {cls.MIN_TRAIN_DAYS} training days for Random Forest lag features (got {n})."
        vals = pd.to_numeric(train_df["demand"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
        non_zero = int(np.count_nonzero(vals > 0.0))
        if non_zero < cls.MIN_NON_ZERO_DAYS:
            return False, f"Requires >= {cls.MIN_NON_ZERO_DAYS} non-zero demand days (got {non_zero})."
        if float(vals.std()) < 1e-6:
            return False, "Zero variance in historical demand; constant baseline is sufficient."
        return True, "Eligible for chronological Random Forest training."

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        ordered = train_df.sort_values("date").copy()
        df_feat = FeatureEngineeringService.create_features(ordered, target_col=target_col)
        self.feature_cols_ = FeatureEngineeringService.get_feature_columns(df_feat, target_col=target_col)
        self.last_date = pd.Timestamp(ordered["date"].max())
        self.history_vals_ = [float(v) for v in ordered[target_col].astype(float).values]

        X = df_feat[self.feature_cols_].to_numpy(dtype=np.float64)
        y = df_feat[target_col].to_numpy(dtype=np.float64)

        self.model_.fit(X, y)
        preds = np.asarray(self.model_.predict(X), dtype=np.float64)
        self.residual_std_ = float((y - preds).std()) if len(y) > 0 else 1.0

        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 3)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_date is None:
            raise RuntimeError("RandomForestForecaster must be fitted before predict.")

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
