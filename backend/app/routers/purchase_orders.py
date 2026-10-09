from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(
    prefix="/api/purchase-orders",
    tags=["Purchase Orders"]
)

# Create a new purchase order
@router.post("/", response_model=schemas.PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
def create_purchase_order(payload: schemas.PurchaseOrderCreate, db: Session = Depends(get_db)):
    supplier = db.query(models.Supplier).filter(
        models.Supplier.id == payload.supplier_id,
        models.Supplier.is_active.is_(True)
    ).first() # if supplier id matches then it will also check that supplier is active or not

    if not supplier:
        raise HTTPException(
            status_code=404,
            detail="Active supplier not found"
        )

    # find all items product ids and store in set because set removes duplicates
    product_ids = {item.product_id for item in payload.items}

    # Find all products whose ID exists in product_ids
    products = db.query(models.Product).filter(
        models.Product.id.in_(product_ids)
    ).all()

    # Verify that every product exists
    if len(products) != len(product_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more products were not found"
        )

    # Create the Purchase Order object
    order = models.PurchaseOrder(
        supplier_id=payload.supplier_id,
        expected_delivery_date=payload.expected_delivery_date,
        notes=payload.notes,
        status="DRAFT" # The order exists but hasn't necessarily been finalized/sent to the supplier.
    )

    for item in payload.items:
        # Add this purchase-order item to this purchase order's relationship.
        order.items.append(
            models.PurchaseOrderItem(
                product_id=item.product_id,
                ordered_quantity=item.ordered_quantity,
                received_quantity=0,
                unit_cost=item.unit_cost
            )
        )

    db.add(order)
    db.commit()
    db.refresh(order)
    return order

# Fetch all purchase orders
@router.get("/", response_model=list[schemas.PurchaseOrderOut])
def get_purchase_orders(db: Session = Depends(get_db)):
    orders = db.query(models.PurchaseOrder).order_by(models.PurchaseOrder.order_date.desc()).all()
    return orders

# Fetch a specific purchase order by its ID
@router.get("/{order_id}", response_model=schemas.PurchaseOrderOut)
def get_purchase_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == order_id).first()

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Purchase order not found"
        )

    return order

# Update a specific purchase order by its ID
@router.put("/{order_id}", response_model=schemas.PurchaseOrderOut)
def update_purchase_order(order_id: int, payload: schemas.PurchaseOrderOut, db: Session = Depends(get_db)):
    order = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == order_id).first()

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Purchase order not found"
        )

    # Update the fields of the purchase order
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(order, field, value)

    db.commit()
    db.refresh(order)
    return order

# Delete a specific purchase order by its ID
@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == order_id).first()

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Purchase order not found"
        )

    db.delete(order)
    db.commit()
    return {"message": "Purchase order deleted successfully"}

# Mark a specific purchase order as "RECEIVED" by its ID
@router.post("/{order_id}/receive", response_model=schemas.PurchaseOrderOut)
def receive_purchase_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == order_id).first()

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Purchase order not found"
        )

    # Update the status of the purchase order to "RECEIVED"
    order.status = "RECEIVED"

    # Update the received_quantity for each item in the purchase order
    for item in order.items:
        item.received_quantity = item.ordered_quantity

        # Update the product's current stock based on the received quantity
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if product:
            product.current_stock += item.received_quantity

            # Create an inventory log entry for this stock addition
            inventory_log = models.InventoryLog(
                product_id=product.id,
                stock_in=item.received_quantity,
                stock_out=0,
                closing_stock=product.current_stock,
                reason="purchase_order_received"
            )
            db.add(inventory_log)

    db.commit()
    db.refresh(order)
    return order

# Mark a specific purchase order as "CANCELLED" by its ID
@router.post("/{order_id}/cancel", response_model=schemas.PurchaseOrderOut)
def cancel_purchase_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == order_id).first()

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Purchase order not found"
        )

    # Update the status of the purchase order to "CANCELLED"
    order.status = "CANCELLED"

    db.commit()
    db.refresh(order)
    return order

# Mark a specific purchase order as "PARTIALLY_RECEIVED" by its ID
@router.post(
    "/{order_id}/partially_receive",
    response_model=schemas.PurchaseOrderOut
)
def partially_receive_purchase_order(
    order_id: int,
    payload: schemas.ReceiveItem,
    db: Session = Depends(get_db)
):
    # 1. Find purchase order
    order = db.query(models.PurchaseOrder).filter(
        models.PurchaseOrder.id == order_id
    ).first()

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Purchase order not found"
        )

    # 2. Find the purchase order item
    order_item = db.query(models.PurchaseOrderItem).filter(
        models.PurchaseOrderItem.id == payload.purchase_order_item_id,
        models.PurchaseOrderItem.purchase_order_id == order_id
    ).first()

    if not order_item:
        raise HTTPException(
            status_code=404,
            detail="Purchase order item not found"
        )

    # 3. Calculate remaining quantity
    remaining_quantity = (
        order_item.ordered_quantity -
        order_item.received_quantity
    )

    # 4. Validate received quantity
    if payload.received_quantity > remaining_quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Only {remaining_quantity} units are remaining"
        )

    # find prodcuct associated with the order item
    product = db.query(models.Product).filter(
        models.Product.id == order_item.product_id
    ).first()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    # update received quantity for the purchase order item
    order_item.received_quantity += payload.received_quantity

    # update inventory stock
    product.current_stock += payload.received_quantity

    # create inventory log
    inventory_log = models.InventoryLog(
        product_id=product.id,
        stock_in=payload.received_quantity,
        stock_out=0,
        closing_stock=product.current_stock,
        reason="purchase_order_partially_received"
    )

    db.add(inventory_log)

    # update the purchase order status based on whether all items have been received or not
    all_received = all(
        item.received_quantity == item.ordered_quantity
        for item in order.items
    )

    if all_received:
        order.status = "RECEIVED"
    else:
        order.status = "PARTIALLY_RECEIVED"

    db.commit()

    db.refresh(order)
    db.refresh(product)

    return order
