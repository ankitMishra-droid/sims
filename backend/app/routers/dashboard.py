from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from .. import models
from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

READ_ROLES = ["admin", "manager", "analyst", "staff"]


def _utc_bounds():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today_start, now - timedelta(days=7), now - timedelta(days=30)


@router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    bid = ctx.business_id
    total_products = db.query(models.Product).filter(
        models.Product.business_id == bid,
        models.Product.is_active.is_(True),
    ).count()

    total_stock = db.query(func.coalesce(func.sum(models.Product.current_stock), 0)).filter(
        models.Product.business_id == bid,
        models.Product.is_active.is_(True),
    ).scalar()

    low_stock_count = db.query(models.Product).filter(
        models.Product.business_id == bid,
        models.Product.is_active.is_(True),
        models.Product.current_stock <= models.Product.reorder_level,
    ).count()

    total_sales = db.query(models.Sale).filter(
        models.Sale.business_id == bid,
        models.Sale.status != "CANCELLED",
    ).count()

    total_revenue = db.query(func.coalesce(func.sum(models.Sale.revenue), 0)).filter(
        models.Sale.business_id == bid,
        models.Sale.status != "CANCELLED",
    ).scalar()

    total_inventory_value = db.query(
        func.coalesce(func.sum(models.Product.current_stock * models.Product.cost_price), 0)
    ).filter(
        models.Product.business_id == bid,
        models.Product.is_active.is_(True),
    ).scalar()

    return {
        "total_products": total_products,
        "total_stock_units": int(total_stock or 0),
        "low_stock_products": low_stock_count,
        "total_sales": total_sales,
        "total_revenue": round(float(total_revenue or 0), 2),
        "total_inventory_value": round(float(total_inventory_value or 0), 2),
    }


@router.get("/purchase-order-metrics")
def purchase_order_metrics(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    bid = ctx.business_id
    total_purchase_order = db.query(models.PurchaseOrder).filter(
        models.PurchaseOrder.business_id == bid
    ).count()

    pending_purchase_order = db.query(models.PurchaseOrder).filter(
        models.PurchaseOrder.business_id == bid,
        models.PurchaseOrder.status.in_([
            models.PurchaseOrderStatus.DRAFT,
            models.PurchaseOrderStatus.SENT,
            models.PurchaseOrderStatus.PARTIALLY_RECEIVED,
        ]),
    ).count()

    incomplete_deliveries = db.query(models.PurchaseOrder).filter(
        models.PurchaseOrder.business_id == bid,
        models.PurchaseOrder.status.in_([
            models.PurchaseOrderStatus.SENT,
            models.PurchaseOrderStatus.PARTIALLY_RECEIVED,
        ]),
    ).count()

    expected_stock = db.query(
        func.coalesce(
            func.sum(models.PurchaseOrderItem.ordered_quantity - models.PurchaseOrderItem.received_quantity),
            0,
        )
    ).join(
        models.PurchaseOrder,
        models.PurchaseOrder.id == models.PurchaseOrderItem.purchase_order_id,
    ).filter(
        models.PurchaseOrder.business_id == bid,
        models.PurchaseOrder.status.in_([
            models.PurchaseOrderStatus.SENT,
            models.PurchaseOrderStatus.PARTIALLY_RECEIVED,
        ]),
    ).scalar()

    return {
        "total_purchase_orders": total_purchase_order,
        "pending_purchase_orders": pending_purchase_order,
        "incomplete_deliveries": incomplete_deliveries,
        "expected_stock": int(expected_stock or 0),
    }


@router.get("/inventory-movement-metrics")
def inventory_movement_metrics(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    bid = ctx.business_id
    today_start, _, _ = _utc_bounds()

    stock_in_today = db.query(
        func.coalesce(func.sum(models.InventoryLog.stock_in), 0)
    ).filter(
        models.InventoryLog.business_id == bid,
        models.InventoryLog.timestamp >= today_start,
    ).scalar()

    stock_out_today = db.query(
        func.coalesce(func.sum(models.InventoryLog.stock_out), 0)
    ).filter(
        models.InventoryLog.business_id == bid,
        models.InventoryLog.timestamp >= today_start,
    ).scalar()

    net_stock_movement_today = int(stock_in_today or 0) - int(stock_out_today or 0)

    inventory_transaction_count_today = db.query(models.InventoryLog).filter(
        models.InventoryLog.business_id == bid,
        models.InventoryLog.timestamp >= today_start,
    ).count()

    return {
        "stock_in_today": int(stock_in_today or 0),
        "stock_out_today": int(stock_out_today or 0),
        "net_stock_movement_today": net_stock_movement_today,
        "inventory_transaction_count_today": inventory_transaction_count_today,
    }


@router.get("/sales-metrics")
def sales_metrics(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    bid = ctx.business_id
    today_start, week_start, month_start = _utc_bounds()

    base_q = db.query(models.Sale).filter(
        models.Sale.business_id == bid,
        models.Sale.status != "CANCELLED",
    )

    sales_count_today = base_q.filter(models.Sale.sales_date >= today_start).count()
    todays_revenue = db.query(func.coalesce(func.sum(models.Sale.revenue), 0)).filter(
        models.Sale.business_id == bid,
        models.Sale.status != "CANCELLED",
        models.Sale.sales_date >= today_start,
    ).scalar()

    sales_count_this_week = base_q.filter(models.Sale.sales_date >= week_start).count()
    this_weeks_revenue = db.query(func.coalesce(func.sum(models.Sale.revenue), 0)).filter(
        models.Sale.business_id == bid,
        models.Sale.status != "CANCELLED",
        models.Sale.sales_date >= week_start,
    ).scalar()

    sales_count_this_month = base_q.filter(models.Sale.sales_date >= month_start).count()
    this_months_revenue = db.query(func.coalesce(func.sum(models.Sale.revenue), 0)).filter(
        models.Sale.business_id == bid,
        models.Sale.status != "CANCELLED",
        models.Sale.sales_date >= month_start,
    ).scalar()

    return {
        "sales_count_today": sales_count_today,
        "sales_count_this_week": sales_count_this_week,
        "sales_count_this_month": sales_count_this_month,
        "todays_revenue": round(float(todays_revenue or 0), 2),
        "this_weeks_revenue": round(float(this_weeks_revenue or 0), 2),
        "this_months_revenue": round(float(this_months_revenue or 0), 2),
    }


@router.get("/supplier-metrics")
def supplier_metrics(
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_business_roles(READ_ROLES)),
):
    bid = ctx.business_id
    total_suppliers = db.query(models.Supplier).filter(models.Supplier.business_id == bid).count()
    active_suppliers = db.query(models.Supplier).filter(
        models.Supplier.business_id == bid,
        models.Supplier.is_active.is_(True),
    ).count()
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
