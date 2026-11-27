from enum import Enum
from typing import Optional, Tuple
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import models


class MovementType(str, Enum):
    OPENING_STOCK = "OPENING_STOCK"
    PURCHASE_RECEIPT = "PURCHASE_RECEIPT"
    SALE = "SALE"
    STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT"
    RETURN = "RETURN"
    REVERSAL = "REVERSAL"


def get_product_or_404(db: Session, product_id: int, business_id: Optional[int] = None) -> models.Product:
    query = db.query(models.Product).filter(models.Product.id == product_id)
    if business_id is not None:
        query = query.filter(models.Product.business_id == business_id)
    product = query.first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def apply_stock_movement(
    db: Session,
    *,
    product_id: int,
    delta: int,
    movement_type: MovementType | str,
    reason: str,
    business_id: Optional[int] = None,
    user_id: Optional[int] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    allow_negative: bool = False,
) -> Tuple[models.Product, models.InventoryLog]:
    """
    Authoritative, concurrency-safe stock update and ledger append.
    Executes an atomic conditional UPDATE inside the caller's transaction.
    """
    if delta == 0:
        raise HTTPException(status_code=400, detail="Quantity change must be non-zero")
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise HTTPException(status_code=400, detail="Stock movement reason is required")

    product = get_product_or_404(db, product_id, business_id=business_id)
    effective_business_id = business_id if business_id is not None else product.business_id

    stmt = update(models.Product).where(
        models.Product.id == product_id,
        models.Product.business_id == effective_business_id,
    )
    if delta < 0 and not allow_negative:
        stmt = stmt.where(models.Product.current_stock >= abs(delta))

    stmt = stmt.values(current_stock=models.Product.current_stock + delta)
    res = db.execute(stmt)

    if res.rowcount == 0:
        raise HTTPException(status_code=400, detail="Insufficient stock")

    db.expire(product)
    updated_product = get_product_or_404(db, product_id, business_id=effective_business_id)
    closing_stock = int(updated_product.current_stock)
    previous_stock = closing_stock - delta

    mtype = movement_type.value if isinstance(movement_type, MovementType) else str(movement_type)
    log = models.InventoryLog(
        business_id=effective_business_id,
        product_id=product_id,
        movement_type=mtype,
        stock_in=delta if delta > 0 else 0,
        stock_out=abs(delta) if delta < 0 else 0,
        previous_stock=previous_stock,
        closing_stock=closing_stock,
        reference_type=reference_type,
        reference_id=reference_id,
        user_id=user_id,
        reason=clean_reason,
    )
    db.add(log)
    db.flush()
    return updated_product, log


def record_opening_stock(
    db: Session,
    *,
    product: models.Product,
    user_id: Optional[int] = None,
) -> Optional[models.InventoryLog]:
    """Record OPENING_STOCK ledger entry for a newly created product without double-adding stock."""
    if (product.current_stock or 0) <= 0:
        return None
    log = models.InventoryLog(
        business_id=product.business_id,
        product_id=product.id,
        movement_type=MovementType.OPENING_STOCK.value,
        stock_in=int(product.current_stock),
        stock_out=0,
        previous_stock=0,
        closing_stock=int(product.current_stock),
        reference_type="product",
        reference_id=product.id,
        user_id=user_id,
        reason="initial_stock",
    )
    db.add(log)
    db.flush()
    return log


def increase_stock(
    db: Session,
    product_id: int,
    quantity: int,
    reason: str,
    reference_id: Optional[int] = None,
    reference_type: Optional[str] = None,
    business_id: Optional[int] = None,
    user_id: Optional[int] = None,
    movement_type: MovementType | str = MovementType.STOCK_ADJUSTMENT,
) -> models.Product:
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    product, _ = apply_stock_movement(
        db,
        product_id=product_id,
        delta=quantity,
        movement_type=movement_type,
        reason=reason,
        business_id=business_id,
        user_id=user_id,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    return product


def decrease_stock(
    db: Session,
    product_id: int,
    quantity: int,
    reason: str,
    reference_id: Optional[int] = None,
    reference_type: Optional[str] = None,
    business_id: Optional[int] = None,
    user_id: Optional[int] = None,
    movement_type: MovementType | str = MovementType.SALE,
    allow_negative: bool = False,
) -> models.Product:
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    product, _ = apply_stock_movement(
        db,
        product_id=product_id,
        delta=-quantity,
        movement_type=movement_type,
        reason=reason,
        business_id=business_id,
        user_id=user_id,
        reference_type=reference_type,
        reference_id=reference_id,
        allow_negative=allow_negative,
    )
    return product
