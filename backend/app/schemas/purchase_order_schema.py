from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# purchase order status enum
class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"

# purchase order item create
class PurchaseOrderItemCreate(BaseModel):
    product_id: int
    ordered_quantity: int = Field(gt=0)
    unit_cost: float = Field(ge=0)

# purchase order create
class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    expected_delivery_date: date | None = None
    notes: str | None = None

    items: list[PurchaseOrderItemCreate] = Field(
        min_length=1
    )

# purchase order item response
class PurchaseOrderItemOut(BaseModel):
    id: int
    product_id: int
    ordered_quantity: int
    received_quantity: int
    unit_cost: float

    model_config = ConfigDict(from_attributes=True)

# purchase order response
class PurchaseOrderOut(BaseModel):
    id: int
    supplier_id: int
    status: PurchaseOrderStatus
    order_date: datetime
    expected_delivery_date: datetime | None = None
    notes: str | None = None

    items: list[PurchaseOrderItemOut]

    model_config = ConfigDict(from_attributes=True)

# Receive Purchase Order Item
class ReceiveItem(BaseModel):
    purchase_order_item_id: int
    received_quantity: int = Field(gt=0)


# Receive Purchase Order
class ReceivePurchaseOrder(BaseModel):
    items: list[ReceiveItem] = Field(
        min_length=1
    )