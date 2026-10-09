from datetime import datetime
from pydantic import BaseModel

class InventoryLogOut(BaseModel):
    id: int
    product_id: int
    timestamp: datetime
    stock_in: int
    stock_out: int
    closing_stock: int
    reason: str

    class Config:
        from_attributes = True

class InventoryLogListResponse(BaseModel):
    data: list[InventoryLogOut]
    message: str
