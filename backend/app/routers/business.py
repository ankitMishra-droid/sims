from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies.authentication import get_current_active_user
from ..dependencies.authorization import (
    BusinessContext,
    get_business_context,
    require_permission,
)
from ..models.users import User
from ..schemas.auth_schema import TokenResponse
from ..schemas.business_schema import (
    BusinessCreateRequest,
    BusinessOut,
    BusinessUpdateRequest,
    WorkspaceMembershipOut,
    WorkspaceSwitchRequest,
)
from ..services.workspace_service import WorkspaceService

router = APIRouter(prefix="/api/businesses", tags=["Workspaces & Businesses"])


@router.get("/", response_model=list[WorkspaceMembershipOut])
def list_my_workspaces(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List only business workspaces where the authenticated user holds an active membership."""
    return WorkspaceService.list_user_workspaces(db, current_user)


@router.post("/", response_model=WorkspaceMembershipOut, status_code=status.HTTP_201_CREATED)
def create_business_workspace(
    payload: BusinessCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a new isolated business workspace and assign the creator as owner."""
    return WorkspaceService.create_business(db, current_user, payload)


@router.get("/current", response_model=WorkspaceMembershipOut)
def get_current_workspace(
    ctx: BusinessContext = Depends(get_business_context),
):
    """Retrieve the active workspace profile, membership role, and resolved permissions."""
    from ..core.permissions import get_permissions_for_role

    return {
        "business": ctx.business,
        "role": ctx.role,
        "permissions": get_permissions_for_role(ctx.role),
        "is_active_workspace": True,
    }


@router.put("/current", response_model=BusinessOut)
def update_current_workspace(
    payload: BusinessUpdateRequest,
    ctx: BusinessContext = Depends(require_permission("business.update")),
    db: Session = Depends(get_db),
):
    """Update active workspace profile, default language, and preferences."""
    return WorkspaceService.update_business(db, ctx.business, payload)


class WorkspaceSwitchResponse(TokenResponse):
    workspace: WorkspaceMembershipOut


@router.post("/switch", response_model=WorkspaceSwitchResponse)
def switch_active_workspace(
    payload: WorkspaceSwitchRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Verify workspace membership, switch active workspace, and return refreshed session tokens."""
    res = WorkspaceService.switch_workspace(db, current_user, payload.business_id)
    return {
        **res["token"],
        "workspace": res["workspace"],
    }
