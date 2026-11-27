from enum import Enum
from typing import Dict, FrozenSet, Iterable


class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    ANALYST = "analyst"
    STAFF = "staff"
    SUPPLIER = "supplier"


class BusinessType(str, Enum):
    RETAILER = "retailer"
    WHOLESALER = "wholesaler"
    SUPPLIER = "supplier"


ROLE_HIERARCHY = {
    UserRole.OWNER: [UserRole.OWNER, UserRole.ADMIN, UserRole.MANAGER, UserRole.ANALYST, UserRole.STAFF],
    UserRole.ADMIN: [UserRole.ADMIN, UserRole.MANAGER, UserRole.ANALYST, UserRole.STAFF],
    UserRole.MANAGER: [UserRole.MANAGER, UserRole.ANALYST, UserRole.STAFF],
    UserRole.ANALYST: [UserRole.ANALYST, UserRole.STAFF],
    UserRole.STAFF: [UserRole.STAFF],
    UserRole.SUPPLIER: [UserRole.SUPPLIER],
}

ROLE_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    UserRole.OWNER.value: frozenset(
        {
            "business.read",
            "business.update",
            "business.delete",
            "business.transfer_ownership",
            "members.read",
            "members.invite",
            "members.manage_roles",
            "members.manage_admins",
            "onboarding.manage",
            "products.read",
            "products.write",
            "inventory.read",
            "inventory.write",
            "sales.read",
            "sales.create",
            "sales.cancel",
            "suppliers.read",
            "suppliers.write",
            "po.read",
            "po.write",
            "po.receive",
            "po.share",
            "reports.read",
            "supplier_portal.read",
            "supplier_portal.update_status",
        }
    ),
    UserRole.ADMIN.value: frozenset(
        {
            "business.read",
            "business.update",
            "members.read",
            "members.invite",
            "members.manage_roles",
            "onboarding.manage",
            "products.read",
            "products.write",
            "inventory.read",
            "inventory.write",
            "sales.read",
            "sales.create",
            "sales.cancel",
            "suppliers.read",
            "suppliers.write",
            "po.read",
            "po.write",
            "po.receive",
            "po.share",
            "reports.read",
            "supplier_portal.read",
            "supplier_portal.update_status",
        }
    ),
    UserRole.MANAGER.value: frozenset(
        {
            "business.read",
            "members.read",
            "onboarding.manage",
            "products.read",
            "products.write",
            "inventory.read",
            "inventory.write",
            "sales.read",
            "sales.create",
            "sales.cancel",
            "suppliers.read",
            "suppliers.write",
            "po.read",
            "po.write",
            "po.receive",
            "po.share",
            "reports.read",
            "supplier_portal.read",
            "supplier_portal.update_status",
        }
    ),
    UserRole.ANALYST.value: frozenset(
        {
            "business.read",
            "products.read",
            "inventory.read",
            "sales.read",
            "suppliers.read",
            "po.read",
            "reports.read",
        }
    ),
    UserRole.STAFF.value: frozenset(
        {
            "business.read",
            "products.read",
            "inventory.read",
            "sales.read",
            "sales.create",
            "suppliers.read",
            "po.read",
            "po.receive",
        }
    ),
    UserRole.SUPPLIER.value: frozenset(
        {
            "business.read",
            "business.update",
            "onboarding.manage",
            "supplier_portal.read",
            "supplier_portal.update_status",
        }
    ),
}


def _norm_role(role) -> str:
    if isinstance(role, Enum):
        return str(role.value).lower()
    return str(role or "").strip().lower()


def has_sufficient_permission(user_role: str | UserRole, required_role: UserRole) -> bool:
    """Check if user_role satisfies required_role in the hierarchy."""
    try:
        user_enum = user_role if isinstance(user_role, UserRole) else UserRole(_norm_role(user_role))
    except ValueError:
        return False
    return required_role in ROLE_HIERARCHY.get(user_enum, [])


def role_satisfies_any(user_role: str | UserRole, allowed_roles: Iterable[str]) -> bool:
    """Return True if user_role directly matches or outranks an allowed role (owner >= admin)."""
    norm = _norm_role(user_role)
    allowed_set = {_norm_role(r) for r in allowed_roles}
    if norm in allowed_set:
        return True
    if norm == UserRole.OWNER.value and UserRole.ADMIN.value in allowed_set:
        return True
    return False


def get_permissions_for_role(role: str | UserRole) -> list[str]:
    """Return sorted permission keys granted to a workspace role."""
    perms = ROLE_PERMISSIONS.get(_norm_role(role), frozenset())
    return sorted(perms)


def role_has_permission(role: str | UserRole, permission: str) -> bool:
    """Return True if workspace role includes the named permission."""
    perms = ROLE_PERMISSIONS.get(_norm_role(role), frozenset())
    return permission in perms
