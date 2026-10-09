from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from .. import schemas

router = APIRouter(
    prefix="/api/inventory",
    tags=["Inventory"]
)


# Add Stock
@router.post("/stock-in")
def add_stock(
    stock: schemas.StockInCreate,
    db: Session = Depends(get_db)
):
    product = (
        db.query(models.Product)
        .filter(models.Product.id == stock.product_id)
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    if stock.quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be greater than 0"
        )

    # Update stock
    product.current_stock += stock.quantity

    # Create inventory log
    log = models.InventoryLog(
        product_id=product.id,
        stock_in=stock.quantity,
        stock_out=0,
        closing_stock=product.current_stock,
        reason=stock.reason
    )

    db.add(log)

    db.commit()
    db.refresh(log)

    return {
        "message": "Stock added successfully",
        "product_id": product.id,
        "added_quantity": stock.quantity,
        "current_stock": product.current_stock
    }


# Get Inventory History
@router.get(
    "/logs/{product_id}",
    response_model=list[schemas.InventoryLogOut]
)
def get_inventory_logs(
    product_id: int,
    db: Session = Depends(get_db)
):

    product = (
        db.query(models.Product)
        .filter(models.Product.id == product_id)
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    get_history = (
        db.query(models.InventoryLog)
        .filter(models.InventoryLog.product_id == product_id)
        .order_by(models.InventoryLog.timestamp.desc())
        .all()
    )

    return get_history


# Low Stock Products
@router.get("/low-stock", response_model=schemas.LowStockResponse)
def get_low_stock_products(db: Session = Depends(get_db)):

    low_stock_products = (
        db.query(models.Product)
        .filter(
            models.Product.current_stock <= models.Product.reorder_level
        )
        .all()
    )

    return {
        "data": low_stock_products,
        "message": "Low stock products fetched successfully"
    }