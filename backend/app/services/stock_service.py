from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models


def get_product_or_404(db, product_id: int) -> models.Product:
    product = db.query(models.Product).filter(
        models.Product.id == product_id
    ).first()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    return product


def increase_stock(
    db,
    product_id: int,
    quantity: int,
    reason: str,
    reference_id: int | None = None,
    reference_type: str | None = None
):
    product = get_product_or_404(db, product_id)

    if quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be greater than zero"
        )

    product.current_stock += quantity

    inventory_log = models.InventoryLog(
        product_id=product_id,
        stock_in=quantity,
        stock_out=0,
        closing_stock=product.current_stock,
        reason=reason
    )

    db.add(inventory_log)
    return product


def decrease_stock(
    db,
    product_id: int,
    quantity: int,
    reason: str,
    reference_id: int | None = None,
    reference_type: str | None = None
):
    product = get_product_or_404(db, product_id)

    if quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be greater than zero"
        )

    if product.current_stock < quantity:
        raise HTTPException(
            status_code=400,
            detail="Insufficient stock"
        )

    product.current_stock -= quantity

    inventory_log = models.InventoryLog(
        product_id=product_id,
        stock_in=0,
        stock_out=quantity,
        closing_stock=product.current_stock,
        reason=reason
    )

    db.add(inventory_log)
    return product