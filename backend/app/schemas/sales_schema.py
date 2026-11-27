from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class SaleCreate(BaseModel):
    product_id: int
    quantity_sold: int = Field(..., gt=0)
    selling_price: float | None = Field(default=None, ge=0)
    idempotency_key: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class SaleCancelRequest(BaseModel):
    reason: str = Field(default="sale_cancelled", min_length=2, max_length=255)


class SaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    product_id: int
    sales_date: datetime
    quantity_sold: int
    selling_price: float
    revenue: float
    status: str = "COMPLETED"
    created_by: int | None = None


class SaleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data: SaleOut
    message: str


class SaleListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data: list[SaleOut]
    total: int | None = None
    message: str
