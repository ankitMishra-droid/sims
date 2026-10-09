from datetime import datetime
from pydantic import BaseModel

class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    order_date: datetime
    expected_delivery_date: datetime
    status: str

class PurchaseOrderOut(BaseModel):
    po_id: int
    supplier_id: int
    order_date: datetime
    expected_delivery_date: datetime
    status: str

    class Config:
        from_attributes = True

class PurchaseOrderItemCreate(BaseModel):
    po_id: int
    product_id: int
    ordered_quantity: int
    received_quantity: float

class PurchaseOrderItemOut(BaseModel):
    id: int
    po_id: int
    product_id: int
    ordered_quantity: int
    received_quantity: float

    class Config:
        from_attributes = True
