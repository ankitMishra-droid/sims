from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import case, func

from .. import models
from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles, require_business_types

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(require_business_types(["retailer", "wholesaler"]))],
)

READ_ROLES = ["admin", "manager", "analyst", "staff"]


def _utc_bounds():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today_start, now - timedelta(days=7), now - timedelta(days=30)


def _active_sale_expr():
    return func.upper(func.coalesce(models.Sale.status, "COMPLETED")) != "CANCELLED"


@router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    bid = ctx.business_id
    prod_agg = (
        db.query(
            func.count(models.Product.id).label("total_products"),
            func.coalesce(func.sum(models.Product.current_stock), 0).label("total_stock"),
            func.sum(
                case((models.Product.current_stock <= models.Product.reorder_level, 1), else_=0)
            ).label("low_stock_count"),
            func.coalesce(
                func.sum(models.Product.current_stock * models.Product.cost_price), 0
            ).label("total_inventory_value"),
        )
        .filter(
            models.Product.business_id == bid,
            models.Product.is_active.is_(True),
        )
        .one()
    )

    sale_agg = (
        db.query(
            func.count(models.Sale.id).label("total_sales"),
            func.coalesce(func.sum(models.Sale.revenue), 0).label("total_revenue"),
        )
        .filter(
            models.Sale.business_id == bid,
            _active_sale_expr(),
        )
        .one()
    )

    return {
        "total_products": int(prod_agg.total_products or 0),
        "total_stock_units": int(prod_agg.total_stock or 0),
        "low_stock_products": int(prod_agg.low_stock_count or 0),
        "total_sales": int(sale_agg.total_sales or 0),
        "total_revenue": round(float(sale_agg.total_revenue or 0), 2),
        "total_inventory_value": round(float(prod_agg.total_inventory_value or 0), 2),
    }


@router.get("/purchase-order-metrics")
def purchase_order_metrics(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    bid = ctx.business_id
    open_statuses = (
        models.PurchaseOrderStatus.DRAFT,
        models.PurchaseOrderStatus.SENT,
        models.PurchaseOrderStatus.PARTIALLY_RECEIVED,
    )
    transit_statuses = (
        models.PurchaseOrderStatus.SENT,
        models.PurchaseOrderStatus.PARTIALLY_RECEIVED,
    )

    po_agg = (
        db.query(
            func.count(models.PurchaseOrder.id).label("total_po"),
            func.sum(
                case((models.PurchaseOrder.status.in_(open_statuses), 1), else_=0)
            ).label("pending_po"),
            func.sum(
                case((models.PurchaseOrder.status.in_(transit_statuses), 1), else_=0)
            ).label("incomplete_deliveries"),
        )
        .filter(models.PurchaseOrder.business_id == bid)
        .one()
    )

    expected_stock = (
        db.query(
            func.coalesce(
                func.sum(models.PurchaseOrderItem.ordered_quantity - models.PurchaseOrderItem.received_quantity),
                0,
            )
        )
        .join(
            models.PurchaseOrder,
            models.PurchaseOrder.id == models.PurchaseOrderItem.purchase_order_id,
        )
        .filter(
            models.PurchaseOrder.business_id == bid,
            models.PurchaseOrder.status.in_(transit_statuses),
        )
        .scalar()
    )

    return {
        "total_purchase_orders": int(po_agg.total_po or 0),
        "pending_purchase_orders": int(po_agg.pending_po or 0),
        "incomplete_deliveries": int(po_agg.incomplete_deliveries or 0),
        "expected_stock": int(expected_stock or 0),
    }


@router.get("/inventory-movement-metrics")
def inventory_movement_metrics(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    bid = ctx.business_id
    today_start, _, _ = _utc_bounds()

    mov_agg = (
        db.query(
            func.coalesce(func.sum(models.InventoryLog.stock_in), 0).label("stock_in_today"),
            func.coalesce(func.sum(models.InventoryLog.stock_out), 0).label("stock_out_today"),
            func.count(models.InventoryLog.id).label("tx_count"),
        )
        .filter(
            models.InventoryLog.business_id == bid,
            models.InventoryLog.timestamp >= today_start,
        )
        .one()
    )

    stock_in_val = int(mov_agg.stock_in_today or 0)
    stock_out_val = int(mov_agg.stock_out_today or 0)
    return {
        "stock_in_today": stock_in_val,
        "stock_out_today": stock_out_val,
        "net_stock_movement_today": stock_in_val - stock_out_val,
        "inventory_transaction_count_today": int(mov_agg.tx_count or 0),
    }


@router.get("/sales-metrics")
def sales_metrics(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    bid = ctx.business_id
    today_start, week_start, month_start = _utc_bounds()

    sales_agg = (
        db.query(
            func.sum(case((models.Sale.sales_date >= today_start, 1), else_=0)).label("today_cnt"),
            func.sum(case((models.Sale.sales_date >= today_start, models.Sale.revenue), else_=0)).label("today_rev"),
            func.sum(case((models.Sale.sales_date >= week_start, 1), else_=0)).label("week_cnt"),
            func.sum(case((models.Sale.sales_date >= week_start, models.Sale.revenue), else_=0)).label("week_rev"),
            func.count(models.Sale.id).label("month_cnt"),
            func.coalesce(func.sum(models.Sale.revenue), 0).label("month_rev"),
        )
        .filter(
            models.Sale.business_id == bid,
            _active_sale_expr(),
            models.Sale.sales_date >= month_start,
        )
        .one()
    )

    return {
        "sales_count_today": int(sales_agg.today_cnt or 0),
        "sales_count_this_week": int(sales_agg.week_cnt or 0),
        "sales_count_this_month": int(sales_agg.month_cnt or 0),
        "todays_revenue": round(float(sales_agg.today_rev or 0), 2),
        "this_weeks_revenue": round(float(sales_agg.week_rev or 0), 2),
        "this_months_revenue": round(float(sales_agg.month_rev or 0), 2),
    }


@router.get("/supplier-metrics")
def supplier_metrics(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    bid = ctx.business_id
    sup_agg = (
        db.query(
            func.count(models.Supplier.id).label("total_suppliers"),
            func.sum(case((models.Supplier.is_active.is_(True), 1), else_=0)).label("active_suppliers"),
        )
        .filter(models.Supplier.business_id == bid)
        .one()
    )
    total_suppliers = int(sup_agg.total_suppliers or 0)
    active_suppliers = int(sup_agg.active_suppliers or 0)
    inactive_suppliers = total_suppliers - active_suppliers

    suppliers_with_pending_pos = db.query(models.PurchaseOrder.supplier_id).filter(
        models.PurchaseOrder.business_id == bid,
        models.PurchaseOrder.status.in_([
            models.PurchaseOrderStatus.DRAFT,
            models.PurchaseOrderStatus.SENT,
            models.PurchaseOrderStatus.PARTIALLY_RECEIVED,
        ]),
    ).distinct().count()

    return {
        "total_suppliers": total_suppliers,
        "active_suppliers": active_suppliers,
        "inactive_suppliers": inactive_suppliers,
        "suppliers_with_pending_pos": suppliers_with_pending_pos,
    }
