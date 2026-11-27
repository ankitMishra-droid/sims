from datetime import date, datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class PurchaseOrderItemCreate(BaseModel):
    product_id: int
    ordered_quantity: int = Field(gt=0)
    unit_cost: float = Field(ge=0)


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    expected_delivery_date: date | None = None
    notes: str | None = None
    items: list[PurchaseOrderItemCreate] = Field(min_length=1)


class PurchaseOrderItemOut(BaseModel):
    id: int
    product_id: int
    ordered_quantity: int
    received_quantity: int
    unit_cost: float

    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderUpdate(BaseModel):
    """Update draft purchase order metadata/items; status transitions use dedicated endpoints."""
    expected_delivery_date: date | None = None
    notes: str | None = None
    items: list[PurchaseOrderItemCreate] | None = None


class GoodsReceiptItemOut(BaseModel):
    id: int
    purchase_order_item_id: int
    product_id: int
    quantity_received: int

    model_config = ConfigDict(from_attributes=True)


class GoodsReceiptOut(BaseModel):
    id: int
    receipt_number: str
    business_id: int
    purchase_order_id: int
    received_by: int | None = None
    notes: str | None = None
    received_at: datetime
    items: list[GoodsReceiptItemOut] = []

    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderOut(BaseModel):
    id: int
    business_id: int
    order_number: str | None = None
    supplier_id: int
    status: PurchaseOrderStatus
    total_amount: float = 0.0
    order_date: datetime
    expected_delivery_date: datetime | None = None
    notes: str | None = None
    created_by: int | None = None
    sent_at: datetime | None = None
    received_at: datetime | None = None
    cancelled_at: datetime | None = None
    shared_with_supplier: bool = False
    shared_at: datetime | None = None
    supplier_status: str | None = None
    supplier_notes: str | None = None
    supplier_acknowledged_at: datetime | None = None
    supplier_dispatched_at: datetime | None = None
    items: list[PurchaseOrderItemOut]

    model_config = ConfigDict(from_attributes=True)


class ReceiveItem(BaseModel):
    purchase_order_item_id: int
    received_quantity: int = Field(gt=0)
    idempotency_key: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class ReceivePurchaseOrder(BaseModel):
    items: list[ReceiveItem] = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, max_length=120)
    notes: str | None = None
