from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from .. import models

router = APIRouter(prefix="/api/sales", tags=['Sales'])

# Sales Creation
@router.post("/", response_model=schemas.SaleResponse)
def create_sale(sale: schemas.SaleCreate, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == sale.product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="product not found")

    if sale.quantity_sold <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")

    if sale.quantity_sold > product.current_stock:
        raise HTTPException(status_code=400, detail="Insufficient stock")

    price = sale.selling_price if sale.selling_price is not None else product.selling_price

    revenue = price * sale.quantity_sold

    db_sale = models.Sale(
        product_id = product.id,
        quantity_sold = sale.quantity_sold,
        selling_price = price,
        revenue = revenue
    )

    product.current_stock -= sale.quantity_sold

    db.add(db_sale)

    db.add(models.InventoryLog(
        product_id = product.id,
        stock_out = sale.quantity_sold,
        closing_stock = product.current_stock,
        reason = "sale"
    ))

    db.commit()
    db.refresh(db_sale)

    return {
        "data": db_sale,
        "message": "product sold"
    }

# Fetch all sales data
@router.get("/", response_model=schemas.SaleListResponse)
def get_sales(db: Session = Depends(get_db)):
    sale = db.query(models.Sale).order_by(models.Sale.sales_date.desc()).all()

    if not sale:
        raise HTTPException(status_code=404, detail="sale product not found")

    return {
        "data": sale,
        "message": "all product sales data fetched"
    }

# fetch specific sale product
@router.get("/product/{product_id}", response_model=schemas.SaleResponse)
def get_sale_by_product(product_id: int, db: Session = Depends(get_db)):
    sale = db.query(models.Sale).filter(models.Sale.product_id == product_id).order_by(models.Sale.sales_date.desc()).first()

    if not sale:
        raise HTTPException(status_code=404, detail="sale product not found")

    return {
        "data": sale,
        "message": f"sale product fetched"
    }

# fetch sales data for a specific date
@router.get("/date/{date}", response_model=schemas.SaleListResponse)
def get_sales_by_date(date: str, db: Session = Depends(get_db)):
    sale = db.query(models.Sale).filter(models.Sale.sales_date == date).all()

    if not sale:
        raise HTTPException(status_code=404, detail="sale product not found")

    return {
        "data": sale,
        "message": f"sale product fetched"
    }

# fetch sales data for a specific date range
@router.get("/date-range/", response_model=schemas.SaleListResponse)
def get_sales_by_date_range(start_date: str, end_date: str, db: Session = Depends(get_db)):
    sale = db.query(models.Sale).filter(models.Sale.sales_date >= start_date, models.Sale.sales_date <= end_date).all()

    if not sale:
        raise HTTPException(status_code=404, detail="sale product not found")

    return {
        "data": sale,
        "message": f"sale product fetched"
    }

# fetch sales data for a specific product and date range
@router.get("/product-date-range/", response_model=schemas.SaleListResponse)
def get_sales_by_product_and_date_range(product_id: int, start_date: str, end_date: str, db: Session = Depends(get_db)):
    sale = db.query(models.Sale).filter(models.Sale.product_id == product_id, models.Sale.sales_date >= start_date, models.Sale.sales_date <= end_date).all()

    if not sale:
        raise HTTPException(status_code=404, detail="sale product not found")

    return {
        "data": sale,
        "message": f"sale product fetched"
    }
