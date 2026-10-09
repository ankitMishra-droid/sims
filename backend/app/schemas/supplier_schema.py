from datetime import datetime
from pydantic import BaseModel

class SupplierCreate(BaseModel):
    name: str
    email: str
    phone: int
    address: str
    lead_time_days: int = 7

class SupplierOut(BaseModel):
    id: int
    name: str
    email: str
    phone: int
    address: str
    lead_time_days: int
    is_active: bool

    class Config:
        from_attributes = True