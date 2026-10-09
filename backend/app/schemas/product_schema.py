from datetime import datetime
from pydantic import BaseModel

class ProductCreate(BaseModel):
    sku: str
    name: str
    category: str | None = None
    unit: str = "piece"
    cost_price: float = 0
    selling_price: float = 0
    current_stock: int = 0
    reorder_level: int = 10
    supplier_id: int | None = None

class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    category: str | None
    unit: str
    cost_price: float
    selling_price: float
    current_stock: int
    reorder_level: int
    supplier_id: int | None
    is_active: bool

    class Config:
        from_attributes = True

class ProductResponse(BaseModel):
    data: ProductOut
    message: str

    class Config:
        from_attributes = True

class StockInCreate(BaseModel):
    product_id: int
    quantity: int
    reason: str = "purchase"

class LowStockResponse(BaseModel):
    data: list[ProductOut]
    message: str