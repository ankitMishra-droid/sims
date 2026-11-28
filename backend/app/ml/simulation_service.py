import math
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..models.products import Product
from .decision_service import InventoryDecisionService
from .forecasting_service import ForecastingService


class ScenarioSimulationService:
    """
    What-If Business Scenario Simulator.
    Uses empirical demand variance, supplier lead-time variability, and current
    inventory position to stress-test depletion trajectories and buffer sizing.
    """

    @classmethod
    def run_simulation(
        cls,
        db: Session,
        product_id: int,
        simulation_horizon_days: int = 60,
        demand_multiplier: float = 1.0,
        lead_time_delay_days: int = 0,
        service_level: float = 0.95,
        planned_restock_qty: int = 0,
        restock_day: int = 14,
        *,
        business_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        query = db.query(Product).filter(Product.id == product_id)
        if business_id is not None:
            query = query.filter(Product.business_id == business_id)
        product = query.first()
        if not product:
            raise ValueError(f"Product ID {product_id} not found.")

        eff_biz_id = product.business_id
        baseline_metrics = InventoryDecisionService.calculate_product_decision_metrics(
            db,
            product_id=product.id,
            service_level=service_level,
            business_id=eff_biz_id,
        )

        forecast_res = ForecastingService.generate_product_forecast(
            db,
            product_id=product.id,
            horizon_days=simulation_horizon_days,
            model_choice="auto",
            business_id=eff_biz_id,
        )
        base_predictions = [pt["predicted_demand"] for pt in forecast_res["forecast_series"]]
        sim_demands = [round(max(0.0, d * demand_multiplier), 2) for d in base_predictions]

        initial_stock = float(product.current_stock or 0)
        current_stock = initial_stock
        stockout_projected = False
        stockout_day = None
        stockout_date = None
        stockout_duration_days = 0
        total_lost_units = 0.0
        trajectory = []
        unit_price = float(product.selling_price or 0.0)

        for day_idx, daily_demand in enumerate(sim_demands, start=1):
            date_str = forecast_res["forecast_series"][day_idx - 1]["date"]

            if planned_restock_qty > 0 and day_idx == restock_day:
                current_stock += planned_restock_qty

            if current_stock >= daily_demand:
                current_stock -= daily_demand
                is_stockout = False
                unmet_demand = 0.0
            else:
                unmet_demand = daily_demand - max(0.0, current_stock)
                current_stock = 0.0
                is_stockout = True
                stockout_duration_days += 1
                total_lost_units += unmet_demand
                if not stockout_projected:
                    stockout_projected = True
                    stockout_day = day_idx
                    stockout_date = date_str

            trajectory.append(
                {
                    "day": day_idx,
                    "date": date_str,
                    "simulated_demand": daily_demand,
                    "projected_stock": round(current_stock, 1),
                    "is_stockout": is_stockout,
                    "unmet_demand": round(unmet_demand, 1),
                }
            )

        estimated_lost_revenue = round(total_lost_units * unit_price, 2)

        sim_lead_time = float(baseline_metrics["lead_time_days"]) + float(lead_time_delay_days)
        sim_d = float(baseline_metrics["daily_predicted_demand"]) * demand_multiplier
        base_sigma_d = float(baseline_metrics.get("demand_std_dev") or (baseline_metrics["daily_predicted_demand"] * 0.35))
        sim_sigma_d = base_sigma_d * demand_multiplier
        sigma_L = max(float(baseline_metrics.get("lead_time_std_days") or 0.5), 0.5 if sim_d > 0 else 0.0)
        Z = InventoryDecisionService.get_z_score(service_level)

        if sim_d > 0:
            revised_safety_stock = math.ceil(
                Z * math.sqrt(max(0.0, sim_lead_time * (sim_sigma_d ** 2) + (sim_d ** 2) * (sigma_L ** 2)))
            )
            revised_rop = math.ceil((sim_d * sim_lead_time) + revised_safety_stock)
        else:
            revised_safety_stock = 0
            revised_rop = 0

        return {
            "product_id": product.id,
            "business_id": eff_biz_id,
            "product_name": product.name,
            "sku": product.sku,
            "simulation_parameters": {
                "horizon_days": simulation_horizon_days,
                "demand_multiplier": demand_multiplier,
                "demand_change_percent": f"{round((demand_multiplier - 1.0) * 100):+d}%",
                "lead_time_delay_days": lead_time_delay_days,
                "total_effective_lead_time": round(sim_lead_time, 2),
                "service_level": service_level,
                "planned_restock_qty": planned_restock_qty,
                "restock_day": restock_day,
            },
            "baseline": {
                "initial_stock": initial_stock,
                "incoming_stock": baseline_metrics["incoming_stock"],
                "inventory_position": baseline_metrics["inventory_position"],
                "safety_stock": baseline_metrics["safety_stock"],
                "reorder_point": baseline_metrics["reorder_point"],
                "stockout_risk": baseline_metrics["stockout_risk"],
            },
            "simulation_result": {
                "stockout_projected": stockout_projected,
                "stockout_day": stockout_day,
                "stockout_date": stockout_date,
                "stockout_duration_days": stockout_duration_days,
                "total_lost_units": round(total_lost_units, 1),
                "estimated_lost_revenue": estimated_lost_revenue,
                "revised_safety_stock_needed": revised_safety_stock,
                "revised_reorder_point": revised_rop,
            },
            "trajectory": trajectory,
        }
