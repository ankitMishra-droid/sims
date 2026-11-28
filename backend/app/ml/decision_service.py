from datetime import datetime, timedelta, timezone
import math
from statistics import NormalDist
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models.products import Product
from ..services.inventory_service import InventoryService
from .forecasting_service import ForecastingService
from .lead_time_service import SupplierLeadTimeService

_STD_NORMAL = NormalDist()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryDecisionService:
    """
    Production Replenishment & Inventory Risk Engine.
    Computes exact tenant-isolated metrics using:
    - InventoryPosition = OnHand + Incoming(SENT/PARTIALLY_RECEIVED POs) - Reserved
    - LeadTimeDemand = AvgDailyDemand * EffectiveLeadTime
    - SafetyStock = Z(service_level) * sqrt(L * sigma_d^2 + d^2 * sigma_L^2)
    - ReorderPoint = ceil(LeadTimeDemand + SafetyStock)
    - TargetStock = ceil(d * (L + ReviewPeriod) + SafetyStock) bounded by optional max_stock_level
    - SuggestedOrderQty constrained cleanly by MOQ, OrderPackSize, and MaxStockLevel
    """

    @classmethod
    def get_z_score(cls, service_level: float = 0.95) -> float:
        clamped = min(max(float(service_level or 0.95), 0.50), 0.9999)
        return float(_STD_NORMAL.inv_cdf(clamped))

    @staticmethod
    def apply_ordering_constraints(
        raw_need: int,
        inventory_position: int,
        *,
        min_order_quantity: int = 1,
        order_pack_size: int = 1,
        max_stock_level: Optional[int] = None,
    ) -> tuple[int, List[str]]:
        """
        Apply MOQ, pack-size rounding, and max-stock cap cleanly without fabricating demand.
        Returns (constrained_qty, constraint_notes).
        """
        notes: List[str] = []
        if raw_need <= 0:
            return 0, notes

        pack = max(1, order_pack_size or 1)
        moq = max(1, min_order_quantity or 1)

        qty = raw_need
        if pack > 1:
            rounded = math.ceil(qty / pack) * pack
            if rounded != qty:
                notes.append(f"Rounded up from {qty} to pack multiple of {pack} -> {rounded}.")
            qty = rounded

        if qty < moq:
            moq_rounded = math.ceil(moq / pack) * pack
            notes.append(f"Raised to supplier MOQ ({moq}, pack={pack}) -> {moq_rounded}.")
            qty = moq_rounded

        if max_stock_level is not None and max_stock_level > 0:
            room = max(0, max_stock_level - inventory_position)
            if room == 0:
                notes.append(f"Capped at 0 because inventory position ({inventory_position}) meets max stock ({max_stock_level}).")
                return 0, notes
            if qty > room:
                capped = (room // pack) * pack if pack > 1 else room
                if capped < moq:
                    notes.append(
                        f"Max stock cap ({max_stock_level}) allows {room} units, which is below MOQ ({moq})."
                    )
                else:
                    notes.append(f"Capped from {qty} to {capped} to respect max stock level ({max_stock_level}).")
                qty = max(0, capped)

        return max(0, qty), notes

    @classmethod
    def calculate_product_decision_metrics(
        cls,
        db: Session,
        product_id: int,
        service_level: Optional[float] = None,
        ordering_cost: float = 50.0,
        holding_cost_rate: float = 0.20,
        *,
        business_id: Optional[int] = None,
        force_forecast_refresh: bool = False,
        _product: Optional[Product] = None,
        _incoming_stock: Optional[int] = None,
        _lead_stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if _product is not None:
            product = _product
        else:
            query = db.query(Product).filter(Product.id == product_id)
            if business_id is not None:
                query = query.filter(Product.business_id == business_id)
            product = query.first()
            if not product:
                raise ValueError(f"Product ID {product_id} not found.")

        eff_biz_id = product.business_id
        eff_service_level = float(
            service_level
            if service_level is not None
            else (getattr(product, "service_level_target", None) or 0.95)
        )
        review_period = product.review_period_days or 7
        moq = max(1, product.min_order_quantity or 1)
        pack_size = max(1, product.order_pack_size or 1)
        max_stock = product.max_stock_level

        lead_stats = (
            _lead_stats
            if _lead_stats is not None
            else SupplierLeadTimeService.get_supplier_lead_time_stats(
                db, eff_biz_id, product.supplier_id
            )
        )
        L = float(lead_stats["effective_lead_time_days"])
        sigma_L = float(lead_stats["lead_time_std_days"])
        protection_days = L + float(review_period)

        forecast_horizon = max(30, min(90, math.ceil(protection_days)))
        forecast_res = ForecastingService.generate_product_forecast(
            db=db,
            product_id=product.id,
            horizon_days=forecast_horizon,
            model_choice="auto",
            business_id=eff_biz_id,
            force_refresh=force_forecast_refresh,
            include_historical_series=False,
        )

        hist = forecast_res.get("historical_summary") or {}
        d = max(0.0, float(forecast_res.get("avg_predicted_daily_demand") or 0.0))
        hist_d = max(0.0, float(hist.get("avg_daily_demand") or 0.0))
        sigma_d = max(0.0, float(hist.get("demand_std_dev") or 0.0))
        eval_metrics = forecast_res.get("evaluation_metrics") or {}
        if sigma_d <= 0 and d > 0:
            sigma_d = float(eval_metrics.get("rmse") or (d * 0.45))

        Z = cls.get_z_score(eff_service_level)

        current_stock = product.current_stock or 0
        if _incoming_stock is not None:
            incoming_stock = _incoming_stock
        else:
            incoming_map = InventoryService.get_incoming_stock_map(db, eff_biz_id, [product.id])
            incoming_stock = incoming_map.get(product.id, 0)
        reserved_stock = 0
        inventory_position = current_stock + incoming_stock - reserved_stock

        unit_cost = float(product.cost_price or (float(product.selling_price or 0.0) * 0.7) or 0.0)
        annual_holding_cost = max(1.0, unit_cost * holding_cost_rate)

        sufficiency = forecast_res.get("data_sufficiency", "NEW")
        is_cold_start = bool(forecast_res.get("is_cold_start", False))

        if d > 0.0:
            lead_time_demand = round(d * L, 2)
            variance_term = (L * (sigma_d ** 2)) + ((d ** 2) * (sigma_L ** 2))
            safety_stock = math.ceil(Z * math.sqrt(max(0.0, variance_term)))
            reorder_point = math.ceil(lead_time_demand + safety_stock)
            raw_target = math.ceil((d * protection_days) + safety_stock)
            target_stock = min(raw_target, max_stock) if (max_stock and max_stock > 0) else raw_target
            annual_demand = d * 365.0
            eoq = math.ceil(math.sqrt((2.0 * annual_demand * ordering_cost) / annual_holding_cost))
            days_cover_on_hand: Optional[float] = round(current_stock / d, 1)
            cover_pos_val = round(inventory_position / d, 1)
            days_cover_position: Optional[float] = cover_pos_val
            stockout_dt = _utcnow() + timedelta(days=cover_pos_val)
            projected_stockout_date = stockout_dt.strftime("%Y-%m-%d")
        else:
            lead_time_demand = 0.0
            safety_stock = 0
            reorder_point = 0
            target_stock = 0
            eoq = 0
            days_cover_on_hand = None
            days_cover_position = None
            projected_stockout_date = None

        manual_rop = product.reorder_level or 0
        is_reorder_needed = (d > 0.0 and inventory_position <= reorder_point)
        raw_shortfall = max(0, target_stock - inventory_position) if is_reorder_needed else 0

        recommended_qty, constraint_notes = cls.apply_ordering_constraints(
            raw_shortfall,
            inventory_position,
            min_order_quantity=moq,
            order_pack_size=pack_size,
            max_stock_level=max_stock,
        )

        # Overstock & Dead-stock assessment
        days_since_last_sale = hist.get("days_since_last_sale")
        overstock_excess = 0
        overstock_risk = "NONE"
        if d > 0.0:
            overstock_cap = max(float(target_stock) * 1.75, d * 90.0)
            if inventory_position > overstock_cap:
                overstock_excess = round(inventory_position - overstock_cap)
                overstock_risk = "HIGH" if (days_cover_position or 0) > 120 else "MODERATE"
        elif current_stock > 0 and (days_since_last_sale is None or days_since_last_sale >= 60):
            # Inventory sitting with zero recent velocity
            overstock_excess = current_stock
            overstock_risk = "DEAD_STOCK" if (hist.get("history_days_observed", 0) >= 30) else "SLOW_OR_UNOBSERVED"

        # Stockout Risk classification based on cover vs lead time and inventory position
        if d <= 0.0:
            if current_stock == 0:
                stockout_risk = "CRITICAL" if manual_rop > 0 else "OPTIMAL"
            elif overstock_risk == "DEAD_STOCK":
                stockout_risk = "OVERSTOCK"
            else:
                stockout_risk = "OPTIMAL"
        else:
            pos_cover = days_cover_position or 0.0
            ss_cover = safety_stock / d
            if current_stock == 0 or pos_cover < L:
                stockout_risk = "CRITICAL"
            elif pos_cover < (L + ss_cover) or inventory_position <= reorder_point:
                stockout_risk = "HIGH"
            elif overstock_risk != "NONE":
                stockout_risk = "OVERSTOCK"
            else:
                stockout_risk = "OPTIMAL"

        # Determine primary actionable recommendation category & explanation
        trend_dir = hist.get("trend_direction", "INSUFFICIENT_DATA")
        trend_pct = hist.get("trend_pct_change")
        if is_cold_start and d == 0.0:
            rec_type = "COLD_START_REVIEW"
            urgency = "LOW" if current_stock == 0 else "INFO"
            explanation = (
                f"New or zero-sale SKU ({hist.get('history_days_observed', 0)}d observed). "
                f"Set an optional initial daily demand estimate or record initial sales before automated ordering."
            )
        elif recommended_qty > 0:
            rec_type = "REORDER_NOW"
            urgency = "CRITICAL" if stockout_risk == "CRITICAL" else "HIGH"
            explanation = (
                f"Inventory position ({inventory_position} = {current_stock} on hand + {incoming_stock} incoming) "
                f"is at or below ROP ({reorder_point}). Forecast demand is {d:.2f} {product.unit}/day "
                f"over {L:.1f}d lead time (+{review_period}d review, {int(eff_service_level * 100)}% SL -> {safety_stock} safety stock). "
                f"Suggested order: {recommended_qty} units to reach target stock {target_stock}."
            )
        elif is_reorder_needed and incoming_stock > 0:
            rec_type = "LOW_STOCK_RISK"
            urgency = "MEDIUM"
            explanation = (
                f"On-hand stock ({current_stock}) is tight, with {incoming_stock} incoming units on open POs."
            )
        elif current_stock <= manual_rop and incoming_stock > 0 and d > 0:
            rec_type = "LOW_STOCK_RISK"
            urgency = "LOW"
            explanation = (
                f"On-hand stock ({current_stock}) is below threshold ({manual_rop}), but {incoming_stock} incoming units "
                f"keep inventory position ({inventory_position}) above ROP ({reorder_point})."
            )
        elif overstock_risk in ("HIGH", "MODERATE", "DEAD_STOCK"):
            rec_type = "OVERSTOCK_ALERT"
            urgency = "MEDIUM" if overstock_risk == "HIGH" else "LOW"
            explanation = (
                f"Inventory position ({inventory_position}) exceeds 90-day / target buffer ({overstock_excess} excess units, "
                f"value Rs.{round(overstock_excess * unit_cost, 2):,.2f})."
            )
        elif lead_stats.get("delay_risk") == "HIGH":
            rec_type = "SUPPLIER_LEAD_TIME_RISK"
            urgency = "MEDIUM"
            explanation = (
                f"Supplier {lead_stats['supplier_name']} shows late deliveries on "
                f"{lead_stats.get('late_delivery_count', 0)}/{lead_stats.get('expected_checked_count', 0)} tracked POs; "
                f"effective lead time adjusted to {L:.1f}d (std {sigma_L:.1f}d)."
            )
        elif trend_dir == "INCREASING" and trend_pct is not None and d >= 0.25:
            rec_type = "DEMAND_INCREASING"
            urgency = "INFO"
            explanation = f"Recent demand rose {trend_pct:+.1f}% vs prior window; monitor stock cover ({days_cover_position or 'N/A'}d)."
        elif trend_dir == "DECREASING" and trend_pct is not None and hist_d >= 0.25:
            rec_type = "DEMAND_DECREASING"
            urgency = "INFO"
            explanation = f"Recent demand declined {trend_pct:+.1f}% vs prior window; avoid premature replenishment."
        else:
            rec_type = "HEALTHY"
            urgency = "LOW"
            explanation = (
                f"Healthy stock cover ({days_cover_position or 'N/A'}d position cover vs {L:.1f}d supplier lead time)."
            )

        if constraint_notes:
            explanation = f"{explanation} {' '.join(constraint_notes)}"

        estimated_order_cost = round(recommended_qty * unit_cost, 2)

        return {
            "product_id": product.id,
            "business_id": eff_biz_id,
            "product_name": product.name,
            "sku": product.sku,
            "category": product.category,
            "unit": product.unit,
            "current_stock": current_stock,
            "on_hand_stock": current_stock,
            "incoming_stock": incoming_stock,
            "reserved_stock": reserved_stock,
            "inventory_position": inventory_position,
            "supplier_id": lead_stats["supplier_id"],
            "supplier_name": lead_stats["supplier_name"],
            "lead_time_days": L,
            "lead_time_std_days": sigma_L,
            "lead_time_source": lead_stats["lead_time_source"],
            "lead_time_sample_count": lead_stats["sample_count"],
            "supplier_delay_risk": lead_stats["delay_risk"],
            "review_period_days": review_period,
            "protection_period_days": round(protection_days, 2),
            "service_level": eff_service_level,
            "service_level_percent": f"{round(eff_service_level * 100)}%",
            "daily_predicted_demand": round(d, 3),
            "avg_daily_demand": round(d, 3),
            "demand_std_dev": round(sigma_d, 3),
            "lead_time_demand": lead_time_demand,
            "safety_stock": safety_stock,
            "reorder_point": reorder_point,
            "manual_reorder_level": manual_rop,
            "target_stock_level": target_stock,
            "economic_order_quantity": eoq,
            "min_order_quantity": moq,
            "order_pack_size": pack_size,
            "max_stock_level": max_stock,
            "days_inventory_remaining": days_cover_on_hand if days_cover_on_hand is not None else (999.0 if current_stock > 0 else 0.0),
            "days_of_cover_on_hand": days_cover_on_hand,
            "days_of_cover_position": days_cover_position,
            "projected_stockout_date": projected_stockout_date,
            "stockout_risk": stockout_risk,
            "overstock_risk": overstock_risk,
            "overstock_excess_units": overstock_excess,
            "excess_inventory_value": round(overstock_excess * unit_cost, 2),
            "is_reorder_needed": is_reorder_needed,
            "recommended_order_quantity": recommended_qty,
            "suggested_order_qty": recommended_qty,
            "unit_cost": round(unit_cost, 2),
            "estimated_order_cost": estimated_order_cost,
            "data_sufficiency": sufficiency,
            "is_cold_start": is_cold_start,
            "forecast_model_used": forecast_res.get("model_used"),
            "stockout_days_count": int(forecast_res.get("stockout_days_count") or 0),
            "trend_direction": trend_dir,
            "trend_pct_change": trend_pct,
            "days_since_last_sale": days_since_last_sale,
            "recommendation_type": rec_type,
            "urgency": urgency,
            "explanation_summary": explanation,
            "explanation_details": {
                "formula": "TargetStock = ceil(d * (L + R) + SS); OrderQty = clamp_moq_pack(TargetStock - InventoryPosition)",
                "z_score": round(Z, 4),
                "demand_daily": round(d, 4),
                "demand_std_dev": round(sigma_d, 4),
                "lead_time_days": L,
                "lead_time_std_days": sigma_L,
                "review_period_days": review_period,
                "on_hand": current_stock,
                "incoming": incoming_stock,
                "reserved": reserved_stock,
                "inventory_position": inventory_position,
                "lead_time_demand": lead_time_demand,
                "safety_stock": safety_stock,
                "reorder_point": reorder_point,
                "target_stock_level": target_stock,
                "raw_shortfall": raw_shortfall,
                "constraint_notes": constraint_notes,
            },
        }

    @classmethod
    def get_all_recommendations(
        cls,
        db: Session,
        service_level: Optional[float] = 0.95,
        business_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if business_id is None:
            raise ValueError("business_id is required for tenant-isolated inventory recommendations.")
        products = (
            db.query(Product)
            .filter(Product.business_id == business_id, Product.is_active.is_(True))
            .order_by(Product.id.asc())
            .all()
        )
        incoming_map = InventoryService.get_incoming_stock_map(
            db, business_id, [p.id for p in products]
        )
        lead_cache: Dict[Optional[int], Dict[str, Any]] = {}
        results: List[Dict[str, Any]] = []
        for p in products:
            if p.supplier_id not in lead_cache:
                lead_cache[p.supplier_id] = SupplierLeadTimeService.get_supplier_lead_time_stats(
                    db, business_id, p.supplier_id
                )
            metrics = cls.calculate_product_decision_metrics(
                db=db,
                product_id=p.id,
                service_level=service_level,
                business_id=business_id,
                _product=p,
                _incoming_stock=incoming_map.get(p.id, 0),
                _lead_stats=lead_cache[p.supplier_id],
            )
            results.append(metrics)

        risk_priority = {"CRITICAL": 0, "HIGH": 1, "OPTIMAL": 2, "OVERSTOCK": 3}
        results.sort(
            key=lambda r: (
                risk_priority.get(r["stockout_risk"], 9),
                r["days_of_cover_position"] if r["days_of_cover_position"] is not None else 9999.0,
            )
        )
        return results
