from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
from sqlalchemy.orm import Session

from ..models.products import Product
from .ingestion_service import DataIngestionService
from .preprocess_service import DataPreprocessingService


class AnomalyDetectionService:
    """
    Detects statistically anomalous demand spikes and drops while distinguishing
    stockout-constrained zero-demand days from true demand drops.
    """

    @classmethod
    def detect_anomalies(
        cls,
        db: Session,
        product_id: int,
        lookback_days: int = 90,
        z_threshold: float = 2.5,
        *,
        business_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        query = db.query(Product).filter(Product.id == product_id)
        if business_id is not None:
            query = query.filter(Product.business_id == business_id)
        product = query.first()
        if not product:
            return {"product_id": product_id, "lookback_days": lookback_days, "anomalies": [], "total_detected": 0}

        cutoff_dt = datetime.now(timezone.utc).replace(tzinfo=None)
        raw_df = DataIngestionService.load_from_database(
            db,
            business_id=product.business_id,
            product_id=product.id,
            as_of_date=cutoff_dt,
        )
        if raw_df.empty:
            return {"product_id": product_id, "lookback_days": lookback_days, "anomalies": [], "total_detected": 0}

        stock_logs_df = DataIngestionService.load_stock_ledger_for_product(
            db,
            business_id=product.business_id,
            product_id=product.id,
            as_of_date=cutoff_dt,
        )
        daily = DataPreprocessingService.prepare_daily_series(
            raw_df,
            product_id=product.id,
            as_of_date=cutoff_dt,
            product_created_at=product.created_at,
            stock_logs_df=stock_logs_df,
            current_stock=product.current_stock,
            clip_outliers=False,
        )
        if len(daily) > lookback_days:
            daily = daily.iloc[-lookback_days:].copy()

        shifted = daily["raw_demand"].astype(float).shift(1)
        rolling_mean = shifted.rolling(window=14, min_periods=3).mean().bfill().fillna(float(daily["raw_demand"].mean()))
        rolling_std = shifted.rolling(window=14, min_periods=3).std().replace(0, 1e-6).fillna(1.0).clip(lower=0.5)

        daily["expected_demand"] = rolling_mean
        daily["z_score"] = (daily["raw_demand"] - daily["expected_demand"]) / rolling_std

        anomalies = []
        for _, row in daily.iterrows():
            z = float(row["z_score"])
            actual = float(row["raw_demand"])
            expected = float(row["expected_demand"])
            is_stockout = bool(row.get("is_stockout_day", False))

            if z > z_threshold:
                anomalies.append(
                    {
                        "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                        "type": "DEMAND_SPIKE",
                        "severity": "HIGH" if z > 3.5 else "MEDIUM",
                        "observed_value": round(actual, 2),
                        "expected_value": round(expected, 2),
                        "z_score": round(z, 2),
                        "is_stockout_day": False,
                        "description": f"Demand spike ({round(actual, 1)} units vs {round(expected, 1)} expected baseline)",
                    }
                )
            elif z < -z_threshold and expected > 2.5 and not is_stockout:
                anomalies.append(
                    {
                        "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                        "type": "DEMAND_DROP",
                        "severity": "MEDIUM",
                        "observed_value": round(actual, 2),
                        "expected_value": round(expected, 2),
                        "z_score": round(z, 2),
                        "is_stockout_day": False,
                        "description": f"Unusual demand drop to {round(actual, 1)} units (stock available; not stockout-driven)",
                    }
                )

        return {
            "product_id": product.id,
            "business_id": product.business_id,
            "lookback_days": lookback_days,
            "total_detected": len(anomalies),
            "anomalies": anomalies,
        }
