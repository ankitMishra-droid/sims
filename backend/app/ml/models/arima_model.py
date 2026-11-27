import time
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from statsmodels.tsa.arima.model import ARIMA
from ..base_model import BaseForecastingModel

class ARIMAForecaster(BaseForecastingModel):
    """
    Statistical Auto-Regressive Integrated Moving Average (ARIMA) Model.
    Models autocorrelation, trend differencing, and moving average residuals.
    """

    def __init__(self, order=(1, 1, 1)):
        super().__init__(model_name=f"ARIMA{order}")
        self.order = order
        self.fitted_model_ = None
        self.history_ = None

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df = train_df.sort_values("date").copy()
        self.last_date = df["date"].max()
        series = df[target_col].astype(float).values
        self.history_ = list(series)

        # Fit ARIMA model
        try:
            model = ARIMA(series, order=self.order)
            self.fitted_model_ = model.fit()
        except Exception:
            # Fallback to simple (1, 0, 0) if (1, 1, 1) encounters convergence issues
            model = ARIMA(series, order=(1, 0, 0))
            self.fitted_model_ = model.fit()

        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 3)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.fitted_model_ is None:
            raise RuntimeError("ARIMAForecaster must be fitted before predict.")

        forecast_res = self.fitted_model_.get_forecast(steps=horizon_days)
        preds = np.maximum(forecast_res.predicted_mean, 0.0)
        conf_int = forecast_res.conf_int(alpha=0.05)
        lower_bounds = np.maximum(conf_int[:, 0], 0.0)
        upper_bounds = np.maximum(conf_int[:, 1], preds)

        future_dates = [
            (self.last_date + pd.Timedelta(days=i + 1)).strftime("%Y-%m-%d")
            for i in range(horizon_days)
        ]

        return {
            "dates": future_dates,
            "predictions": [round(float(p), 2) for p in preds],
            "lower_bounds": [round(float(l), 2) for l in lower_bounds],
            "upper_bounds": [round(float(u), 2) for u in upper_bounds],
        }
