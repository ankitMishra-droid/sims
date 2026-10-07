from datetime import datetime
from pydantic import BaseModel

class SupplierCreate(BaseModel):
    name: str
    contract: str | None = None
    lead_time_days: int = 7

class SupplierOut(BaseModel):
    id: int
    name: str
    contract: str | None
    lead_time_days: int

    class Config:
        from_attributes = True

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

class SaleCreate(BaseModel):
    product_id: int
    quantity_sold: int
    selling_price: float | None = None

class SaleOut(BaseModel):
    id: int
    product_id: int
    sales_date: datetime
    quantity_sold: int
    selling_price: float
    revenue: float

    class Config:
        from_attributes = True

class SaleResponse(BaseModel):
    data: SaleOut
    message: str

    class Config:
        from_attributes = True

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