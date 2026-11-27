from dataclasses import dataclass
from typing import Callable, List, Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.business import Business, BusinessMember
from ..models.users import User
from ..core.permissions import UserRole, role_has_permission, role_satisfies_any
from .authentication import get_current_active_user


@dataclass
class BusinessContext:
    user: User
    business: Business
    membership: BusinessMember
    business_id: int
    role: str


def get_business_context(
    current_user: User = Depends(get_current_active_user),
    x_business_id: Optional[int] = Header(default=None, alias="X-Business-Id"),
    db: Session = Depends(get_db),
) -> BusinessContext:
    """Resolve and verify authenticated user's active business workspace membership."""
    target_biz_id = x_business_id or current_user.active_business_id

    query = (
        db.query(BusinessMember, Business)
        .join(Business, Business.id == BusinessMember.business_id)
        .filter(
            BusinessMember.user_id == current_user.id,
            BusinessMember.is_active.is_(True),
            Business.is_active.is_(True),
        )
    )

    if target_biz_id is not None:
        row = query.filter(BusinessMember.business_id == target_biz_id).first()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied for the requested business workspace.",
            )
    else:
        row = query.order_by(BusinessMember.id.asc()).first()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No active business workspace membership found. Create or join a workspace first.",
            )

    membership, business = row
    return BusinessContext(
        user=current_user,
        business=business,
        membership=membership,
        business_id=business.id,
        role=membership.role,
    )


def require_business_roles(allowed_roles: List[str]) -> Callable:
    """Dependency factory enforcing workspace membership and allowed roles."""

    def checker(ctx: BusinessContext = Depends(get_business_context)) -> BusinessContext:
        if not role_satisfies_any(ctx.role, allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Requires one of roles: {', '.join(allowed_roles)}",
            )
        return ctx

    return checker


def require_permission(permission: str) -> Callable:
    """Dependency factory enforcing a named granular permission in the active workspace."""

    def checker(ctx: BusinessContext = Depends(get_business_context)) -> BusinessContext:
        if not role_has_permission(ctx.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required workspace permission: {permission}",
            )
        return ctx

    return checker


def require_business_types(allowed_types: List[str]) -> Callable:
    """Dependency factory enforcing active workspace business_type."""

    allowed_norm = {t.lower() for t in allowed_types}

    def checker(ctx: BusinessContext = Depends(get_business_context)) -> BusinessContext:
        btype = str(ctx.business.business_type or "").lower()
        if btype not in allowed_norm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This endpoint requires business type: {', '.join(allowed_types)}",
            )
        return ctx

    return checker


def require_role(allowed_roles: List[str]) -> Callable:
    """Dependency factory that checks if current user possesses one of the allowed roles."""

    def role_checker(current_user: User = Depends(get_current_active_user)) -> User:
        if not role_satisfies_any(current_user.role, allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Requires one of roles: {', '.join(allowed_roles)}",
            )
        return current_user

    return role_checker


def require_admin(current_user: User = Depends(get_current_active_user)) -> User:
    """Convenience dependency requiring Owner or Admin privileges."""
    if not role_satisfies_any(current_user.role, [UserRole.ADMIN.value]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required for this action.",
        )
    return current_user
