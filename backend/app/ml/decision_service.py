import math
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from ..models.products import Product
from ..models.supplier import Supplier
from ..services.inventory_service import InventoryService
from .ingestion_service import DataIngestionService
from .preprocess_service import DataPreprocessingService
from .forecasting_service import ForecastingService

# Normal critical values for service levels
SERVICE_LEVEL_Z_TABLE = {
    0.90: 1.282,
    0.95: 1.645,
    0.98: 2.054,
    0.99: 2.326,
    0.999: 3.090,
}

class InventoryDecisionService:
    """
    Inventory Intelligence & Decision Engine.
    Implements formal Operations Research & Supply Chain formulations:
    - Safety Stock (SS) with stochastic demand and lead time
    - Reorder Point (ROP)
    - Economic Order Quantity (EOQ)
    - Days of Inventory Remaining (DIR)
    - Stockout & Overstock Risk Classification
    """

    @classmethod
    def get_z_score(cls, service_level: float = 0.95) -> float:
        """Finds closest Z-score for requested service level."""
        closest_sl = min(SERVICE_LEVEL_Z_TABLE.keys(), key=lambda sl: abs(sl - service_level))
        return SERVICE_LEVEL_Z_TABLE[closest_sl]

    @classmethod
    def calculate_product_decision_metrics(
        cls,
        db: Session,
        product_id: int,
        service_level: float = 0.95,
        ordering_cost: float = 50.0,
        holding_cost_rate: float = 0.20
    ) -> Dict[str, Any]:
        """
        Calculates complete ROP, Safety Stock, EOQ, and Risk metrics for a single product.
        """
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise ValueError(f"Product ID {product_id} not found.")

        supplier = db.query(Supplier).filter(Supplier.id == product.supplier_id).first() if product.supplier_id else None
        lead_time_days = supplier.lead_time_days if supplier and supplier.lead_time_days else 7
        supplier_lead_time_std = 1.0  # Lead time variance

        # Fetch demand forecast
        forecast_res = ForecastingService.generate_product_forecast(db, product_id=product_id, horizon_days=30, model_choice="auto")
        d = forecast_res["summary"]["daily_average_demand"]  # Average daily demand
        if d <= 0:
            d = 0.5  # Minimum positive demand baseline

        # Residual std dev from forecast model
        sigma_d = forecast_res["metrics"].get("rmse") or (d * 0.4)
        if sigma_d <= 0:
            sigma_d = d * 0.35

        Z = cls.get_z_score(service_level)

        # 1. Safety Stock Formula: SS = Z * sqrt(L * sigma_d^2 + d^2 * sigma_L^2)
        variance_term = (lead_time_days * (sigma_d ** 2)) + ((d ** 2) * (supplier_lead_time_std ** 2))
        safety_stock = int(math.ceil(Z * math.sqrt(max(0.01, variance_term))))

        # 2. Reorder Point Formula: ROP = (d * L) + SS
        lead_time_demand = d * lead_time_days
        reorder_point = int(math.ceil(lead_time_demand + safety_stock))

        # 3. Economic Order Quantity: EOQ = sqrt(2 * D * S / H)
        annual_demand = d * 365.0
        unit_cost = float(product.cost_price or (product.selling_price * 0.7) or 100.0)
        annual_holding_cost = max(1.0, unit_cost * holding_cost_rate)
        eoq = int(math.ceil(math.sqrt((2.0 * annual_demand * ordering_cost) / annual_holding_cost)))

        # 4. Inventory Position & Days Remaining
        current_stock = int(product.current_stock or 0)
        incoming_map = InventoryService.get_incoming_stock_map(
            db, product.business_id, [product.id]
        )
        incoming_stock = incoming_map.get(product.id, 0)
        reserved_stock = 0
        inventory_position = current_stock + incoming_stock - reserved_stock
        days_remaining = round(current_stock / max(d, 0.01), 1)

        # 5. Risk Classification
        if days_remaining < lead_time_days:
            stockout_risk = "CRITICAL"
        elif days_remaining < (lead_time_days + (safety_stock / max(d, 0.01))):
            stockout_risk = "HIGH"
        elif days_remaining > 60:
            stockout_risk = "OVERSTOCK"
        else:
            stockout_risk = "OPTIMAL"

        # 6. Recommended Order Quantity (accounts for incoming PO stock via inventory_position)
        is_reorder_needed = inventory_position <= reorder_point
        if is_reorder_needed:
            shortage = reorder_point - inventory_position
            recommended_qty = max(eoq, shortage + safety_stock)
        else:
            recommended_qty = 0

        estimated_order_cost = round(recommended_qty * unit_cost, 2)

        return {
            "product_id": product.id,
            "product_name": product.name,
            "sku": product.sku,
            "category": product.category,
            "current_stock": current_stock,
            "incoming_stock": incoming_stock,
            "reserved_stock": reserved_stock,
            "inventory_position": inventory_position,
            "supplier_id": supplier.id if supplier else None,
            "supplier_name": supplier.name if supplier else "Unassigned",
            "lead_time_days": lead_time_days,
            "service_level": service_level,
            "service_level_percent": f"{int(service_level * 100)}%",
            "daily_predicted_demand": round(d, 2),
            "safety_stock": safety_stock,
            "reorder_point": reorder_point,
            "economic_order_quantity": eoq,
            "days_inventory_remaining": days_remaining,
            "stockout_risk": stockout_risk,
            "is_reorder_needed": is_reorder_needed,
            "recommended_order_quantity": recommended_qty,
            "unit_cost": round(unit_cost, 2),
            "estimated_order_cost": estimated_order_cost,
        }

    @classmethod
    def get_all_recommendations(
        cls,
        db: Session,
        service_level: float = 0.95,
        business_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Calculates smart reorder recommendations across active catalog products.
        """
        query = db.query(Product).filter(Product.is_active == True)
        if business_id is not None:
            query = query.filter(Product.business_id == business_id)
        products = query.all()
        recommendations = []

        for p in products:
            try:
                metrics = cls.calculate_product_decision_metrics(db, product_id=p.id, service_level=service_level)
                recommendations.append(metrics)
            except Exception as e:
                print(f"Error computing decision metrics for product {p.id}: {e}")

        # Sort recommendations: CRITICAL first, then HIGH, then OPTIMAL, then OVERSTOCK
        risk_priority = {"CRITICAL": 0, "HIGH": 1, "OPTIMAL": 2, "OVERSTOCK": 3}
        recommendations.sort(key=lambda r: (risk_priority.get(r["stockout_risk"], 9), r["days_inventory_remaining"]))
        return recommendations
