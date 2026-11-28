from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class InventoryLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    product_id: int
    timestamp: datetime
    movement_type: str
    stock_in: int
    stock_out: int
    previous_stock: int
    closing_stock: int
    quantity: int
    resulting_stock: int
    reference_type: str | None = None
    reference_id: int | None = None
    user_id: int | None = None
    is_synthetic: bool = False
    reason: str


class InventoryLogListResponse(BaseModel):
    data: list[InventoryLogOut]
    message: str


class InventoryPositionOut(BaseModel):
    product_id: int
    sku: str
    name: str
    on_hand_stock: int
    incoming_stock: int
    reserved_stock: int
    available_stock: int
    inventory_position: int
    reorder_level: int
    unit_cost: float
    inventory_value: float
    reservations_supported: bool = False


class StockAlertReadRequest(BaseModel):
    alert_key: str | None = Field(default=None, max_length=120)
    product_id: int | None = None
    mark_all: bool = False


class StockAlertDismissRequest(BaseModel):
    alert_key: str = Field(..., min_length=1, max_length=120)
    alert_type: str = Field(default="LOW_STOCK", max_length=32)
    product_id: int | None = None
    severity: str | None = Field(default=None, max_length=24)
    current_stock: int | None = None
    cooldown_days: int = Field(default=7, ge=1, le=90)
    notes: str | None = Field(default=None, max_length=500)


class StockAlertReopenRequest(BaseModel):
    alert_key: str = Field(..., min_length=1, max_length=120)
