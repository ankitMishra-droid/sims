from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr

class SupplierCreate(BaseModel):
    name: str
    contact_person: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    lead_time_days: int = 7

class SupplierCreateResponse(BaseModel):
    data: SupplierCreate
    message: str

    class Config:
        from_attributes = True

class SupplierUpdate(BaseModel):
    name: str | None = None
    contact_person: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    lead_time_days: int | None = None
    is_active: bool | None = None

class SupplierOut(BaseModel):
    id: int
    name: str
    contact_person: str | None
    email: str
    phone: str
    address: str
    lead_time_days: int
    is_active: bool

    class Config:
        from_attributes = True


class SupplierListResponse(BaseModel):
    data: list[SupplierOut]
    message: str

class SupplierResponse(BaseModel):
    data: SupplierOut
    message: str