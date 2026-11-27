from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class BusinessCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    business_type: str = Field("retailer")
    default_language: Optional[str] = Field("en", max_length=10)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(None, max_length=30)
    address: Optional[str] = Field(None, max_length=255)
    gstin_or_tax_id: Optional[str] = Field(None, max_length=50)
    currency: str = Field("INR", max_length=10)
    low_stock_threshold_default: int = Field(10, ge=0, le=100000)
    allow_negative_stock: bool = False


class BusinessUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    business_type: Optional[str] = None
    default_language: Optional[str] = Field(None, max_length=10)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(None, max_length=30)
    address: Optional[str] = Field(None, max_length=255)
    gstin_or_tax_id: Optional[str] = Field(None, max_length=50)
    currency: Optional[str] = Field(None, max_length=10)
    low_stock_threshold_default: Optional[int] = Field(None, ge=0, le=100000)
    allow_negative_stock: Optional[bool] = None


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    business_type: str
    owner_user_id: int
    default_language: str = "en"
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    gstin_or_tax_id: Optional[str] = None
    currency: str = "INR"
    low_stock_threshold_default: int = 10
    allow_negative_stock: bool = False
    onboarding_completed: bool = False
    is_active: bool = True
    created_at: Optional[datetime] = None


class WorkspaceMembershipOut(BaseModel):
    business: BusinessOut
    role: str
    permissions: List[str]
    is_active_workspace: bool


class WorkspaceSwitchRequest(BaseModel):
    business_id: int


class MemberInviteRequest(BaseModel):
    email: EmailStr
    role: str = Field("staff")


class MemberRoleUpdateRequest(BaseModel):
    role: str


class InvitationAcceptRequest(BaseModel):
    token: str = Field(..., min_length=12)


class BusinessMemberOut(BaseModel):
    id: int
    business_id: int
    user_id: int
    user_name: str
    user_email: str
    role: str
    is_active: bool
    created_at: Optional[datetime] = None


class BusinessInvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    email: str
    role: str
    token: str
    status: str
    expires_at: datetime
    created_at: Optional[datetime] = None


class OnboardingProductSeedItem(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=150)
    category: str = Field("General", max_length=100)
    unit: str = Field("piece", max_length=30)
    cost_price: float = Field(0.0, ge=0)
    selling_price: float = Field(0.0, ge=0)
    reorder_level: int = Field(10, ge=0)
    opening_stock: int = Field(0, ge=0)


class OnboardingSupplierSeedItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    contact_person: Optional[str] = Field(None, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=30)
    lead_time_days: int = Field(7, ge=1, le=365)


class OnboardingStepSaveRequest(BaseModel):
    step: int = Field(..., ge=1, le=10)
    action: str = Field("complete", description="complete, skip, or back")
    data: Dict[str, Any] = Field(default_factory=dict)


class OnboardingProgressOut(BaseModel):
    business_id: int
    business_type: str
    current_step: int
    completed_steps: List[int]
    skipped_steps: List[int]
    step_data: Dict[str, Any]
    is_completed: bool
    applicable_steps: List[int]


class SupplierLinkWorkspaceRequest(BaseModel):
    supplier_business_id: Optional[int] = None


class SupplierPortalOrderItemOut(BaseModel):
    id: int
    product_id: int
    sku: Optional[str] = None
    product_name: Optional[str] = None
    ordered_quantity: int
    received_quantity: int
    unit_cost: float


class SupplierPortalActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    notes: Optional[str] = None
    user_id: int
    created_at: datetime


class SupplierPortalOrderOut(BaseModel):
    id: int
    order_number: Optional[str] = None
    buyer_business_id: int
    buyer_business_name: str
    status: str
    supplier_status: Optional[str] = None
    supplier_notes: Optional[str] = None
    total_amount: float
    order_date: datetime
    expected_delivery_date: Optional[datetime] = None
    shared_at: Optional[datetime] = None
    supplier_acknowledged_at: Optional[datetime] = None
    supplier_dispatched_at: Optional[datetime] = None
    items: List[SupplierPortalOrderItemOut] = Field(default_factory=list)
    actions: List[SupplierPortalActionOut] = Field(default_factory=list)


class SupplierPortalStatusUpdateRequest(BaseModel):
    supplier_status: str = Field(..., description="ACKNOWLEDGED, DISPATCHED, or ISSUE_REPORTED")
    notes: Optional[str] = Field(None, max_length=500)
