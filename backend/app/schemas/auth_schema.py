from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Full name of the user")
    email: EmailStr = Field(..., description="Unique email address for login")
    password: str = Field(..., min_length=6, max_length=100, description="Plaintext password")
    role: Optional[str] = Field("owner", description="Workspace role: owner, admin, manager, analyst, staff, or supplier")
    business_name: Optional[str] = Field(None, max_length=150)
    business_type: Optional[str] = Field("retailer")
    preferred_language: Optional[str] = Field("en", max_length=10)
    create_workspace: bool = Field(True, description="Automatically provision a default workspace on signup")


class UserLoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Registered email address")
    password: str = Field(..., description="Password")


class UserProfileUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    preferred_language: Optional[str] = Field(None, min_length=2, max_length=10)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=100)
    new_password: str = Field(..., min_length=6, max_length=100)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=200)
    new_password: str = Field(..., min_length=6, max_length=100)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=16)


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None
    revoke_all: bool = False


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    active_business_id: Optional[int] = None
    preferred_language: str = "en"
    is_active: bool
    created_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = 86400
    user: UserResponse


class TokenData(BaseModel):
    user_id: Optional[int] = None
    email: Optional[str] = None
    role: Optional[str] = None
