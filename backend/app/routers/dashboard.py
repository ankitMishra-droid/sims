from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from .. import models
from ..database import get_db

router = APIRouter(prefix="/dashboard", tags=['Dashboard'])

@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    total_products = db.query(models.Product).count()

    total_stock = db.query(func.coalesce(func.sum(models.Product.current_stock), 0)).scalar()

    low_stock_count = db.query(models.Product).filter(models.Product.current_stock <= models.Product.reorder_level).count()

    total_sales = db.query(models.Sale).count()

    total_revenue = db.query(func.coalesce(func.sum(models.Sale.revenue), 0)).scalar()

    total_inventory_value = db.query(func.coalesce(func.sum(models.Product.current_stock * models.Product.cost_price), 0)).scalar()

    out_of_stock_products = db.query(models.Product).filter(models.Product.current_stock == 0).count()

    return {
        "total_products": total_products,
        "total_stock_units": total_stock,
        "low_stock_products": low_stock_count,
        "total_sales": total_sales,
        "total_revenue": round(float(total_revenue), 2),
        "total_inventory_value": round(float(total_inventory_value), 2)
    }

# Purchase-order metrics
@router.get("/purchase-order-metrics")
def purchase_order_metrics(db: Session = Depends(get_db)):
    total_purchase_order = db.query(models.PurchaseOrder).count()
    # IN DRAFT, SENT, PARTIALLY_RECEIVED Orders that aren't completely received
    pending_purchase_order = db.query(models.PurchaseOrder).filter(
        models.PurchaseOrder.status.in_([models.PurchaseOrderStatus.DRAFT, models.PurchaseOrderStatus.SENT, models.PurchaseOrderStatus.PARTIALLY_RECEIVED])
    ).count()

    # Shows incomplete deliveries
    incomplete_deliveries = db.query(models.PurchaseOrder).filter(
        models.PurchaseOrder.status.in_([models.PurchaseOrderStatus.SENT, models.PurchaseOrderStatus.PARTIALLY_RECEIVED])
    ).count()

    # for active purchase orders, How much stock is still expected
    expected_stock = db.query(func.coalesce(func.sum(models.PurchaseOrderItem.ordered_quantity - models.PurchaseOrderItem.received_quantity), 0)).join(
        models.PurchaseOrder, models.PurchaseOrder.id == models.PurchaseOrderItem.purchase_order_id
    ).filter(
        models.PurchaseOrder.status.in_([models.PurchaseOrderStatus.SENT, models.PurchaseOrderStatus.PARTIALLY_RECEIVED])
    ).scalar()

    return {
        "total_purchase_orders": total_purchase_order,
        "pending_purchase_orders": pending_purchase_order,
        "incomplete_deliveries": incomplete_deliveries,
        "expected_stock": expected_stock
    }

# Inventory movement metrics
@router.get("/inventory-movement-metrics")
def inventory_movement_metrics(db: Session = Depends(get_db)):

    # Stock In Today
    stock_in_today = db.query(
        func.coalesce(func.sum(models.InventoryLog.stock_in), 0)
    ).filter(
        func.date(models.InventoryLog.timestamp) == func.current_date()
    ).scalar()

    # Stock Out Today
    stock_out_today = db.query(
        func.coalesce(func.sum(models.InventoryLog.stock_out), 0)
    ).filter(
        func.date(models.InventoryLog.timestamp) == func.current_date()
    ).scalar()

    # Net Stock Movement Today
    net_stock_movement_today = stock_in_today - stock_out_today

    # Number of inventory transactions today
    inventory_transaction_count_today = db.query(
        models.InventoryLog
    ).filter(
        func.date(models.InventoryLog.timestamp) == func.current_date()
    ).count()

    return {
        "stock_in_today": stock_in_today,
        "stock_out_today": stock_out_today,
        "net_stock_movement_today": net_stock_movement_today,
        "inventory_transaction_count_today": inventory_transaction_count_today
    }

# Sales metrics - add a few time-based metrics.
@router.get("/sales-metrics")
def sales_metrics(db: Session = Depends(get_db)):
    # Total sales today
    sales_count_today = db.query(
        func.count(models.Sale.id)
    ).filter(
        func.date(models.Sale.sales_date) == func.date("now")
    ).scalar()

    # Today's Revenue
    todays_revenue = db.query(
        func.coalesce(func.sum(models.Sale.revenue), 0)
    ).filter(
        func.date(models.Sale.sales_date) == func.date("now")
    ).scalar()


    # Total sales this week
    sales_count_this_week = db.query(
        func.count(models.Sale.id)
    ).filter(
        func.date(models.Sale.sales_date) >= func.date("now", "-7 days")
    ).scalar()

    # This week's Revenue
    this_weeks_revenue = db.query(func.coalesce(func.sum(models.Sale.revenue), 0)).filter(
        func.date(models.Sale.sales_date) >= func.date("now", "-7 days")
    ).scalar()

    # Total sales this month
    sales_count_this_month = db.query(
        func.count(models.Sale.id)
    ).filter(
        func.date(models.Sale.sales_date) >= func.date("now", "-30 days")
    ).scalar()

    # This month's Revenue
    this_months_revenue = db.query(func.coalesce(func.sum(models.Sale.revenue), 0)).filter(
        func.date(models.Sale.sales_date) >= func.date("now", "-30 days")
    ).scalar()

    return {
        "sales_count_today": sales_count_today,
        "sales_count_this_week": sales_count_this_week,
        "sales_count_this_month": sales_count_this_month,
        "todays_revenue": round(float(todays_revenue), 2),
        "this_weeks_revenue": round(float(this_weeks_revenue), 2),
        "this_months_revenue": round(float(this_months_revenue), 2)
    }

# Supplier metrics
@router.get("/supplier-metrics")
def supplier_metrics(db: Session = Depends(get_db)):
    # Total Suppliers
    total_suppliers = db.query(models.Supplier).count()

    # Active Suppliers
    active_suppliers = db.query(models.Supplier).filter(models.Supplier.is_active == True).count()

    # Inactive Suppliers
    inactive_suppliers = db.query(models.Supplier).filter(models.Supplier.is_active == False).count()

    # Suppliers with Pending POs - COUNT(DISTINCT supplier_id)
    suppliers_with_pending_pos = db.query(models.PurchaseOrder.supplier_id).filter(
        models.PurchaseOrder.status.in_([models.PurchaseOrderStatus.DRAFT, models.PurchaseOrderStatus.SENT, models.PurchaseOrderStatus.PARTIALLY_RECEIVED])
    ).distinct().count()

    return {
        "total_suppliers": total_suppliers,
        "active_suppliers": active_suppliers,
        "inactive_suppliers": inactive_suppliers,
        "suppliers_with_pending_pos": suppliers_with_pending_pos
    }