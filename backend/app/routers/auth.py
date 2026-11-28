from typing import Optional
from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..core.rate_limiter import rate_limit
from ..database import get_db
from ..dependencies.authentication import get_current_active_user, security_scheme
from ..models.users import User
from ..schemas.auth_schema import (
    ChangePasswordRequest,
    LogoutRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserProfileUpdateRequest,
    UserRegisterRequest,
    UserResponse,
)
from ..services.auth import AuthService

router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication & Security"],
)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("auth_register", default_max=20, window_seconds=60, env_var="AUTH_REGISTER_LIMIT"))],
)
def register(user_data: UserRegisterRequest, db: Session = Depends(get_db)):
    """Register a new user account with Argon2id password hashing."""
    return AuthService.register_user(db, user_data)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("auth_login", default_max=30, window_seconds=60, env_var="AUTH_LOGIN_LIMIT"))],
)
def login(login_data: UserLoginRequest, db: Session = Depends(get_db)):
    """Authenticate user credentials and return signed access + refresh tokens."""
    user = AuthService.authenticate_user(db, login_data)
    return AuthService.create_token_pair_for_user(user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("auth_refresh", default_max=30, window_seconds=60, env_var="AUTH_REFRESH_LIMIT"))],
)
def refresh_token(req: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Rotate refresh token and return fresh access + refresh JWTs."""
    return AuthService.refresh_session(db, req.refresh_token)


@router.post("/logout")
def logout(
    req: Optional[LogoutRequest] = None,
    auth_credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Revoke current access/refresh token (or all sessions via revoke_all=true)."""
    token = auth_credentials.credentials if auth_credentials else None
    AuthService.logout(
        db=db,
        user=current_user,
        access_token=token,
        refresh_token=req.refresh_token if req else None,
        revoke_all=req.revoke_all if req else False,
    )
    return {"message": "Signed out successfully."}


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(current_user: User = Depends(get_current_active_user)):
    """Retrieve profile and workspace/language preferences for authenticated user."""
    return current_user


@router.patch("/me", response_model=UserResponse)
def update_current_user_profile(
    payload: UserProfileUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update authenticated user's profile name and personal language preference."""
    return AuthService.update_profile(
        db=db,
        user=current_user,
        name=payload.name,
        preferred_language=payload.preferred_language,
    )


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Verify current password, rotate password hash, invalidate old sessions, return fresh tokens."""
    return AuthService.change_password(
        db=db,
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )


@router.post(
    "/password-reset/request",
    dependencies=[Depends(rate_limit("auth_reset_req", default_max=10, window_seconds=60, env_var="AUTH_RESET_LIMIT"))],
)
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    """Initiate verified password reset without disclosing whether email is registered."""
    AuthService.request_password_reset(db, payload.email)
    return {
        "message": "If an active account exists for that email, a password reset token has been dispatched."
    }


@router.post(
    "/password-reset/confirm",
    dependencies=[Depends(rate_limit("auth_reset_confirm", default_max=10, window_seconds=60, env_var="AUTH_RESET_CONFIRM_LIMIT"))],
)
def confirm_password_reset(payload: PasswordResetConfirmRequest, db: Session = Depends(get_db)):
    """Confirm single-use reset token and rotate password hash + revoke old sessions."""
    AuthService.confirm_password_reset(db, payload.token, payload.new_password)
    return {"message": "Password reset successfully. Please sign in with your new password."}
