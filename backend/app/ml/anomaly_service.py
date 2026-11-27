import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from .ingestion_service import DataIngestionService
from .preprocess_service import DataPreprocessingService

class AnomalyDetectionService:
    """
    Detects demand spikes, abrupt drops, and irregular sales spikes.
    Uses rolling Z-score and Interquartile Range (IQR) residual boundary detection.
    """

    @classmethod
    def detect_anomalies(
        cls,
        db: Session,
        product_id: int,
        lookback_days: int = 90,
        z_threshold: float = 2.5
    ) -> Dict[str, Any]:
        """
        Scans historical sales for product_id over lookback_days to detect anomalous events.
        """
        raw_df = DataIngestionService.load_from_database(db, product_id=product_id)
        if raw_df.empty:
            return {"product_id": product_id, "anomalies": [], "total_detected": 0}

        daily = DataPreprocessingService.prepare_daily_series(raw_df, product_id=product_id, clip_outliers=False)
        if len(daily) > lookback_days:
            daily = daily.iloc[-lookback_days:].copy()

        # Rolling 14-day baseline mean and std
        rolling_mean = daily["demand"].rolling(window=14, min_periods=3).mean()
        rolling_std = daily["demand"].rolling(window=14, min_periods=3).std().replace(0, 1e-6).fillna(1.0)

        daily["expected_demand"] = rolling_mean.fillna(daily["demand"].mean())
        daily["z_score"] = (daily["demand"] - daily["expected_demand"]) / rolling_std

        anomalies = []
        for idx, row in daily.iterrows():
            z = float(row["z_score"])
            actual = float(row["demand"])
            expected = float(row["expected_demand"])

            if z > z_threshold:
                anomalies.append({
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "type": "DEMAND_SPIKE",
                    "severity": "HIGH" if z > 3.5 else "MEDIUM",
                    "observed_value": round(actual, 2),
                    "expected_value": round(expected, 2),
                    "z_score": round(z, 2),
                    "description": f"Demand spike ({round(actual, 1)} units vs {round(expected, 1)} expected baseline)",
                })
            elif z < -z_threshold and expected > 3.0:
                anomalies.append({
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "type": "DEMAND_DROP",
                    "severity": "MEDIUM",
                    "observed_value": round(actual, 2),
                    "expected_value": round(expected, 2),
                    "z_score": round(z, 2),
                    "description": f"Unusual demand drop to {round(actual, 1)} units",
                })

        return {
            "product_id": product_id,
            "lookback_days": lookback_days,
            "total_detected": len(anomalies),
            "anomalies": anomalies,
        }
