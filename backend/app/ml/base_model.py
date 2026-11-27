from abc import ABC, abstractmethod
import os
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple

class BaseForecastingModel(ABC):
    """
    Abstract Base Strategy Interface for all demand forecasting models.
    Every model conforms to this contract, enabling uniform training,
    evaluation, walk-forward cross validation, and champion selection.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.is_fitted = False
        self.last_date: Optional[pd.Timestamp] = None
        self.training_time_seconds: float = 0.0

    @abstractmethod
    def fit(self, train_df: pd.DataFrame, target_col: str = "demand") -> None:
        """
        Fit model on historical training data.
        """
        pass

    @abstractmethod
    def predict(self, horizon_days: int = 30) -> Dict[str, Any]:
        """
        Generate out-of-sample forecast for the next horizon_days.
        Returns dictionary containing:
        - dates: List[str]
        - predictions: List[float]
        - lower_bounds: List[float]
        - upper_bounds: List[float]
        """
        pass

    def evaluate(self, y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
        """
        Compute standard academic time-series accuracy metrics:
        MAE, RMSE, MAPE, sMAPE, and WAPE.
        """
        y_true = np.asarray(y_true, dtype=float)
        y_pred = np.asarray(y_pred, dtype=float)
        y_pred = np.maximum(y_pred, 0.0)  # Non-negative demand constraint

        n = len(y_true)
        if n == 0:
            return {"mae": 0.0, "rmse": 0.0, "mape": 0.0, "smape": 0.0, "wape": 0.0}

        # 1. Mean Absolute Error
        abs_err = np.abs(y_true - y_pred)
        mae = float(np.mean(abs_err))

        # 2. Root Mean Squared Error
        sq_err = np.square(y_true - y_pred)
        rmse = float(np.sqrt(np.mean(sq_err)))

        # 3. Mean Absolute Percentage Error (handling 0 division)
        non_zero_mask = y_true > 0
        if np.any(non_zero_mask):
            mape = float(np.mean(abs_err[non_zero_mask] / y_true[non_zero_mask])) * 100.0
        else:
            mape = 0.0

        # 4. Symmetric Mean Absolute Percentage Error (sMAPE)
        denominator = (np.abs(y_true) + np.abs(y_pred)) / 2.0
        denom_mask = denominator > 0
        if np.any(denom_mask):
            smape = float(np.mean(abs_err[denom_mask] / denominator[denom_mask])) * 100.0
        else:
            smape = 0.0

        # 5. Weighted Absolute Percentage Error (WAPE)
        sum_actual = float(np.sum(y_true))
        wape = (float(np.sum(abs_err)) / sum_actual * 100.0) if sum_actual > 0 else 0.0

        return {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "mape": round(mape, 2),
            "smape": round(smape, 2),
            "wape": round(wape, 2),
        }

    def save_model(self, filepath: str) -> None:
        """Serialize model artifact to disk."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        joblib.dump(self, filepath)

    @classmethod
    def load_model(cls, filepath: str) -> "BaseForecastingModel":
        """Deserialize model artifact from disk."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Model file not found: {filepath}")
        return joblib.load(filepath)
