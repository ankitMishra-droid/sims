from abc import ABC, abstractmethod
import os
from typing import Any, Dict, Optional

import joblib
import numpy as np
import pandas as pd


class BaseForecastingModel(ABC):
    """
    Abstract Base Strategy Interface for all demand forecasting models.
    Supports baselines and statistical/ML models with honest zero-safe evaluation metrics:
    MAE, MSE, RMSE, nullable MAPE, WAPE, signed Forecast Bias (Predicted - Actual),
    sMAPE, and MASE.
    """

    is_baseline: bool = False
    BIAS_CONVENTION = "Mean(Predicted - Actual): positive values indicate over-forecasting; negative values indicate under-forecasting."

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.is_fitted = False
        self.last_date: Optional[pd.Timestamp] = None
        self.training_time_seconds: float = 0.0

    @abstractmethod
    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        """Fit model on chronological historical training data."""
        pass

    @abstractmethod
    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        """Generate non-negative out-of-sample daily point and interval forecasts."""
        pass

    @classmethod
    def check_eligibility(
        cls,
        train_df: pd.DataFrame,
        profile: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """Default eligibility check for simple baseline models."""
        n = len(train_df) if train_df is not None else 0
        if n < 1:
            return False, "No training observations available."
        return True, "Eligible."

    def evaluate(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_train: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Compute standard zero-safe out-of-sample time-series accuracy metrics:
        MAE, MSE, RMSE, nullable MAPE, WAPE, signed Forecast Bias, sMAPE, and MASE.
        When y_true contains only zeros, MAPE/WAPE return None instead of fabricating 0.0.
        """
        y_true = np.asarray(y_true, dtype=float)
        y_pred = np.maximum(np.asarray(y_pred, dtype=float), 0.0)

        n = len(y_true)
        if n == 0:
            return {
                "mae": None,
                "mse": None,
                "rmse": None,
                "mape": None,
                "smape": None,
                "wape": None,
                "mase": None,
                "bias": None,
                "bias_pct": None,
                "bias_direction": None,
                "zero_actuals_ratio": None,
                "mape_limitation_note": "No held-out observations.",
            }

        signed_err = y_pred - y_true  # Convention: Predicted - Actual (+ over-forecast, - under-forecast)
        abs_err = np.abs(y_true - y_pred)
        sq_err = np.square(y_true - y_pred)

        mae = float(np.mean(abs_err))
        mse = float(np.mean(sq_err))
        rmse = float(np.sqrt(mse))
        bias = float(np.mean(signed_err))

        non_zero_mask = y_true > 0
        zero_ratio = round(float(np.sum(~non_zero_mask)) / n, 4)

        if np.any(non_zero_mask):
            mape: Optional[float] = round(
                float(np.mean(abs_err[non_zero_mask] / y_true[non_zero_mask])) * 100.0,
                2,
            )
            mape_note = (
                f"Calculated over {int(np.sum(non_zero_mask))}/{n} non-zero demand days; {int(np.sum(~non_zero_mask))} zero-demand day(s) excluded to prevent division by zero."
                if zero_ratio > 0
                else "Calculated across all held-out days (no zero-demand days in test fold)."
            )
        else:
            mape = None
            mape_note = "Undefined: all held-out actual observations are zero (zero-demand denominator)."

        denominator = (np.abs(y_true) + np.abs(y_pred)) / 2.0
        denom_mask = denominator > 0
        if np.any(denom_mask):
            smape = round(float(np.mean(abs_err[denom_mask] / denominator[denom_mask])) * 100.0, 2)
        else:
            smape = 0.0

        sum_abs_actual = float(np.sum(np.abs(y_true)))
        wape: Optional[float] = round(float(np.sum(abs_err)) / sum_abs_actual * 100.0, 2) if sum_abs_actual > 0 else None
        bias_pct: Optional[float] = round(float(np.sum(signed_err)) / sum_abs_actual * 100.0, 2) if sum_abs_actual > 0 else None

        if abs(bias) <= 0.05:
            bias_direction = "BALANCED"
        elif bias > 0:
            bias_direction = "OVER_FORECASTING"
        else:
            bias_direction = "UNDER_FORECASTING"

        mase: Optional[float] = None
        if y_train is not None:
            y_tr = np.asarray(y_train, dtype=float)
            if len(y_tr) >= 2:
                naive_scale = float(np.mean(np.abs(np.diff(y_tr))))
                if naive_scale > 1e-8:
                    mase = round(mae / naive_scale, 4)

        return {
            "mae": round(mae, 4),
            "mse": round(mse, 4),
            "rmse": round(rmse, 4),
            "mape": mape,
            "smape": smape,
            "wape": wape,
            "mase": mase,
            "bias": round(bias, 4),
            "bias_pct": bias_pct,
            "bias_direction": bias_direction,
            "zero_actuals_ratio": zero_ratio,
            "mape_limitation_note": mape_note,
        }

    def save_model(self, filepath: str) -> None:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        joblib.dump(self, filepath)

    @classmethod
    def load_model(cls, filepath: str) -> "BaseForecastingModel":
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Model file not found: {filepath}")
        return joblib.load(filepath)
