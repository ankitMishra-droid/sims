import time
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from sklearn.linear_model import Ridge
from ..base_model import BaseForecastingModel

class ProphetForecaster(BaseForecastingModel):
    """
    Additive Seasonal Trend Forecaster (Prophet-style formulation).
    Decomposes demand into:
    y(t) = Trend(t) + WeeklySeasonality(t) + MonthlySeasonality(t) + Residuals
    Uses Fourier harmonics for smooth weekly and annual cyclical dynamics.
    """

    def __init__(self):
        super().__init__(model_name="AdditiveProphet")
        self.regressor_ = Ridge(alpha=1.0)
        self.start_date_: Optional[pd.Timestamp] = None
        self.residual_std_: float = 1.0

    def _extract_fourier_features(self, dates: pd.Series) -> pd.DataFrame:
        if self.start_date_ is None:
            raise RuntimeError("ProphetForecaster start_date_ must be initialized before feature extraction.")
        t = np.asarray((dates - self.start_date_).dt.days.to_numpy(dtype=np.float64), dtype=np.float64)
        dow = np.asarray(dates.dt.day_of_week.to_numpy(dtype=np.float64), dtype=np.float64)
        month = np.asarray(dates.dt.month.to_numpy(dtype=np.float64), dtype=np.float64)

        features = pd.DataFrame({
            "trend": t,
            "trend_sq": (t / 100.0) ** 2,
            "sin_weekly_1": np.sin(2 * np.pi * 1 * dow / 7.0),
            "cos_weekly_1": np.cos(2 * np.pi * 1 * dow / 7.0),
            "sin_weekly_2": np.sin(2 * np.pi * 2 * dow / 7.0),
            "cos_weekly_2": np.cos(2 * np.pi * 2 * dow / 7.0),
            "sin_yearly_1": np.sin(2 * np.pi * 1 * month / 12.0),
            "cos_yearly_1": np.cos(2 * np.pi * 1 * month / 12.0),
            "sin_yearly_2": np.sin(2 * np.pi * 2 * month / 12.0),
            "cos_yearly_2": np.cos(2 * np.pi * 2 * month / 12.0),
            "is_weekend": np.isin(dow, [5, 6]).astype(float),
        })
        return features

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df = train_df.sort_values("date").copy()
        self.start_date_ = pd.Timestamp(df["date"].min())
        self.last_date = pd.Timestamp(df["date"].max())

        X = self._extract_fourier_features(df["date"])
        y = np.asarray(pd.to_numeric(df[target_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64), dtype=np.float64)

        self.regressor_.fit(X, y)
        preds = self.regressor_.predict(X)
        residuals = y - preds
        self.residual_std_ = float(np.std(residuals)) if len(residuals) > 0 else 1.0

        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 3)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_date is None:
            raise RuntimeError("ProphetForecaster must be fitted before predict.")

        last_dt = self.last_date
        future_dates = [
            last_dt + pd.Timedelta(days=i + 1)
            for i in range(horizon_days)
        ]
        future_series = pd.Series(future_dates)
        X_future = self._extract_fourier_features(future_series)

        preds = np.maximum(self.regressor_.predict(X_future), 0.0)
        # 95% confidence bound (+/- 1.96 * residual_std)
        lower_bounds = np.maximum(preds - 1.96 * self.residual_std_, 0.0)
        upper_bounds = preds + 1.96 * self.residual_std_

        return {
            "dates": [d.strftime("%Y-%m-%d") for d in future_dates],
            "predictions": [round(float(p), 2) for p in preds],
            "lower_bounds": [round(float(l), 2) for l in lower_bounds],
            "upper_bounds": [round(float(u), 2) for u in upper_bounds],
        }
