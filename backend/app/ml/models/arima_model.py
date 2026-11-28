import time
import warnings
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.stattools import adfuller

from ..base_model import BaseForecastingModel


class ARIMAForecaster(BaseForecastingModel):
    """
    Statistical Auto-Regressive Integrated Moving Average (ARIMA) Model
    with chronological stationarity/differencing selection and safe convergence handling.
    """

    is_baseline = False
    MIN_TRAIN_DAYS = 24
    MIN_NON_ZERO_DAYS = 8

    def __init__(self, order=(1, 1, 1)):
        super().__init__(model_name=f"ARIMA{order}")
        self.order = order
        self.selected_order_ = order
        self.fitted_model_ = None
        self.constant_level_: Optional[float] = None
        self.is_stationary_: Optional[bool] = None

    @classmethod
    def check_eligibility(
        cls,
        train_df: pd.DataFrame,
        profile: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        n = len(train_df) if train_df is not None else 0
        if n < cls.MIN_TRAIN_DAYS:
            return False, f"Requires >= {cls.MIN_TRAIN_DAYS} historical observations for ARIMA differencing (got {n})."
        vals = pd.to_numeric(train_df["demand"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
        non_zero = int(np.count_nonzero(vals > 0.0))
        if non_zero < cls.MIN_NON_ZERO_DAYS:
            return False, f"Requires >= {cls.MIN_NON_ZERO_DAYS} non-zero demand days for ARIMA parameter fit (got {non_zero})."
        if float(vals.std()) < 1e-4:
            return False, "Near-zero series variance; ARIMA differencing would collapse to a constant."
        return True, "Eligible for chronological ARIMA time-series fitting."

    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        t0 = time.time()
        df = train_df.sort_values("date").copy()
        self.last_date = pd.Timestamp(df["date"].max())
        series = np.asarray(
            pd.to_numeric(df[target_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64),
            dtype=np.float64,
        )

        if len(series) < 8 or float(np.std(series)) < 1e-6:
            self.constant_level_ = float(np.mean(series)) if len(series) > 0 else 0.0
            self.fitted_model_ = None
            self.is_fitted = True
            self.training_time_seconds = round(time.time() - t0, 4)
            return

        # Stationarity hint for order adaptation (stationary -> prefer d=0 when non-stationary check passes)
        candidate_orders = [self.order, (1, 0, 1), (1, 0, 0)]
        try:
            if len(series) >= 20:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    adf_stat = adfuller(series, autolag="AIC")
                self.is_stationary_ = bool(adf_stat[1] < 0.05)
                if self.is_stationary_ and self.order == (1, 1, 1):
                    candidate_orders = [(1, 0, 1), (1, 1, 1), (1, 0, 0)]
        except Exception:
            self.is_stationary_ = None

        self.constant_level_ = None
        self.fitted_model_ = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for cand_order in candidate_orders:
                try:
                    model = ARIMA(series, order=cand_order)
                    res = model.fit()
                    preds_check = res.get_forecast(steps=1).predicted_mean
                    if np.all(np.isfinite(preds_check)):
                        self.fitted_model_ = res
                        self.selected_order_ = cand_order
                        break
                except Exception:
                    continue

        if self.fitted_model_ is None:
            self.constant_level_ = float(np.mean(series))

        self.is_fitted = True
        self.training_time_seconds = round(time.time() - t0, 3)

    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        if not self.is_fitted or self.last_date is None:
            raise RuntimeError("ARIMAForecaster must be fitted before predict.")

        future_dates = [
            (self.last_date + pd.Timedelta(days=i + 1)).strftime("%Y-%m-%d")
            for i in range(horizon_days)
        ]

        if self.fitted_model_ is None:
            val = round(max(self.constant_level_ or 0.0, 0.0), 2)
            return {
                "dates": future_dates,
                "predictions": [val] * horizon_days,
                "lower_bounds": [val] * horizon_days,
                "upper_bounds": [val] * horizon_days,
            }

        forecast_res = self.fitted_model_.get_forecast(steps=horizon_days)
        preds = np.maximum(forecast_res.predicted_mean, 0.0)
        conf_int = forecast_res.conf_int(alpha=0.05)
        lower_bounds = np.maximum(conf_int[:, 0], 0.0)
        upper_bounds = np.maximum(conf_int[:, 1], preds)

        return {
            "dates": future_dates,
            "predictions": [round(float(p), 2) for p in preds],
            "lower_bounds": [round(float(l), 2) for l in lower_bounds],
            "upper_bounds": [round(float(u), 2) for u in upper_bounds],
        }
