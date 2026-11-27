from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    contact_person: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=255)
    lead_time_days: int = Field(default=7, ge=0, le=365)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    contact_person: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=255)
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    is_active: bool | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    linked_business_id: int | None = None
    name: str
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    lead_time_days: int
    is_active: bool


class SupplierCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data: SupplierOut
    message: str


class SupplierListResponse(BaseModel):
    data: list[SupplierOut]
    total: int | None = None
    message: str


class SupplierResponse(BaseModel):
    data: SupplierOut
    message: str
