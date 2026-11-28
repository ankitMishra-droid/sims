from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..models.intelligence import ReplenishmentRecommendation
from ..models.products import Product
from ..services.procurement_service import ProcurementService
from .decision_service import InventoryDecisionService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


ACTIONABLE_TYPES = {
    "REORDER_NOW",
    "LOW_STOCK_RISK",
    "OVERSTOCK_ALERT",
    "DEMAND_INCREASING",
    "DEMAND_DECREASING",
    "SUPPLIER_LEAD_TIME_RISK",
    "COLD_START_REVIEW",
}

OPEN_STATUSES = {"NEW", "VIEWED", "ACCEPTED"}


class RecommendationLifecycleService:
    """
    Persists, deduplicates, explains, and manages lifecycle transitions
    for inventory intelligence & replenishment recommendations.
    Never modifies stock directly; converts confirmed recommendations strictly
    to DRAFT Purchase Orders via ProcurementService.
    """

    @staticmethod
    def _build_dedup_key(business_id: int, product_id: int, rec_type: str) -> str:
        return f"biz:{business_id}:prod:{product_id}:cat:{rec_type}"

    @classmethod
    def sync_workspace_recommendations(
        cls,
        db: Session,
        business_id: int,
        service_level: Optional[float] = None,
        *,
        decisions: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recompute product decision snapshots across active SKUs in business_id and
        synchronize persisted ReplenishmentRecommendation rows without duplicates.
        """
        if decisions is None:
            decisions = InventoryDecisionService.get_all_recommendations(
                db=db,
                service_level=service_level,
                business_id=business_id,
            )
        now = _utcnow()
        dismissed_cutoff = now - timedelta(days=7)
        active_dedup_keys: set[str] = set()

        # Prefetch all open and recently dismissed rows in a single query to avoid 2N+1 lookups
        existing_rows = (
            db.query(ReplenishmentRecommendation)
            .filter(
                ReplenishmentRecommendation.business_id == business_id,
                (
                    ReplenishmentRecommendation.status.in_(list(OPEN_STATUSES))
                    | (
                        (ReplenishmentRecommendation.status == "DISMISSED")
                        & (ReplenishmentRecommendation.actioned_at >= dismissed_cutoff)
                    )
                ),
            )
            .order_by(ReplenishmentRecommendation.id.desc())
            .all()
        )
        open_by_key: Dict[str, ReplenishmentRecommendation] = {}
        recent_dismissed_by_key: Dict[str, ReplenishmentRecommendation] = {}
        for row in existing_rows:
            if row.status in OPEN_STATUSES:
                if row.dedup_key not in open_by_key:
                    open_by_key[row.dedup_key] = row
            elif row.status == "DISMISSED":
                if row.dedup_key not in recent_dismissed_by_key:
                    recent_dismissed_by_key[row.dedup_key] = row

        for d in decisions:
            rec_type = str(d["recommendation_type"])
            if rec_type not in ACTIONABLE_TYPES:
                continue

            dedup_key = cls._build_dedup_key(business_id, int(d["product_id"]), rec_type)
            active_dedup_keys.add(dedup_key)

            existing_open = open_by_key.get(dedup_key)
            if existing_open is None:
                recent_dismissed = recent_dismissed_by_key.get(dedup_key)
                if recent_dismissed is not None:
                    # Only re-open if urgency escalated to CRITICAL or inventory dropped materially
                    was_critical = recent_dismissed.urgency == "CRITICAL"
                    escalated = d["urgency"] == "CRITICAL" and not was_critical
                    dropped = int(d["inventory_position"]) < recent_dismissed.inventory_position
                    if not (escalated or dropped):
                        continue

            if existing_open is None:
                rec = ReplenishmentRecommendation(
                    business_id=business_id,
                    product_id=int(d["product_id"]),
                    dedup_key=dedup_key,
                    recommendation_type=rec_type,
                    status="NEW",
                )
                db.add(rec)
            else:
                rec = existing_open

            cls._apply_snapshot_to_model(rec, d, now)

        # Expire stale OPEN recommendations whose condition resolved (no longer triggered)
        for dedup_key, rec in open_by_key.items():
            if dedup_key not in active_dedup_keys:
                rec.status = "EXPIRED"
                rec.updated_at = now

        db.commit()
        return cls.list_recommendations(db=db, business_id=business_id, status_filter=None)

    @staticmethod
    def _apply_snapshot_to_model(
        rec: ReplenishmentRecommendation,
        d: Dict[str, Any],
        now: datetime,
    ) -> None:
        rec.supplier_id = d.get("supplier_id")
        rec.urgency = str(d.get("urgency", "MEDIUM"))
        rec.on_hand_stock = int(d.get("on_hand_stock", 0))
        rec.incoming_stock = int(d.get("incoming_stock", 0))
        rec.reserved_stock = int(d.get("reserved_stock", 0))
        rec.inventory_position = int(d.get("inventory_position", 0))
        rec.avg_daily_demand = float(d.get("avg_daily_demand", 0.0))
        rec.demand_std_dev = float(d.get("demand_std_dev", 0.0))
        rec.lead_time_days = float(d.get("lead_time_days", 7.0))
        rec.lead_time_std_days = float(d.get("lead_time_std_days", 0.0))
        rec.lead_time_source = str(d.get("lead_time_source", "supplier_default"))
        rec.review_period_days = int(d.get("review_period_days", 7))
        rec.service_level = float(d.get("service_level", 0.95))
        rec.lead_time_demand = float(d.get("lead_time_demand", 0.0))
        rec.safety_stock = int(d.get("safety_stock", 0))
        rec.reorder_point = int(d.get("reorder_point", 0))
        rec.target_stock_level = int(d.get("target_stock_level", 0))
        rec.suggested_order_qty = int(d.get("suggested_order_qty", 0))
        rec.days_of_cover_on_hand = d.get("days_of_cover_on_hand")
        rec.days_of_cover_position = d.get("days_of_cover_position")
        stockout_str = d.get("projected_stockout_date")
        if stockout_str:
            try:
                rec.projected_stockout_date = datetime.strptime(stockout_str, "%Y-%m-%d")
            except ValueError:
                rec.projected_stockout_date = None
        else:
            rec.projected_stockout_date = None
        rec.estimated_order_cost = float(d.get("estimated_order_cost", 0.0))
        rec.forecast_model_used = d.get("forecast_model_used")
        rec.data_sufficiency = str(d.get("data_sufficiency", "NEW"))
        rec.explanation_summary = str(d.get("explanation_summary", ""))
        rec.explanation_details_json = json.dumps(d.get("explanation_details", {}))
        rec.expires_at = now + timedelta(days=7)
        rec.updated_at = now

    @staticmethod
    def _serialize(rec: ReplenishmentRecommendation, product: Optional[Product]) -> Dict[str, Any]:
        return {
            "id": rec.id,
            "business_id": rec.business_id,
            "product_id": rec.product_id,
            "sku": product.sku if product else None,
            "product_name": product.name if product else f"Product #{rec.product_id}",
            "category": product.category if product else None,
            "unit": product.unit if product else "piece",
            "unit_cost": round(float(product.cost_price or 0.0), 2) if product else 0.0,
            "supplier_id": rec.supplier_id,
            "recommendation_type": rec.recommendation_type,
            "urgency": rec.urgency,
            "status": rec.status,
            "on_hand_stock": rec.on_hand_stock,
            "incoming_stock": rec.incoming_stock,
            "reserved_stock": rec.reserved_stock,
            "inventory_position": rec.inventory_position,
            "avg_daily_demand": round(float(rec.avg_daily_demand or 0.0), 3),
            "demand_std_dev": round(float(rec.demand_std_dev or 0.0), 3),
            "lead_time_days": round(float(rec.lead_time_days or 0.0), 2),
            "lead_time_std_days": round(float(rec.lead_time_std_days or 0.0), 2),
            "lead_time_source": rec.lead_time_source,
            "review_period_days": rec.review_period_days,
            "service_level": rec.service_level,
            "lead_time_demand": round(float(rec.lead_time_demand or 0.0), 2),
            "safety_stock": rec.safety_stock,
            "reorder_point": rec.reorder_point,
            "target_stock_level": rec.target_stock_level,
            "suggested_order_qty": rec.suggested_order_qty,
            "adjusted_order_qty": rec.adjusted_order_qty,
            "days_of_cover_on_hand": rec.days_of_cover_on_hand,
            "days_of_cover_position": rec.days_of_cover_position,
            "projected_stockout_date": rec.projected_stockout_date.strftime("%Y-%m-%d")
            if rec.projected_stockout_date
            else None,
            "estimated_order_cost": round(float(rec.estimated_order_cost or 0.0), 2),
            "forecast_model_used": rec.forecast_model_used,
            "data_sufficiency": rec.data_sufficiency,
            "explanation_summary": rec.explanation_summary,
            "explanation_details": json.loads(rec.explanation_details_json or "{}"),
            "linked_purchase_order_id": rec.linked_purchase_order_id,
            "dismiss_reason": rec.dismiss_reason,
            "actioned_at": rec.actioned_at.isoformat() + "Z" if rec.actioned_at else None,
            "updated_at": rec.updated_at.isoformat() + "Z" if rec.updated_at else None,
        }

    @classmethod
    def list_recommendations(
        cls,
        db: Session,
        business_id: int,
        status_filter: Optional[str] = "OPEN",
        recommendation_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = (
            db.query(ReplenishmentRecommendation, Product)
            .join(Product, ReplenishmentRecommendation.product_id == Product.id)
            .filter(
                ReplenishmentRecommendation.business_id == business_id,
                Product.business_id == business_id,
            )
        )
        if status_filter == "OPEN":
            query = query.filter(ReplenishmentRecommendation.status.in_(list(OPEN_STATUSES)))
        elif status_filter and status_filter != "ALL":
            query = query.filter(ReplenishmentRecommendation.status == status_filter.upper())

        if recommendation_type and recommendation_type != "ALL":
            query = query.filter(
                ReplenishmentRecommendation.recommendation_type == recommendation_type.upper()
            )

        rows = query.all()
        urgency_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
        serialized = [cls._serialize(rec, prod) for rec, prod in rows]
        serialized.sort(
            key=lambda r: (
                urgency_rank.get(r["urgency"], 9),
                -r["suggested_order_qty"],
                r["product_id"],
            )
        )
        return serialized

    @classmethod
    def get_recommendation(
        cls,
        db: Session,
        business_id: int,
        recommendation_id: int,
        *,
        mark_viewed: bool = False,
    ) -> Dict[str, Any]:
        row = (
            db.query(ReplenishmentRecommendation, Product)
            .join(Product, ReplenishmentRecommendation.product_id == Product.id)
            .filter(
                ReplenishmentRecommendation.id == recommendation_id,
                ReplenishmentRecommendation.business_id == business_id,
                Product.business_id == business_id,
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Recommendation not found in workspace")
        rec, prod = row
        if mark_viewed and rec.status == "NEW":
            rec.status = "VIEWED"
            db.commit()
            db.refresh(rec)
        return cls._serialize(rec, prod)

    @classmethod
    def accept_recommendation(
        cls,
        db: Session,
        business_id: int,
        user_id: int,
        recommendation_id: int,
        adjusted_order_qty: Optional[int] = None,
    ) -> Dict[str, Any]:
        rec = (
            db.query(ReplenishmentRecommendation)
            .filter(
                ReplenishmentRecommendation.id == recommendation_id,
                ReplenishmentRecommendation.business_id == business_id,
            )
            .first()
        )
        if not rec:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if rec.status == "CONVERTED_TO_PO":
            raise HTTPException(status_code=400, detail="Recommendation has already been converted to a PO")
        if rec.status == "EXPIRED":
            raise HTTPException(status_code=400, detail="Expired recommendation cannot be accepted")

        rec.status = "ACCEPTED"
        if adjusted_order_qty is not None:
            if adjusted_order_qty <= 0:
                raise HTTPException(status_code=400, detail="adjusted_order_qty must be positive")
            rec.adjusted_order_qty = adjusted_order_qty
        rec.actioned_by_user_id = user_id
        rec.actioned_at = _utcnow()
        db.commit()
        db.refresh(rec)
        prod = db.query(Product).filter(Product.id == rec.product_id).first()
        return cls._serialize(rec, prod)

    @classmethod
    def dismiss_recommendation(
        cls,
        db: Session,
        business_id: int,
        user_id: int,
        recommendation_id: int,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        rec = (
            db.query(ReplenishmentRecommendation)
            .filter(
                ReplenishmentRecommendation.id == recommendation_id,
                ReplenishmentRecommendation.business_id == business_id,
            )
            .first()
        )
        if not rec:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if rec.status == "CONVERTED_TO_PO":
            raise HTTPException(status_code=400, detail="Converted recommendation cannot be dismissed")

        rec.status = "DISMISSED"
        rec.dismiss_reason = (reason or "").strip() or None
        rec.actioned_by_user_id = user_id
        rec.actioned_at = _utcnow()
        db.commit()
        db.refresh(rec)
        prod = db.query(Product).filter(Product.id == rec.product_id).first()
        return cls._serialize(rec, prod)

    @classmethod
    def convert_recommendation_to_po(
        cls,
        db: Session,
        business_id: int,
        user_id: int,
        recommendation_id: int,
        *,
        supplier_id: Optional[int] = None,
        ordered_quantity: Optional[int] = None,
        expected_delivery_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convert a reviewed recommendation into a DRAFT Purchase Order via ProcurementService.
        Enforces confirmation & idempotency: never increases stock directly.
        """
        rec = (
            db.query(ReplenishmentRecommendation)
            .filter(
                ReplenishmentRecommendation.id == recommendation_id,
                ReplenishmentRecommendation.business_id == business_id,
            )
            .first()
        )
        if not rec:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if rec.status == "CONVERTED_TO_PO" and rec.linked_purchase_order_id is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Recommendation already converted to PO #{rec.linked_purchase_order_id}",
            )
        if rec.status in ("DISMISSED", "EXPIRED"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot convert recommendation in status {rec.status}",
            )

        prod = (
            db.query(Product)
            .filter(Product.id == rec.product_id, Product.business_id == business_id)
            .first()
        )
        if not prod:
            raise HTTPException(status_code=404, detail="Product not found in workspace")

        target_supplier = supplier_id or rec.supplier_id or prod.supplier_id
        if not target_supplier:
            raise HTTPException(
                status_code=400,
                detail="Please select a supplier before creating a purchase order.",
            )

        qty = ordered_quantity or rec.adjusted_order_qty or rec.suggested_order_qty
        if qty <= 0:
            raise HTTPException(
                status_code=400,
                detail="Order quantity must be greater than 0.",
            )

        exp_dt = None
        if expected_delivery_date:
            try:
                exp_dt = datetime.strptime(expected_delivery_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid expected_delivery_date (expected YYYY-MM-DD)",
                )

        po_payload = schemas.PurchaseOrderCreate(
            supplier_id=target_supplier,
            expected_delivery_date=exp_dt,
            notes=notes or f"Created from recommendation #{rec.id}: {rec.explanation_summary[:180]}",
            items=[
                schemas.PurchaseOrderItemCreate(
                    product_id=prod.id,
                    ordered_quantity=qty,
                    unit_cost=float(prod.cost_price or 0.0),
                )
            ],
        )
        po = ProcurementService.create_purchase_order(
            db=db,
            business_id=business_id,
            user_id=user_id,
            payload=po_payload,
        )

        rec.status = "CONVERTED_TO_PO"
        rec.adjusted_order_qty = qty
        rec.linked_purchase_order_id = po.id
        rec.actioned_by_user_id = user_id
        rec.actioned_at = _utcnow()
        db.commit()
        db.refresh(rec)

        return {
            "status": "success",
            "message": f"Draft purchase order '{po.order_number}' created from recommendation #{rec.id}.",
            "recommendation": cls._serialize(rec, prod),
            "purchase_order_id": po.id,
            "order_number": po.order_number,
            "total_amount": round(float(po.total_amount or 0.0), 2),
        }
