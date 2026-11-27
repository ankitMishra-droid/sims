import os
import time
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from pathlib import Path

from ..models.products import Product
from .ingestion_service import DataIngestionService
from .preprocess_service import DataPreprocessingService
from .evaluation_service import ModelEvaluationService
from .models.arima_model import ARIMAForecaster
from .models.prophet_model import ProphetForecaster
from .models.rf_model import RandomForestForecaster
from .models.xgb_model import XGBoostForecaster
from .models.lstm_model import LSTMForecaster
from .base_model import BaseForecastingModel

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts" / "models"

class ForecastingService:
    """
    Forecasting Engine: Orchestrates data ingestion, multi-model training,
    walk-forward benchmarking, champion selection, and future demand projections.
    """

    _model_cache: Dict[str, BaseForecastingModel] = {}
    _champion_cache: Dict[int, Dict[str, Any]] = {}

    @classmethod
    def get_model_instance(cls, model_name: str) -> BaseForecastingModel:
        name = model_name.lower()
        if "arima" in name:
            return ARIMAForecaster(order=(1, 1, 1))
        elif "prophet" in name:
            return ProphetForecaster()
        elif "random_forest" in name or "rf" in name:
            return RandomForestForecaster()
        elif "xgb" in name:
            return XGBoostForecaster()
        elif "lstm" in name or "neural" in name:
            return LSTMForecaster()
        else:
            return XGBoostForecaster()  # High-accuracy default

    @classmethod
    def generate_product_forecast(
        cls,
        db: Session,
        product_id: int,
        horizon_days: int = 30,
        model_choice: str = "auto"
    ) -> Dict[str, Any]:
        """
        Generates multi-day demand forecast for product_id.
        If model_choice == 'auto', uses champion model from comparative evaluation.
        """
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise ValueError(f"Product with ID {product_id} not found.")

        # Ingest and preprocess sales
        raw_sales = DataIngestionService.load_from_database(db, product_id=product_id)
        if raw_sales.empty:
            raise ValueError(f"No historical sales found for product '{product.name}' (SKU: {product.sku}).")

        daily_df = DataPreprocessingService.prepare_daily_series(raw_sales, product_id=product_id)

        # Determine champion model or use requested model
        if model_choice == "auto":
            if product_id in cls._champion_cache:
                best_model_name = cls._champion_cache[product_id]["champion_model"]
                best_metrics = cls._champion_cache[product_id]["metrics"]
            else:
                comparison = ModelEvaluationService.compare_all_models(daily_df, test_days=min(30, int(len(daily_df) * 0.15)))
                best_model_name = comparison["champion_model"]
                best_metrics = next((m for m in comparison["models"] if m["model_name"] == best_model_name), {})
                cls._champion_cache[product_id] = {
                    "champion_model": best_model_name,
                    "metrics": best_metrics
                }
            model = cls.get_model_instance(best_model_name)
            is_champion = True
        else:
            model = cls.get_model_instance(model_choice)
            best_model_name = model.model_name
            train_df, test_df = DataPreprocessingService.train_test_split(daily_df, test_days=min(30, int(len(daily_df) * 0.15)))
            eval_res = ModelEvaluationService.evaluate_model(model, train_df, test_df)
            best_metrics = eval_res["metrics"]
            is_champion = False

        # Fit model on entire available historical series for future forecasting
        model.fit(daily_df, target_col="demand")
        forecast = model.predict(horizon_days=horizon_days)

        predictions = forecast["predictions"]
        total_demand = round(float(np.sum(predictions)), 2)
        daily_avg = round(float(np.mean(predictions)), 2)
        peak_idx = int(np.argmax(predictions)) if predictions else 0
        peak_day = forecast["dates"][peak_idx] if forecast["dates"] else ""

        # Determine trend direction
        half = len(predictions) // 2
        first_half = np.mean(predictions[:half]) if half > 0 else daily_avg
        second_half = np.mean(predictions[half:]) if half > 0 else daily_avg
        if second_half > first_half * 1.05:
            trend = "upward"
        elif second_half < first_half * 0.95:
            trend = "downward"
        else:
            trend = "stable"

        return {
            "product_id": product.id,
            "product_name": product.name,
            "sku": product.sku,
            "category": product.category,
            "current_stock": product.current_stock,
            "model_used": best_model_name,
            "is_champion_model": is_champion,
            "forecast_horizon_days": horizon_days,
            "generated_at": pd.Timestamp.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary": {
                "total_predicted_demand": total_demand,
                "daily_average_demand": daily_avg,
                "peak_demand_day": peak_day,
                "peak_demand_value": predictions[peak_idx] if predictions else 0.0,
                "forecast_trend": trend,
            },
            "metrics": {
                "mae": best_metrics.get("mae", 0.0),
                "rmse": best_metrics.get("rmse", 0.0),
                "mape": best_metrics.get("mape", 0.0),
                "smape": best_metrics.get("smape", 0.0),
                "wape": best_metrics.get("wape", 0.0),
            },
            "forecast_series": [
                {
                    "date": forecast["dates"][i],
                    "predicted_demand": predictions[i],
                    "lower_confidence_bound": forecast["lower_bounds"][i],
                    "upper_confidence_bound": forecast["upper_bounds"][i],
                }
                for i in range(len(predictions))
            ],
        }

    @classmethod
    def compare_models_for_product(
        cls,
        db: Session,
        product_id: int,
        test_days: int = 30
    ) -> Dict[str, Any]:
        """
        Runs the 5-model benchmark on a product and returns comparison table.
        """
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise ValueError(f"Product with ID {product_id} not found.")

        raw_sales = DataIngestionService.load_from_database(db, product_id=product_id)
        if raw_sales.empty:
            raise ValueError(f"No historical sales for product ID {product_id}.")

        daily_df = DataPreprocessingService.prepare_daily_series(raw_sales, product_id=product_id)
        comparison = ModelEvaluationService.compare_all_models(daily_df, test_days=test_days)

        return {
            "product_id": product.id,
            "product_name": product.name,
            "sku": product.sku,
            **comparison
        }
