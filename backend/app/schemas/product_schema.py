from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="General", min_length=1, max_length=100)
    unit: str = Field(default="piece", min_length=1, max_length=32)
    cost_price: float = Field(default=0.0, ge=0)
    selling_price: float = Field(default=0.0, ge=0)
    current_stock: int = Field(default=0, ge=0)
    reorder_level: int = Field(default=10, ge=0)
    min_order_quantity: int = Field(default=1, ge=1)
    order_pack_size: int = Field(default=1, ge=1)
    max_stock_level: int | None = Field(default=None, gt=0)
    review_period_days: int = Field(default=7, ge=0, le=90)
    service_level_target: float = Field(default=0.95, ge=0.5, le=0.9999)
    initial_daily_demand: float | None = Field(default=None, ge=0)
    supplier_id: int | None = None

    @field_validator("sku", "name", mode="before")
    @classmethod
    def strip_required_text(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("category", mode="before")
    @classmethod
    def default_category(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return "General"
        return v.strip()

    @field_validator("unit", mode="before")
    @classmethod
    def default_unit(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return "piece"
        return v.strip()


class ProductUpdate(BaseModel):
    """Product metadata update schema; excludes current_stock so stock only changes via ledger."""
    model_config = ConfigDict(extra="ignore")

    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    cost_price: float | None = Field(default=None, ge=0)
    selling_price: float | None = Field(default=None, ge=0)
    reorder_level: int | None = Field(default=None, ge=0)
    min_order_quantity: int | None = Field(default=None, ge=1)
    order_pack_size: int | None = Field(default=None, ge=1)
    max_stock_level: int | None = Field(default=None, gt=0)
    review_period_days: int | None = Field(default=None, ge=0, le=90)
    service_level_target: float | None = Field(default=None, ge=0.5, le=0.9999)
    initial_daily_demand: float | None = Field(default=None, ge=0)
    supplier_id: int | None = None

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return "General"
        return v.strip()


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    sku: str
    name: str
    category: str | None
    unit: str
    cost_price: float
    selling_price: float
    current_stock: int
    reorder_level: int
    min_order_quantity: int = 1
    order_pack_size: int = 1
    max_stock_level: int | None = None
    review_period_days: int = 7
    service_level_target: float = 0.95
    initial_daily_demand: float | None = None
    supplier_id: int | None
    is_active: bool
    is_synthetic: bool = False
    incoming_stock: int = 0
    reserved_stock: int = 0
    available_stock: int | None = None
    inventory_position: int | None = None


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data: ProductOut
    message: str


class StockInCreate(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)
    reason: str = Field(default="purchase", min_length=2, max_length=255)


class StockAdjustmentCreate(BaseModel):
    product_id: int
    quantity_delta: int
    reason: str = Field(..., min_length=2, max_length=255)
    movement_type: str = "STOCK_ADJUSTMENT"

    @field_validator("quantity_delta")
    @classmethod
    def non_zero_delta(cls, v):
        if v == 0:
            raise ValueError("quantity_delta must be non-zero")
        return v

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class LowStockResponse(BaseModel):
    data: list[ProductOut]
    message: str


class ProductListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data: list[ProductOut]
    total: int | None = None
    message: str


class ProductCsvImportRowError(BaseModel):
    row: int
    sku: str | None = None
    reason: str


class ProductCsvImportResponse(BaseModel):
    created_count: int
    skipped_count: int
    error_count: int
    created_skus: list[str]
    errors: list[ProductCsvImportRowError]
    message: str
