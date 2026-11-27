import time
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple
from .base_model import BaseForecastingModel
from .preprocess_service import DataPreprocessingService
from .models.arima_model import ARIMAForecaster
from .models.prophet_model import ProphetForecaster
from .models.rf_model import RandomForestForecaster
from .models.xgb_model import XGBoostForecaster
from .models.lstm_model import LSTMForecaster

class ModelEvaluationService:
    """
    Executes walk-forward temporal cross-validation and comparative model evaluation.
    Computes academic metrics: MAE, RMSE, MAPE, sMAPE, and WAPE.
    """

    @classmethod
    def evaluate_model(
        cls,
        model: BaseForecastingModel,
        train_df: pd.DataFrame,
        test_df: pd.DataFrame,
        target_col: str = "demand"
    ) -> Dict[str, Any]:
        """
        Fits model strictly on train_df, predicts over test horizon, and evaluates against actuals.
        """
        model.fit(train_df, target_col=target_col)
        horizon = len(test_df)
        pred_dict = model.predict(horizon_days=horizon)

        y_true = test_df[target_col].values
        y_pred = np.array(pred_dict["predictions"][:horizon])

        metrics = model.evaluate(y_true, y_pred)
        return {
            "model_name": model.model_name,
            "metrics": metrics,
            "training_time_seconds": model.training_time_seconds,
            "predictions": pred_dict["predictions"],
            "actuals": [round(float(v), 2) for v in y_true],
            "dates": pred_dict["dates"],
        }

    @classmethod
    def compare_all_models(
        cls,
        daily_df: pd.DataFrame,
        test_days: int = 30,
        target_col: str = "demand"
    ) -> Dict[str, Any]:
        """
        Benchmarking suite: Runs all 5 forecasting models on the identical walk-forward test split.
        Ranks models by lowest MAE and designates the Champion Model.
        """
        train_df, test_df = DataPreprocessingService.train_test_split(daily_df, test_days=test_days)

        models: List[BaseForecastingModel] = [
            ARIMAForecaster(order=(1, 1, 1)),
            ProphetForecaster(),
            RandomForestForecaster(n_estimators=100, max_depth=8),
            XGBoostForecaster(n_estimators=100, learning_rate=0.08, max_depth=5),
            LSTMForecaster(sequence_length=14, hidden_units=16, epochs=50),
        ]

        results = []
        for model in models:
            try:
                res = cls.evaluate_model(model, train_df, test_df, target_col=target_col)
                results.append({
                    "model_name": res["model_name"],
                    "mae": res["metrics"]["mae"],
                    "rmse": res["metrics"]["rmse"],
                    "mape": res["metrics"]["mape"],
                    "smape": res["metrics"]["smape"],
                    "wape": res["metrics"]["wape"],
                    "training_time_seconds": res["training_time_seconds"],
                    "predictions": res["predictions"],
                })
            except Exception as e:
                print(f"Evaluation error on {model.model_name}: {e}")

        # Rank models by MAE ascending
        results.sort(key=lambda x: x["mae"])
        for rank, item in enumerate(results, start=1):
            item["rank"] = rank

        champion = results[0]["model_name"] if results else "None"

        return {
            "test_window_days": len(test_df),
            "champion_model": champion,
            "test_dates": [d.strftime("%Y-%m-%d") for d in test_df["date"]],
            "test_actuals": [round(float(v), 2) for v in test_df[target_col]],
            "models": results,
        }
