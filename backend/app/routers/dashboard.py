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