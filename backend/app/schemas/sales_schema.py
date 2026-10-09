from datetime import datetime
from pydantic import BaseModel

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

class SaleListResponse(BaseModel):
    data: list[SaleOut]
    message: str

    class Config:
        from_attributes = True