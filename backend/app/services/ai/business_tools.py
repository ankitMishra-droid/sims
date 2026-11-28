"""RBAC- and tenant-authorized business data retrieval, reconciliation, and PO proposal tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ...core.ai_exceptions import AIInvalidRequestError
from ...core.permissions import role_has_permission
from ...dependencies.authorization import BusinessContext
from ...ml.decision_service import InventoryDecisionService
from ...ml.recommendation_service import OPEN_STATUSES
from ...models.intelligence import ProductForecast, ReplenishmentRecommendation
from ...models.inventory import InventoryLog
from ...models.products import Product
from ...models.purchase_order import PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus
from ...models.sales import Sale
from ...models.supplier import Supplier
from ...schemas.purchase_order_schema import PurchaseOrderCreate, PurchaseOrderItemCreate
from ...services.inventory_service import InventoryService
from ...services.procurement_service import ProcurementService
from .context_assembly import ToolEvidenceBlock
from .intent_classifier import IntentAnalysis
from .user_facing_labels import (
    humanize_internal_text,
    humanize_movement_type,
    humanize_po_status,
    humanize_priority,
    humanize_recommendation_type,
)

_SKU_OR_PO_RE = re.compile(r"\b([A-Za-z0-9]{2,}[_-][A-Za-z0-9_-]+)\b")
_LOW_RISK_TYPES = {"REORDER_NOW", "LOW_STOCK_RISK"}
_PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sales_window(query: str, days: int = 30) -> Tuple[datetime, datetime, str]:
    """Resolve common natural-language sales periods to a half-open date range."""
    now = _utcnow()
    q = (query or "").lower()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if "this month" in q or "current month" in q or "इस महीने" in q:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now, "month to date"
    if "last month" in q or "previous month" in q or "पिछले महीने" in q:
        this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = this_month
        start = (this_month - timedelta(days=1)).replace(day=1)
        return start, end, "previous calendar month"
    if "this week" in q or "current week" in q or "इस सप्ताह" in q:
        return today - timedelta(days=today.weekday()), now, "week to date"
    if "last week" in q or "previous week" in q or "पिछले सप्ताह" in q:
        this_monday = today - timedelta(days=today.weekday())
        return this_monday - timedelta(days=7), this_monday, "previous calendar week"
    if "today" in q or "आज" in q:
        return today, now, "today"
    return now - timedelta(days=days), now, f"last {days} days"


def _sales_totals(db: Session, ctx: BusinessContext, start: datetime, end: datetime) -> Dict[str, Any]:
    """Calculate all-transaction sales totals and bounded per-product metrics for one tenant."""
    filters = (
        Sale.business_id == ctx.business_id,
        Sale.status == "COMPLETED",
        Sale.sales_date >= start,
        Sale.sales_date < end,
    )
    totals = (
        db.query(
            func.coalesce(func.sum(Sale.revenue), 0.0),
            func.coalesce(func.sum(Sale.quantity_sold), 0),
            func.count(Sale.id),
        )
        .join(Product, Product.id == Sale.product_id)
        .filter(*filters, Product.business_id == ctx.business_id)
        .one()
    )
    sale_join = and_(
        Sale.product_id == Product.id,
        Sale.business_id == ctx.business_id,
        Sale.status == "COMPLETED",
        Sale.sales_date >= start,
        Sale.sales_date < end,
    )
    rows = (
        db.query(
            Product.sku,
            Product.name,
            Product.cost_price,
            func.coalesce(func.sum(Sale.quantity_sold), 0).label("units"),
            func.coalesce(func.sum(Sale.revenue), 0.0).label("revenue"),
            func.count(Sale.id).label("transactions"),
        )
        .select_from(Product)
        .outerjoin(Sale, sale_join)
        .filter(Product.business_id == ctx.business_id)
        .group_by(Product.id, Product.sku, Product.name, Product.cost_price)
        .all()
    )
    products: List[Dict[str, Any]] = []
    has_complete_cost_data = True
    estimated_cogs = 0.0
    for row in rows:
        units = int(row.units or 0)
        revenue = float(row.revenue or 0.0)
        unit_cost = float(row.cost_price or 0.0)
        cost_available = unit_cost > 0
        if cost_available and units:
            estimated_cogs += units * unit_cost
        elif units:
            has_complete_cost_data = False
        products.append(
            {
                "sku": row.sku,
                "name": row.name,
                "units_sold": units,
                "revenue": round(revenue, 2),
                "estimated_gross_profit": round(revenue - units * unit_cost, 2) if cost_available and units else None,
                "cost_data_available": cost_available,
                "transactions": int(row.transactions or 0),
            }
        )

    revenue = float(totals[0] or 0.0)
    units_sold = int(totals[1] or 0)
    transaction_count = int(totals[2] or 0)
    gross_profit = revenue - estimated_cogs if has_complete_cost_data and transaction_count else None
    return {
        "total_revenue": round(revenue, 2),
        "total_units_sold": units_sold,
        "transaction_count": transaction_count,
        "estimated_cogs": round(estimated_cogs, 2) if has_complete_cost_data and transaction_count else None,
        "estimated_gross_profit": round(gross_profit, 2) if gross_profit is not None else None,
        "estimated_gross_margin_percent": round(gross_profit / revenue * 100, 2)
        if gross_profit is not None and revenue > 0
        else None,
        "cost_data_complete": has_complete_cost_data,
        "products_missing_cost_count": sum(
            1 for product in products if product["units_sold"] > 0 and not product["cost_data_available"]
        ),
        "products": products,
    }


class AuthorizedBusinessTools:
    """Executes strictly typed, permission-checked, tenant-scoped business tools and reconciles data."""

    @staticmethod
    def _is_supplier_workspace(ctx: BusinessContext) -> bool:
        return (ctx.business.business_type or "").lower() == "supplier"

    @staticmethod
    def _check_perm(ctx: BusinessContext, perm: str) -> bool:
        return role_has_permission(ctx.role, perm)

    @classmethod
    def get_supplier_portal_orders(
        cls, db: Session, ctx: BusinessContext, *, limit: int = 25
    ) -> Optional[ToolEvidenceBlock]:
        if not cls._is_supplier_workspace(ctx) or not cls._check_perm(ctx, "supplier_portal.read"):
            return None
        orders = ProcurementService.list_supplier_portal_orders(db, ctx.business_id)[:limit]
        compact = [
            {
                "order_number": o["order_number"],
                "buyer_name": o["buyer_business_name"],
                "status": humanize_po_status(o["status"]),
                "supplier_status": humanize_po_status(o.get("supplier_status")) if o.get("supplier_status") else None,
                "total_amount": round(float(o.get("total_amount") or 0.0), 2),
                "expected_delivery_date": str(o["expected_delivery_date"]) if o["expected_delivery_date"] else None,
                "items_count": len(o.get("items") or []),
            }
            for o in orders
        ]
        return ToolEvidenceBlock(
            tool_name="get_supplier_portal_orders",
            source_kind="business_tool",
            summary=f"Shared purchase orders ({len(compact)} records)",
            data={
                "query_type": "supplier_portal_orders",
                "total_count": len(compact),
                "orders": compact,
            },
        )

    @classmethod
    def _fetch_open_po_map(
        cls, db: Session, business_id: int
    ) -> Dict[int, List[Dict[str, Any]]]:
        """Return active open incoming purchase order lines grouped by product_id."""
        if not business_id:
            return {}
        rows = (
            db.query(PurchaseOrderItem, PurchaseOrder)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
            .filter(
                PurchaseOrder.business_id == business_id,
                PurchaseOrder.status.in_(
                    [
                        PurchaseOrderStatus.DRAFT,
                        PurchaseOrderStatus.SENT,
                        PurchaseOrderStatus.PARTIALLY_RECEIVED,
                    ]
                ),
            )
            .all()
        )
        by_product: Dict[int, List[Dict[str, Any]]] = {}
        for item, po in rows:
            st_val = po.status.value if hasattr(po.status, "value") else str(po.status)
            remaining = max(0, int(item.ordered_quantity or 0) - int(item.received_quantity or 0))
            by_product.setdefault(int(item.product_id), []).append(
                {
                    "order_number": po.order_number,
                    "status": humanize_po_status(st_val),
                    "remaining_quantity": remaining,
                    "expected_delivery_date": (
                        po.expected_delivery_date.strftime("%Y-%m-%d") if po.expected_delivery_date else None
                    ),
                }
            )
        return by_product

    @classmethod
    def get_reconciled_inventory_intelligence(
        cls,
        db: Session,
        ctx: BusinessContext,
        *,
        intent: IntentAnalysis,
        query: str = "",
        page_context: Optional[Dict[str, Any]] = None,
        focus_product_ids: Sequence[int] = (),
    ) -> Tuple[Optional[ToolEvidenceBlock], List[Dict[str, Any]]]:
        """Reconcile authoritative physical stock, open POs, and forecast/replenishment by product_id.

        Returns `(ToolEvidenceBlock | None, focus_products_metadata)`.
        """
        if cls._is_supplier_workspace(ctx):
            return None, []

        can_read_inv = cls._check_perm(ctx, "inventory.read") or cls._check_perm(ctx, "products.read")
        can_read_intel = cls._check_perm(ctx, "intelligence.read")
        if not can_read_inv and not can_read_intel:
            return None, []

        data_warnings: List[str] = []

        # 1. Resolve target single product from page_context or resolved follow-up if scoped
        target_pids: List[int] = [int(pid) for pid in focus_product_ids if pid is not None]
        if page_context and page_context.get("product_id") is not None and not target_pids:
            try:
                target_pids = [int(page_context["product_id"])]
            except (TypeError, ValueError):
                pass

        # 2. Source of truth #1: Live inventory positions (Physical + Incoming + Reserved)
        live_positions: List[Dict[str, Any]] = []
        live_by_pid: Dict[int, Dict[str, Any]] = {}
        live_inventory_available = True
        if can_read_inv:
            try:
                live_positions = InventoryService.get_inventory_positions(db, ctx.business_id)
            except Exception:
                live_positions = []
                live_inventory_available = False
                data_warnings.append(
                    "Live inventory quantities could not be retrieved cleanly; verify physical stock before ordering."
                )

        seen_skus: Dict[str, int] = {}
        duplicate_skus: set[str] = set()
        for pos in live_positions:
            pid = pos.get("product_id")
            if pid is None:
                data_warnings.append("Encountered an inventory record missing a product identifier.")
                continue
            pid_int = int(pid)
            sku_norm = str(pos.get("sku") or "").strip().upper()
            if sku_norm:
                if sku_norm in seen_skus and seen_skus[sku_norm] != pid_int:
                    duplicate_skus.add(sku_norm)
                seen_skus[sku_norm] = pid_int

            on_hand_raw = pos.get("on_hand_stock")
            if isinstance(on_hand_raw, (int, float)) and on_hand_raw < 0:
                data_warnings.append(
                    f"{pos.get('name', 'Product')} ({sku_norm}) shows negative stock ({on_hand_raw}); verify the stock ledger."
                )
            live_by_pid[pid_int] = pos

        if duplicate_skus:
            data_warnings.append(
                f"Duplicate SKU identifier(s) detected ({', '.join(sorted(duplicate_skus))}); records matched by internal product ID."
            )

        # Load active Product ORM lookup in same tenant scope for validation & attributes
        active_products: Dict[int, Product] = {
            p.id: p
            for p in db.query(Product)
            .filter(Product.business_id == ctx.business_id, Product.is_active.is_(True))
            .order_by(Product.id.asc())
            .all()
        }

        # 3. Source of truth #2: Open replenishment recommendations & latest forecasts (active products only)
        recs_by_pid: Dict[int, ReplenishmentRecommendation] = {}
        forecasts_by_pid: Dict[int, ProductForecast] = {}
        if can_read_intel:
            open_recs = (
                db.query(ReplenishmentRecommendation)
                .join(Product, Product.id == ReplenishmentRecommendation.product_id)
                .filter(
                    ReplenishmentRecommendation.business_id == ctx.business_id,
                    ReplenishmentRecommendation.status.in_(list(OPEN_STATUSES)),
                    Product.business_id == ctx.business_id,
                    Product.is_active.is_(True),
                )
                .order_by(ReplenishmentRecommendation.updated_at.desc(), ReplenishmentRecommendation.id.desc())
                .all()
            )
            for rec in open_recs:
                pid_int = int(rec.product_id)
                # Keep the most actionable open recommendation per product_id without duplicate rows
                prev = recs_by_pid.get(pid_int)
                if prev is None or (
                    rec.recommendation_type in _LOW_RISK_TYPES and prev.recommendation_type not in _LOW_RISK_TYPES
                ):
                    recs_by_pid[pid_int] = rec

            # Detect any persisted recommendation missing from live active inventory (conflict / stale / empty live inventory)
            for pid_int in recs_by_pid:
                if can_read_inv and pid_int not in live_by_pid:
                    live_inventory_available = False

            fcs = (
                db.query(ProductForecast)
                .join(Product, Product.id == ProductForecast.product_id)
                .filter(
                    ProductForecast.business_id == ctx.business_id,
                    Product.business_id == ctx.business_id,
                    Product.is_active.is_(True),
                )
                .all()
            )
            for fc in fcs:
                forecasts_by_pid[int(fc.product_id)] = fc

        # Check open PO map and latest sale timestamps per product to spot stale forecasts cleanly
        open_po_map = cls._fetch_open_po_map(db, ctx.business_id) if cls._check_perm(ctx, "po.read") else {}
        latest_sales: Dict[int, datetime] = {
            int(pid): dt
            for pid, dt in db.query(Sale.product_id, func.max(Sale.sales_date))
            .filter(Sale.business_id == ctx.business_id, Sale.status == "COMPLETED")
            .group_by(Sale.product_id)
            .all()
            if pid is not None and dt is not None
        }

        # When neither live persisted recs exist for a low/reorder/forecast query AND user has intel permission,
        # compute live decisions across active products so responses stay accurate.
        live_decisions_by_pid: Dict[int, Dict[str, Any]] = {}
        if can_read_intel and active_products:
            # Determine which product IDs need live recalculation (either no cached rec OR stale vs live stock)
            if not recs_by_pid and (
                intent.flags.get("forecast")
                or intent.flags.get("reorder")
                or intent.flags.get("low_stock")
                or intent.flags.get("out_of_stock")
                or intent.wants_explanation
            ):
                computed = InventoryDecisionService.get_all_recommendations(
                    db=db, business_id=ctx.business_id
                )
                for d in computed:
                    live_decisions_by_pid[int(d["product_id"])] = d
            else:
                for pid_int in recs_by_pid:
                    live_pos = live_by_pid.get(pid_int)
                    rec = recs_by_pid[pid_int]
                    stock_changed = live_pos is not None and (
                        int(live_pos.get("on_hand_stock", 0)) != int(rec.on_hand_stock)
                        or int(live_pos.get("incoming_stock", 0)) != int(rec.incoming_stock)
                    )
                    if stock_changed and pid_int in active_products:
                        live_decisions_by_pid[pid_int] = (
                            InventoryDecisionService.calculate_product_decision_metrics(
                                db=db, product_id=pid_int, business_id=ctx.business_id
                            )
                        )

        # Conflict check: empty live inventory or partial missing physical stock vs non-empty recommendations
        if can_read_inv and not live_by_pid and recs_by_pid:
            live_inventory_available = False
            data_warnings.append(
                f"{len(recs_by_pid)} product(s) are flagged in replenishment forecasts, but latest physical stock quantities could not be verified from inventory records."
            )
        elif can_read_inv and any(pid not in live_by_pid for pid in recs_by_pid):
            missing_names = [
                active_products[pid].name for pid in recs_by_pid if pid not in live_by_pid and pid in active_products
            ]
            if missing_names:
                live_inventory_available = False
                data_warnings.append(
                    f"Latest physical stock could not be verified for: {', '.join(missing_names[:5])}."
                )

        # 4. Merge by validated product_id into unified normalized product records
        all_pids = sorted(set(live_by_pid.keys()) | set(recs_by_pid.keys()) | set(live_decisions_by_pid.keys()))
        merged_records: List[Dict[str, Any]] = []
        any_stale_forecast = False

        for pid in all_pids:
            prod = active_products.get(pid)
            live_pos = live_by_pid.get(pid)
            rec = recs_by_pid.get(pid)
            live_dec = live_decisions_by_pid.get(pid)
            fc = forecasts_by_pid.get(pid)

            # Skip orphan/archived product entries without active Product backing
            if prod is None and live_pos is None:
                data_warnings.append(f"Excluded an archived or unknown product reference (ID {pid}).")
                continue

            name = (live_pos.get("name") if live_pos else None) or (prod.name if prod else None)
            sku = (live_pos.get("sku") if live_pos else None) or (prod.sku if prod else None)
            if not name or not sku:
                continue

            physical_verified = live_pos is not None
            on_hand: Optional[int] = int(live_pos["on_hand_stock"]) if live_pos and live_pos.get("on_hand_stock") is not None else None
            reserved: int = int(live_pos.get("reserved_stock") or 0) if live_pos else 0
            incoming: int = int(live_pos.get("incoming_stock") or 0) if live_pos else (
                int(rec.incoming_stock) if rec else 0
            )
            available: Optional[int] = (on_hand - reserved) if on_hand is not None else None
            inv_position: Optional[int] = (on_hand + incoming - reserved) if on_hand is not None else None
            manual_rop = int(live_pos.get("reorder_level") or 0) if live_pos else int(prod.reorder_level or 0 if prod else 0)
            unit_cost = float(live_pos.get("unit_cost") or 0.0) if live_pos else float(prod.cost_price or 0.0 if prod else 0.0)

            # Forecast / replenishment overlay
            if live_dec is not None:
                rec_type = str(live_dec.get("recommendation_type") or "")
                urgency_raw = str(live_dec.get("urgency") or "INFO")
                dynamic_rop: Optional[int] = live_dec.get("reorder_point")
                safety_stock: Optional[int] = live_dec.get("safety_stock")
                avg_daily_demand: Optional[float] = live_dec.get("avg_daily_demand")
                lead_time_days: Optional[float] = live_dec.get("lead_time_days")
                suggested_qty: Optional[int] = live_dec.get("suggested_order_qty")
                days_cover_oh: Optional[float] = live_dec.get("days_of_cover_on_hand")
                days_cover_pos: Optional[float] = live_dec.get("days_of_cover_position")
                reason_raw = str(live_dec.get("explanation_summary") or "")
                stockout_risk_raw = str(live_dec.get("stockout_risk") or "")
            elif rec is not None:
                rec_type = str(rec.recommendation_type or "")
                urgency_raw = str(rec.urgency or "INFO")
                dynamic_rop = rec.reorder_point
                safety_stock = rec.safety_stock
                avg_daily_demand = round(float(rec.avg_daily_demand), 2) if rec.avg_daily_demand is not None else None
                lead_time_days = round(float(rec.lead_time_days), 1) if rec.lead_time_days is not None else None
                suggested_qty = rec.adjusted_order_qty if rec.adjusted_order_qty is not None else rec.suggested_order_qty
                days_cover_oh = rec.days_of_cover_on_hand
                days_cover_pos = rec.days_of_cover_position
                reason_raw = str(rec.explanation_summary or "")
                stockout_risk_raw = rec.urgency if rec.urgency in ("CRITICAL", "HIGH") else ""
            elif fc is not None:
                rec_type = ""
                avg_daily_demand = round(float(fc.avg_daily_demand), 2) if fc.avg_daily_demand is not None else None
                dynamic_rop = None
                safety_stock = None
                lead_time_days = None
                suggested_qty = None
                if on_hand is not None and avg_daily_demand and avg_daily_demand > 0:
                    days_cover_oh = round(on_hand / avg_daily_demand, 1)
                    days_cover_pos = round((inv_position or 0) / avg_daily_demand, 1)
                else:
                    days_cover_oh = None
                    days_cover_pos = None
                urgency_raw = "HIGH" if (on_hand is not None and on_hand <= manual_rop) else "LOW"
                reason_raw = ""
                stockout_risk_raw = "CRITICAL" if (on_hand is not None and on_hand <= 0) else ""
            else:
                rec_type = ""
                urgency_raw = "LOW"
                dynamic_rop = None
                safety_stock = None
                avg_daily_demand = None
                lead_time_days = None
                suggested_qty = None
                days_cover_oh = None
                days_cover_pos = None
                reason_raw = ""
                stockout_risk_raw = "CRITICAL" if (on_hand is not None and on_hand <= 0) else ""

            # Check forecast staleness against newer sales
            latest_sale_dt = latest_sales.get(pid)
            is_forecast_stale = False
            if fc is not None and latest_sale_dt is not None and fc.data_cutoff_date is not None:
                if latest_sale_dt > (fc.data_cutoff_date + timedelta(days=1)):
                    is_forecast_stale = True
                    any_stale_forecast = True

            effective_rop: Optional[int] = (
                dynamic_rop if (dynamic_rop is not None and dynamic_rop > 0) else (manual_rop if manual_rop > 0 else None)
            )
            is_out_of_stock = physical_verified and on_hand is not None and on_hand <= 0
            is_below_rop = (
                physical_verified
                and inv_position is not None
                and effective_rop is not None
                and inv_position <= effective_rop
            )
            needs_reorder = bool(
                rec_type == "REORDER_NOW"
                or (suggested_qty is not None and suggested_qty > 0 and rec_type not in ("OVERSTOCK_ALERT", "DEMAND_DECREASING"))
            )
            is_low_stock = bool(
                is_out_of_stock
                or is_below_rop
                or needs_reorder
                or rec_type == "LOW_STOCK_RISK"
            )
            horizon_days = intent.forecast_horizon_days or 7
            predicted_horizon_demand: Optional[float] = (
                round(avg_daily_demand * horizon_days, 1) if avg_daily_demand is not None else None
            )
            # Runs out within horizon if physical cover OR position cover <= horizon (while having active demand)
            runs_out_within_horizon = bool(
                is_out_of_stock
                or (days_cover_pos is not None and days_cover_pos <= horizon_days)
                or (days_cover_oh is not None and days_cover_oh <= horizon_days and incoming == 0)
            )

            # Determine user-facing priority & status without exposing internal enum tokens
            if is_out_of_stock or urgency_raw == "CRITICAL" or stockout_risk_raw == "CRITICAL":
                eff_priority_raw = "CRITICAL"
            elif urgency_raw == "HIGH" or (is_below_rop and needs_reorder):
                eff_priority_raw = "HIGH"
            elif is_low_stock or urgency_raw == "MEDIUM":
                eff_priority_raw = "MEDIUM"
            else:
                eff_priority_raw = urgency_raw or "LOW"

            if not physical_verified and rec is not None:
                status_label = humanize_recommendation_type(rec_type)
            elif is_out_of_stock:
                status_label = "Out of stock"
            elif needs_reorder:
                status_label = "Reorder now"
            elif is_low_stock:
                status_label = "Running low"
            elif rec_type:
                status_label = humanize_recommendation_type(rec_type)
            elif physical_verified:
                status_label = "Healthy stock"
            else:
                status_label = "Not enough data available"

            open_pos = open_po_map.get(pid, [])
            merged_records.append(
                {
                    "_pid": pid,
                    "_priority_rank": _PRIORITY_ORDER.get(eff_priority_raw, 9),
                    "_is_out_of_stock": is_out_of_stock,
                    "_is_low_stock": is_low_stock,
                    "_needs_reorder": needs_reorder,
                    "_runs_out_in_horizon": runs_out_within_horizon,
                    "_is_critical": eff_priority_raw == "CRITICAL",
                    "product_id": pid,
                    "name": name,
                    "sku": sku,
                    "stock_available": available if physical_verified else None,
                    "on_hand_stock": on_hand if physical_verified else None,
                    "reserved_stock": reserved if reserved > 0 else 0,
                    "incoming_stock": incoming,
                    "inventory_position": inv_position if physical_verified else None,
                    "reorder_point": effective_rop,
                    "suggested_order_quantity": suggested_qty,
                    "estimated_days_of_cover": days_cover_oh,
                    "estimated_days_with_incoming": days_cover_pos,
                    "avg_daily_demand": avg_daily_demand,
                    "safety_stock": safety_stock,
                    "supplier_lead_time_days": lead_time_days,
                    "predicted_demand_in_horizon": predicted_horizon_demand,
                    "horizon_days": horizon_days if intent.primary_intent == "demand_forecast" else None,
                    "priority": humanize_priority(eff_priority_raw, short=True),
                    "status": status_label,
                    "physical_stock_verified": physical_verified,
                    "forecast_stale": is_forecast_stale,
                    "open_purchase_orders": open_pos if open_pos else None,
                    "unit_cost": round(unit_cost, 2),
                    "inventory_value": round((on_hand or 0) * unit_cost, 2) if physical_verified else None,
                    "reason": humanize_internal_text(reason_raw) if reason_raw else None,
                }
            )

        if any_stale_forecast:
            data_warnings.append(
                "Some demand forecasts are based on an earlier cutoff date than the latest recorded sales."
            )

        # 5. Filter & rank accurately according to query intent
        q_lower = (query or "").lower()
        code_tokens = set(intent.extracted_skus)
        matched_subset: List[Dict[str, Any]] = []

        if target_pids:
            target_set = set(target_pids)
            matched_subset = [r for r in merged_records if r["_pid"] in target_set]
        elif code_tokens:
            matched_subset = [r for r in merged_records if r["sku"].upper() in code_tokens]

        if not matched_subset and q_lower and intent.primary_intent in (
            "inventory_lookup",
            "product_availability",
            "purchase_recommendations",
            "general_inventory",
            "low_stock_products",
            "reorder_recommendations",
        ):
            # Match product names mentioned in the user query if no explicit SKU or follow-up ID matched
            _generic_words = {
                "what", "which", "where", "when", "why", "this", "that", "these", "those",
                "much", "many", "have", "stock", "inventory", "product", "products", "item",
                "items", "units", "order", "reorder", "running", "available", "availability",
                "today", "week", "next", "critical", "urgent", "only", "show", "give",
                "complete", "report", "explain", "about", "there", "currently", "remaining",
            }
            query_words = [
                w
                for w in re.findall(r"[A-Za-z0-9\u0900-\u097F]+", q_lower)
                if len(w) >= 4 and w not in _generic_words
            ]
            if query_words:
                name_hits = [
                    r for r in merged_records if any(w in r["name"].lower() or w in r["sku"].lower() for w in query_words)
                ]
                if name_hits:
                    matched_subset = name_hits

        if not matched_subset:
            if intent.primary_intent == "out_of_stock_products" or intent.flags.get("out_of_stock"):
                matched_subset = [r for r in merged_records if r["_is_out_of_stock"]]
            elif intent.primary_intent == "reorder_recommendations":
                matched_subset = [
                    r for r in merged_records if r["_needs_reorder"] or r["_is_out_of_stock"]
                ]
            elif intent.primary_intent == "demand_forecast" and intent.forecast_horizon_days:
                matched_subset = [r for r in merged_records if r["_runs_out_in_horizon"]]
            elif intent.primary_intent == "low_stock_products" or intent.flags.get("low_stock"):
                matched_subset = [r for r in merged_records if r["_is_low_stock"]]
            elif intent.primary_intent == "demand_forecast":
                matched_subset = [
                    r for r in merged_records
                    if r["avg_daily_demand"] is not None or r["_is_low_stock"]
                ]
            else:
                # General lookup fallback: surface low/urgent products first, or all active products
                low_first = [r for r in merged_records if r["_is_low_stock"]]
                matched_subset = low_first if low_first else list(merged_records)

        if intent.critical_only:
            crit = [r for r in matched_subset if r["_is_critical"]]
            strict_only = "only" in q_lower
            matched_subset = crit if (crit or strict_only) else matched_subset[:1]

        matched_subset.sort(
            key=lambda r: (
                r["_priority_rank"],
                r["estimated_days_of_cover"] if r["estimated_days_of_cover"] is not None else 9999.0,
                -(r["suggested_order_quantity"] or 0),
                r["product_id"],
            )
        )

        # Clean internal underscore helper keys before serialization
        total_matching = len(matched_subset)
        max_rows = 200 if intent.include_all else 15
        sliced = matched_subset[:max_rows]
        truncated = total_matching > len(sliced)

        compact_list_mode = len(sliced) > 3 and not intent.wants_explanation

        def _strip_internal_fields(item: Dict[str, Any]) -> Dict[str, Any]:
            cleaned: Dict[str, Any] = {}
            for k, v in item.items():
                if k.startswith("_") or k == "product_id":
                    continue
                if compact_list_mode and k in ("reason", "unit_cost", "inventory_value", "physical_stock_verified", "forecast_stale"):
                    continue
                if not intent.flags.get("valuation") and k in ("unit_cost", "inventory_value"):
                    continue
                if v is None and k not in (
                    "stock_available",
                    "reorder_point",
                    "suggested_order_quantity",
                    "estimated_days_of_cover",
                ):
                    continue
                cleaned[k] = v
            return cleaned

        out_products = [_strip_internal_fields(r) for r in sliced]
        focus_meta = [
            {
                "product_id": r["product_id"],
                "sku": r["sku"],
                "name": r["name"],
                "priority": r["priority"],
                "suggested_order_quantity": r["suggested_order_quantity"],
            }
            for r in sliced
        ]

        tool_name = (
            "get_low_stock_products"
            if intent.primary_intent in ("low_stock_products", "out_of_stock_products", "reorder_recommendations")
            else "get_inventory_status"
        )
        source_kind = "forecast_intelligence" if intent.primary_intent == "demand_forecast" else "business_tool"

        summary_title = f"Workspace inventory status ({total_matching} matching products)"
        payload: Dict[str, Any] = {
            "query_type": intent.primary_intent,
            "total_count": total_matching,
            "returned_count": len(out_products),
            "truncated": truncated,
            "out_of_stock_count": sum(1 for r in merged_records if r["_is_out_of_stock"]),
            "low_stock_count": sum(1 for r in merged_records if r["_is_low_stock"]),
            "needs_reorder_count": sum(1 for r in merged_records if r["_needs_reorder"]),
            "critical_count": sum(1 for r in matched_subset if r["_is_critical"]),
            "physical_stock_verified": live_inventory_available,
            "data_warnings": list(dict.fromkeys(data_warnings)),
            "products": out_products,
        }

        return (
            ToolEvidenceBlock(
                tool_name=tool_name,
                source_kind=source_kind,
                summary=summary_title,
                data=payload,
                include_in_user_citations=False,
            ),
            focus_meta,
        )

    @classmethod
    def get_stock_movements(
        cls,
        db: Session,
        ctx: BusinessContext,
        *,
        query: str,
        focus_product_ids: Sequence[int] = (),
        limit: int = 15,
    ) -> Optional[ToolEvidenceBlock]:
        if cls._is_supplier_workspace(ctx) or not cls._check_perm(ctx, "inventory.read"):
            return None

        log_q = (
            db.query(InventoryLog, Product)
            .join(Product, Product.id == InventoryLog.product_id)
            .filter(
                InventoryLog.business_id == ctx.business_id,
                Product.business_id == ctx.business_id,
            )
        )
        if focus_product_ids:
            log_q = log_q.filter(InventoryLog.product_id.in_(list(focus_product_ids)))
        else:
            code_tokens = [m.upper() for m in _SKU_OR_PO_RE.findall(query)]
            if code_tokens:
                log_q = log_q.filter(func.upper(Product.sku).in_(code_tokens))

        rows = (
            log_q.order_by(InventoryLog.timestamp.desc(), InventoryLog.id.desc())
            .limit(max(1, min(50, limit)))
            .all()
        )
        movements = [
            {
                "sku": prod.sku,
                "product_name": prod.name,
                "movement_type": humanize_movement_type(log.movement_type),
                "quantity_change": (log.stock_in or 0) - (log.stock_out or 0),
                "previous_stock": log.previous_stock,
                "closing_stock": log.closing_stock,
                "reason": log.reason,
                "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M") if log.timestamp else None,
            }
            for log, prod in rows
        ]
        return ToolEvidenceBlock(
            tool_name="get_stock_movements",
            source_kind="business_tool",
            summary=f"Recent stock movements ({len(movements)} entries)",
            data={
                "query_type": "stock_movement",
                "total_count": len(movements),
                "movements": movements,
            },
            include_in_user_citations=False,
        )

    @classmethod
    def get_inventory_valuation(
        cls,
        db: Session,
        ctx: BusinessContext,
        *,
        include_all: bool = False,
    ) -> Optional[ToolEvidenceBlock]:
        if cls._is_supplier_workspace(ctx) or not cls._check_perm(ctx, "inventory.read"):
            return None

        positions = InventoryService.get_inventory_positions(db, ctx.business_id)
        ranked = sorted(positions, key=lambda p: float(p.get("inventory_value") or 0.0), reverse=True)
        total_value = round(sum(float(p.get("inventory_value") or 0.0) for p in ranked), 2)
        total_units = sum(max(0, int(p.get("on_hand_stock") or 0)) for p in ranked)

        max_rows = 200 if include_all else 12
        items = [
            {
                "name": p["name"],
                "sku": p["sku"],
                "on_hand_stock": p["on_hand_stock"],
                "unit_cost": p["unit_cost"],
                "inventory_value": p["inventory_value"],
            }
            for p in ranked[:max_rows]
        ]
        return ToolEvidenceBlock(
            tool_name="get_inventory_valuation",
            source_kind="business_tool",
            summary=f"Inventory valuation across {len(ranked)} products",
            data={
                "query_type": "inventory_valuation",
                "total_skus": len(ranked),
                "total_units_on_hand": total_units,
                "total_inventory_value": total_value,
                "returned_count": len(items),
                "truncated": len(ranked) > len(items),
                "top_valued_products": items,
            },
            include_in_user_citations=False,
        )

    @classmethod
    def get_product_and_inventory_status(
        cls,
        db: Session,
        ctx: BusinessContext,
        *,
        query: str,
        page_context: Optional[Dict[str, Any]] = None,
        low_stock_only: bool = False,
    ) -> Optional[ToolEvidenceBlock]:
        """Backwards-compatible entry point returning reconciled live inventory."""
        from .intent_classifier import analyze_intent

        intent = analyze_intent(query, page_context)
        if low_stock_only:
            intent = IntentAnalysis(
                primary_intent="low_stock_products",
                flags={**intent.flags, "low_stock": True},
                answer_mode=intent.answer_mode,
                include_all=intent.include_all,
                critical_only=intent.critical_only,
                wants_count=intent.wants_count,
                wants_explanation=intent.wants_explanation,
                wants_report=intent.wants_report,
                forecast_horizon_days=intent.forecast_horizon_days,
                extracted_skus=intent.extracted_skus,
                extracted_po_numbers=intent.extracted_po_numbers,
                has_followup_reference=intent.has_followup_reference,
            )
        block, _ = cls.get_reconciled_inventory_intelligence(
            db, ctx, intent=intent, query=query, page_context=page_context
        )
        return block

    @classmethod
    def get_purchase_orders_and_suppliers(
        cls,
        db: Session,
        ctx: BusinessContext,
        *,
        query: str,
        page_context: Optional[Dict[str, Any]] = None,
    ) -> List[ToolEvidenceBlock]:
        if cls._is_supplier_workspace(ctx):
            sp = cls.get_supplier_portal_orders(db, ctx)
            return [sp] if sp else []

        blocks: List[ToolEvidenceBlock] = []
        if cls._check_perm(ctx, "po.read"):
            po_q = db.query(PurchaseOrder).filter(PurchaseOrder.business_id == ctx.business_id)
            if page_context and page_context.get("purchase_order_id") is not None:
                try:
                    po_q = po_q.filter(PurchaseOrder.id == int(page_context["purchase_order_id"]))
                except (TypeError, ValueError):
                    pass
            pos = po_q.order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc()).limit(20).all()
            supplier_ids = list({po.supplier_id for po in pos})
            sup_names: Dict[int, str] = {}
            if supplier_ids:
                sups = db.query(Supplier).filter(Supplier.id.in_(supplier_ids), Supplier.business_id == ctx.business_id).all()
                sup_names = {s.id: s.name for s in sups}
            q_lower = query.lower()
            focus_pending = any(w in q_lower for w in ("pending", "acknowledge", "sent", "draft", "open", "nahi", "lamba"))
            po_rows = []
            for po in pos:
                st_val = po.status.value if hasattr(po.status, "value") else str(po.status)
                if focus_pending and st_val in ("RECEIVED", "CANCELLED"):
                    continue
                po_rows.append(
                    {
                        "order_number": po.order_number,
                        "supplier_name": sup_names.get(po.supplier_id),
                        "status": humanize_po_status(st_val),
                        "supplier_status": humanize_po_status(getattr(po, "supplier_status", None))
                        if getattr(po, "supplier_status", None)
                        else None,
                        "total_amount": round(float(po.total_amount or 0.0), 2),
                        "order_date": po.order_date.strftime("%Y-%m-%d") if po.order_date else None,
                        "expected_delivery_date": po.expected_delivery_date.strftime("%Y-%m-%d")
                        if po.expected_delivery_date
                        else None,
                    }
                )
            blocks.append(
                ToolEvidenceBlock(
                    tool_name="get_purchase_order_status",
                    source_kind="business_tool",
                    summary=f"Purchase orders ({len(po_rows)} records)",
                    data={
                        "query_type": "purchase_orders",
                        "total_count": len(po_rows),
                        "orders": po_rows,
                    },
                    include_in_user_citations=False,
                )
            )

        if cls._check_perm(ctx, "suppliers.read"):
            sups = (
                db.query(Supplier)
                .filter(Supplier.business_id == ctx.business_id, Supplier.is_active.is_(True))
                .order_by(Supplier.name.asc())
                .limit(20)
                .all()
            )
            blocks.append(
                ToolEvidenceBlock(
                    tool_name="get_supplier_details",
                    source_kind="business_tool",
                    summary=f"Active suppliers ({len(sups)} suppliers)",
                    data={
                        "query_type": "suppliers",
                        "total_count": len(sups),
                        "suppliers": [
                            {
                                "name": s.name,
                                "lead_time_days": s.lead_time_days,
                                "portal_connected": s.linked_business_id is not None,
                            }
                            for s in sups
                        ],
                    },
                    include_in_user_citations=False,
                )
            )
        return blocks

    @classmethod
    def get_sales_summary(
        cls,
        db: Session,
        ctx: BusinessContext,
        *,
        days: int = 30,
        query: str = "",
        rank_by_profit: bool = False,
    ) -> Optional[ToolEvidenceBlock]:
        if cls._is_supplier_workspace(ctx) or not cls._check_perm(ctx, "sales.read"):
            return None
        start, end, period_label = _sales_window(query, days)
        metrics = _sales_totals(db, ctx, start, end)
        products = metrics.pop("products")
        rank_key = "estimated_gross_profit" if rank_by_profit else "revenue"
        slow_moving = any(word in query.lower() for word in ("poorly", "slow", "bottom", "least", "promote"))
        products.sort(key=lambda row: (
            row[rank_key] is None,
            (row[rank_key] or 0.0) if slow_moving else -(row[rank_key] or 0.0),
            row["name"].lower(),
        ))
        top_products = products[:15]
        summary = {
            "query_type": "sales_analysis",
            "period": period_label,
            "period_start": start.isoformat(),
            "period_end_exclusive": end.isoformat(),
            **metrics,
            "top_products": top_products,
            "products_returned": len(top_products),
            "products_truncated": len(products) > len(top_products),
            "net_profit_available": False,
            "financial_limitations": [
                "Gross profit is estimated using each product's current cost price; historical sale-time costs are not stored.",
                "Net profit cannot be calculated because operating expenses are not recorded.",
            ],
        }
        return ToolEvidenceBlock(
            tool_name="get_sales_summary",
            source_kind="business_tool",
            summary=(
                f"Lowest sales products ({period_label})"
                if slow_moving
                else f"Completed sales summary ({period_label})"
            ),
            data=summary,
            include_in_user_citations=False,
        )

    @classmethod
    def get_period_comparison(
        cls, db: Session, ctx: BusinessContext, *, query: str
    ) -> Optional[ToolEvidenceBlock]:
        if cls._is_supplier_workspace(ctx) or not cls._check_perm(ctx, "sales.read"):
            return None
        current_start, current_end, period_label = _sales_window(query)
        duration = current_end - current_start
        if period_label == "month to date":
            previous_start = (current_start - timedelta(days=1)).replace(day=1)
            previous_end = previous_start + duration
        elif period_label == "week to date":
            previous_start = current_start - timedelta(days=7)
            previous_end = previous_start + duration
        else:
            previous_start = current_start - duration
            previous_end = current_start
        current = _sales_totals(db, ctx, current_start, current_end)
        previous = _sales_totals(db, ctx, previous_start, previous_end)

        def percent_change(current_value: float, previous_value: float) -> Optional[float]:
            return round((current_value - previous_value) / previous_value * 100, 2) if previous_value else None

        return ToolEvidenceBlock(
            tool_name="compare_business_periods",
            source_kind="business_tool",
            summary=f"Sales and gross-profit comparison for {period_label}",
            data={
                "query_type": "period_comparison",
                "comparison_method": "equal-length comparable windows",
                "current_period": {
                    "start": current_start.isoformat(),
                    "end_exclusive": current_end.isoformat(),
                    **{k: current[k] for k in ("total_revenue", "total_units_sold", "transaction_count", "estimated_gross_profit")},
                },
                "previous_period": {
                    "start": previous_start.isoformat(),
                    "end_exclusive": previous_end.isoformat(),
                    **{k: previous[k] for k in ("total_revenue", "total_units_sold", "transaction_count", "estimated_gross_profit")},
                },
                "revenue_change_percent": percent_change(current["total_revenue"], previous["total_revenue"]),
                "units_change_percent": percent_change(current["total_units_sold"], previous["total_units_sold"]),
                "net_profit_available": False,
                "financial_limitations": [
                    "Gross profit uses current product cost prices, not historical costs at sale time.",
                    "Net profit is unavailable because operating expenses are not recorded.",
                ],
            },
            include_in_user_citations=False,
        )

    @classmethod
    def get_profitability_analysis(
        cls, db: Session, ctx: BusinessContext, *, query: str
    ) -> Optional[ToolEvidenceBlock]:
        sales = cls.get_sales_summary(
            db,
            ctx,
            query=query,
            rank_by_profit=any(word in query.lower() for word in ("product", "which", "margin")),
        )
        if sales is None:
            return None
        return ToolEvidenceBlock(
            tool_name="get_profitability_analysis",
            source_kind="business_tool",
            summary="Sales-based estimated gross profit and margin",
            data={
                **sales.data,
                "query_type": "profitability_analysis",
                "inventory_turnover_available": False,
                "inventory_turnover_limitation": (
                    "Turnover requires cost of goods sold and average inventory value over time; "
                    "historical inventory valuation snapshots are not available."
                ),
            },
            include_in_user_citations=False,
        )

    @classmethod
    def get_business_health_summary(
        cls, db: Session, ctx: BusinessContext
    ) -> Optional[ToolEvidenceBlock]:
        if cls._is_supplier_workspace(ctx):
            return None
        sections: Dict[str, Any] = {}
        if cls._check_perm(ctx, "sales.read"):
            sales = cls.get_sales_summary(db, ctx)
            if sales:
                sections["sales_last_30_days"] = sales.data
            comparison = cls.get_period_comparison(db, ctx, query="compare sales over the last 30 days")
            if comparison:
                sections["sales_period_comparison"] = comparison.data

        if cls._check_perm(ctx, "inventory.read"):
            positions = InventoryService.get_inventory_positions(db, ctx.business_id)
            sections["inventory"] = {
                "active_product_count": len(positions),
                "on_hand_units": sum(int(row["on_hand_stock"] or 0) for row in positions),
                "inventory_value_at_current_cost": round(
                    sum(float(row["inventory_value"] or 0.0) for row in positions), 2
                ),
                "at_or_below_manual_reorder_level_count": sum(
                    1 for row in positions
                    if int(row["on_hand_stock"] or 0) + int(row["incoming_stock"] or 0)
                    <= int(row["reorder_level"] or 0)
                ),
                "incoming_units": sum(int(row["incoming_stock"] or 0) for row in positions),
                "valuation_basis": "on-hand units multiplied by current product cost price",
            }
        if not sections:
            return None
        return ToolEvidenceBlock(
            tool_name="get_business_health_summary",
            source_kind="business_tool",
            summary="Authorized sales and inventory indicators for this workspace",
            data={
                "query_type": "business_health",
                "available_sections": sections,
                "unavailable_metrics": [
                    "Net profit and cash flow: operating expenses and cash transactions are not recorded.",
                    "Inventory turnover: historical average inventory valuation is not available.",
                ],
            },
            include_in_user_citations=False,
        )

    @classmethod
    def get_sales_forecast(
        cls, db: Session, ctx: BusinessContext, *, horizon_days: int
    ) -> Optional[ToolEvidenceBlock]:
        if (
            cls._is_supplier_workspace(ctx)
            or not cls._check_perm(ctx, "intelligence.read")
            or not cls._check_perm(ctx, "sales.read")
        ):
            return None
        forecasts = (
            db.query(ProductForecast, Product)
            .join(Product, Product.id == ProductForecast.product_id)
            .filter(
                ProductForecast.business_id == ctx.business_id,
                Product.business_id == ctx.business_id,
                Product.is_active.is_(True),
                ProductForecast.horizon_days == horizon_days,
            )
            .order_by(Product.id.asc())
            .all()
        )
        if not forecasts:
            return ToolEvidenceBlock(
                tool_name="get_sales_forecast",
                source_kind="forecast_intelligence",
                summary=f"No saved {horizon_days}-day demand forecasts are available",
                data={
                    "query_type": "revenue_forecast",
                    "horizon_days": horizon_days,
                    "available": False,
                    "reason": "No matching persisted demand forecasts were found; no forecast was fabricated.",
                },
                include_in_user_citations=False,
            )

        products: List[Dict[str, Any]] = []
        total_expected_demand = 0.0
        total_projected_revenue = 0.0
        revenue_complete = True
        for forecast, product in forecasts:
            demand = float(forecast.expected_total_demand or 0.0)
            price = float(product.selling_price or 0.0)
            total_expected_demand += demand
            projected_revenue = round(demand * price, 2) if price > 0 else None
            if projected_revenue is None:
                revenue_complete = False
            else:
                total_projected_revenue += projected_revenue
            products.append(
                {
                    "name": product.name,
                    "sku": product.sku,
                    "horizon_days": forecast.horizon_days,
                    "expected_demand_units": round(demand, 1),
                    "projected_revenue_at_current_price": projected_revenue,
                    "current_selling_price": round(price, 2) if price > 0 else None,
                    "model": forecast.champion_model,
                    "data_sufficiency": forecast.data_sufficiency,
                    "history_days_observed": forecast.history_days_observed,
                    "is_cold_start": forecast.is_cold_start,
                    "data_cutoff_date": forecast.data_cutoff_date.isoformat(),
                }
            )
        return ToolEvidenceBlock(
            tool_name="get_sales_forecast",
            source_kind="forecast_intelligence",
            summary=f"Saved product demand forecasts for the next {horizon_days} days",
            data={
                "query_type": "revenue_forecast",
                "horizon_days": horizon_days,
                "available": True,
                "products": products[:50],
                "product_count": len(products),
                "total_expected_demand_units": round(total_expected_demand, 1),
                "projected_revenue_at_current_prices": round(total_projected_revenue, 2) if revenue_complete else None,
                "revenue_projection_method": "forecast demand multiplied by current selling price; assumes prices and product mix remain unchanged",
                "uncertainty": "Forecast quality depends on each product's recorded data sufficiency, history length, and cutoff date.",
            },
            include_in_user_citations=False,
        )

    @classmethod
    def get_supplier_performance(
        cls, db: Session, ctx: BusinessContext
    ) -> Optional[ToolEvidenceBlock]:
        if (
            cls._is_supplier_workspace(ctx)
            or not cls._check_perm(ctx, "suppliers.read")
            or not cls._check_perm(ctx, "po.read")
        ):
            return None
        rows = (
            db.query(PurchaseOrder, Supplier)
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
            .filter(
                PurchaseOrder.business_id == ctx.business_id,
                Supplier.business_id == ctx.business_id,
                PurchaseOrder.status == PurchaseOrderStatus.RECEIVED,
            )
            .order_by(PurchaseOrder.order_date.desc())
            .limit(500)
            .all()
        )
        aggregate: Dict[int, Dict[str, Any]] = {}
        for po, supplier in rows:
            entry = aggregate.setdefault(
                supplier.id,
                {"supplier": supplier.name, "received_orders": 0, "delivered_on_time": 0, "measured_deliveries": 0, "delays": []},
            )
            entry["received_orders"] += 1
            if po.expected_delivery_date is not None and po.received_at is not None:
                delay = (po.received_at.date() - po.expected_delivery_date.date()).days
                entry["measured_deliveries"] += 1
                entry["delays"].append(delay)
                if delay <= 0:
                    entry["delivered_on_time"] += 1
        suppliers = []
        for row in aggregate.values():
            delays = row.pop("delays")
            row["average_delivery_delay_days"] = round(sum(delays) / len(delays), 1) if delays else None
            row["on_time_delivery_percent"] = (
                round(row["delivered_on_time"] / row["measured_deliveries"] * 100, 1)
                if row["measured_deliveries"]
                else None
            )
            suppliers.append(row)
        suppliers.sort(key=lambda row: (row["average_delivery_delay_days"] is None, -(row["average_delivery_delay_days"] or 0)))

        price_rows = (
            db.query(
                Product.id,
                Product.name,
                Supplier.name,
                func.avg(PurchaseOrderItem.unit_cost).label("average_unit_cost"),
                func.count(PurchaseOrderItem.id).label("received_line_count"),
            )
            .join(PurchaseOrderItem, PurchaseOrderItem.product_id == Product.id)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
            .filter(
                Product.business_id == ctx.business_id,
                PurchaseOrder.business_id == ctx.business_id,
                Supplier.business_id == ctx.business_id,
                PurchaseOrder.status == PurchaseOrderStatus.RECEIVED,
            )
            .group_by(Product.id, Product.name, Supplier.id, Supplier.name)
            .all()
        )
        prices_by_product: Dict[int, Dict[str, Any]] = {}
        for product_id, product_name, supplier_name, average_cost, line_count in price_rows:
            entry = prices_by_product.setdefault(
                int(product_id),
                {"product": product_name, "supplier_prices": []},
            )
            entry["supplier_prices"].append(
                {
                    "supplier": supplier_name,
                    "average_unit_cost": round(float(average_cost), 2),
                    "received_line_count": int(line_count),
                }
            )
        pricing_comparisons = []
        for entry in prices_by_product.values():
            if len(entry["supplier_prices"]) < 2:
                continue
            entry["supplier_prices"].sort(key=lambda item: item["average_unit_cost"])
            pricing_comparisons.append(entry)
        return ToolEvidenceBlock(
            tool_name="get_supplier_performance",
            source_kind="business_tool",
            summary=f"Supplier delivery performance from {len(rows)} received purchase orders",
            data={
                "query_type": "supplier_performance",
                "received_order_count": len(rows),
                "suppliers": suppliers,
                "pricing_comparisons": pricing_comparisons,
                "pricing_comparison_available": bool(pricing_comparisons),
                "limitations": [
                    "Only received purchase orders with both expected and actual delivery dates are used for punctuality.",
                    "Supplier prices are compared only for products purchased from at least two suppliers.",
                ],
            },
            include_in_user_citations=False,
        )

    @classmethod
    def get_forecast_and_alerts(
        cls,
        db: Session,
        ctx: BusinessContext,
        *,
        query: str,
        page_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ToolEvidenceBlock]:
        """Backwards-compatible forecast wrapper backed by reconciled data without internal phase labels."""
        from .intent_classifier import analyze_intent

        intent = analyze_intent(query, page_context)
        if intent.primary_intent == "general_inventory":
            intent = IntentAnalysis(
                primary_intent="demand_forecast",
                flags={**intent.flags, "forecast": True},
                answer_mode=intent.answer_mode,
                include_all=intent.include_all,
                critical_only=intent.critical_only,
                wants_count=intent.wants_count,
                wants_explanation=intent.wants_explanation,
                wants_report=intent.wants_report,
                forecast_horizon_days=intent.forecast_horizon_days,
                extracted_skus=intent.extracted_skus,
                extracted_po_numbers=intent.extracted_po_numbers,
                has_followup_reference=intent.has_followup_reference,
            )
        block, _ = cls.get_reconciled_inventory_intelligence(
            db, ctx, intent=intent, query=query, page_context=page_context
        )
        return block

    @classmethod
    def prepare_draft_po_proposal(
        cls,
        db: Session,
        ctx: BusinessContext,
        *,
        query: str,
        page_context: Optional[Dict[str, Any]] = None,
        focus_product_ids: Sequence[int] = (),
    ) -> Optional[Dict[str, Any]]:
        """Build confirmation-gated draft PO proposal without executing any write."""
        if cls._is_supplier_workspace(ctx):
            raise AIInvalidRequestError(
                "Supplier workspaces cannot create buyer purchase orders.",
                provider="assistant",
            )
        if not cls._check_perm(ctx, "po.write"):
            raise AIInvalidRequestError(
                "Insufficient permissions ('po.write' required) to prepare a purchase order.",
                provider="assistant",
            )

        products = (
            db.query(Product)
            .filter(Product.business_id == ctx.business_id, Product.is_active.is_(True))
            .order_by(Product.id.asc())
            .all()
        )
        if not products:
            return None

        target_prod: Optional[Product] = None
        if page_context and page_context.get("product_id") is not None:
            try:
                pid = int(page_context["product_id"])
                target_prod = next((p for p in products if p.id == pid), None)
            except (TypeError, ValueError):
                target_prod = None

        if target_prod is None:
            code_tokens = [m.upper() for m in _SKU_OR_PO_RE.findall(query)]
            for tok in code_tokens:
                target_prod = next((p for p in products if p.sku.upper() == tok), None)
                if target_prod:
                    break
        if target_prod is None and focus_product_ids:
            target_prod = next((p for p in products if p.id == int(focus_product_ids[0])), None)
        if target_prod is None:
            q_lower = query.lower()
            target_prod = next(
                (p for p in products if p.name.lower() in q_lower or any(w in p.name.lower() for w in q_lower.split() if len(w) >= 4)),
                None,
            )
        if target_prod is None:
            low_prods = [p for p in products if p.current_stock <= p.reorder_level]
            target_prod = low_prods[0] if low_prods else products[0]

        supplier: Optional[Supplier] = None
        if target_prod.supplier_id:
            supplier = (
                db.query(Supplier)
                .filter(
                    Supplier.id == target_prod.supplier_id,
                    Supplier.business_id == ctx.business_id,
                    Supplier.is_active.is_(True),
                )
                .first()
            )
        if supplier is None:
            supplier = (
                db.query(Supplier)
                .filter(Supplier.business_id == ctx.business_id, Supplier.is_active.is_(True))
                .order_by(Supplier.id.asc())
                .first()
            )
        if supplier is None:
            return None

        qty_match = re.search(r"\b(\d{1,5})\s*(?:units?|pcs?|pieces?|qty|quantity|इकाई)?\b", query, re.IGNORECASE)
        if qty_match and int(qty_match.group(1)) > 0:
            qty = int(qty_match.group(1))
        else:
            rec_row = (
                db.query(ReplenishmentRecommendation)
                .filter(
                    ReplenishmentRecommendation.business_id == ctx.business_id,
                    ReplenishmentRecommendation.product_id == target_prod.id,
                    ReplenishmentRecommendation.status.in_(list(OPEN_STATUSES)),
                )
                .order_by(ReplenishmentRecommendation.updated_at.desc())
                .first()
            )
            if rec_row and rec_row.suggested_order_qty and rec_row.suggested_order_qty > 0:
                qty = int(rec_row.adjusted_order_qty or rec_row.suggested_order_qty)
            else:
                qty = max(
                    1,
                    target_prod.min_order_quantity or 1,
                    max(10, (target_prod.reorder_level or 10) * 2 - target_prod.current_stock),
                )

        unit_cost = round(float(target_prod.cost_price or 10.0), 2)

        return {
            "action_type": "CREATE_DRAFT_PO",
            "status": "PENDING_CONFIRMATION",
            "summary": f"Create Draft PO for {qty} x {target_prod.name} ({target_prod.sku}) from {supplier.name}",
            "requires_permission": "po.write",
            "payload": {
                "supplier_id": supplier.id,
                "supplier_name": supplier.name,
                "product_id": target_prod.id,
                "sku": target_prod.sku,
                "product_name": target_prod.name,
                "ordered_quantity": qty,
                "unit_cost": unit_cost,
                "estimated_total": round(qty * unit_cost, 2),
                "notes": "Prepared via StockSangati AI Assistant (user confirmed).",
            },
        }

    @classmethod
    def execute_confirmed_draft_po(
        cls,
        db: Session,
        ctx: BusinessContext,
        *,
        action_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if cls._is_supplier_workspace(ctx):
            raise AIInvalidRequestError(
                "Supplier workspaces cannot execute buyer purchase orders.",
                provider="assistant",
            )
        if not cls._check_perm(ctx, "po.write"):
            raise AIInvalidRequestError(
                "Insufficient permissions ('po.write' required) to create a purchase order.",
                provider="assistant",
            )
        po = ProcurementService.create_purchase_order(
            db=db,
            business_id=ctx.business_id,
            user_id=ctx.user.id,
            payload=PurchaseOrderCreate(
                supplier_id=int(action_payload["supplier_id"]),
                notes=str(action_payload.get("notes") or "Confirmed via StockSangati AI Assistant"),
                items=[
                    PurchaseOrderItemCreate(
                        product_id=int(action_payload["product_id"]),
                        ordered_quantity=int(action_payload["ordered_quantity"]),
                        unit_cost=float(action_payload["unit_cost"]),
                    )
                ],
            ),
        )
        return {
            "purchase_order_id": po.id,
            "order_number": po.order_number,
            "status": po.status.value if hasattr(po.status, "value") else str(po.status),
            "total_amount": float(po.total_amount or 0.0),
        }
