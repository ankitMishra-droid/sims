from datetime import datetime
from pydantic import BaseModel, ConfigDict


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
