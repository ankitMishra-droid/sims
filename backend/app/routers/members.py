from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies.authentication import get_current_active_user
from ..dependencies.authorization import BusinessContext, require_permission
from ..models.users import User
from ..schemas.business_schema import (
    BusinessInvitationOut,
    BusinessMemberOut,
    InvitationAcceptRequest,
    MemberInviteRequest,
    MemberRoleUpdateRequest,
    WorkspaceMembershipOut,
)
from ..services.workspace_service import WorkspaceService

router = APIRouter(prefix="/api/members", tags=["Workspace Members & Roles"])


@router.get("/", response_model=list[BusinessMemberOut])
def list_workspace_members(
    ctx: BusinessContext = Depends(require_permission("members.read")),
    db: Session = Depends(get_db),
):
    """List members and roles within the active workspace."""
    return WorkspaceService.list_members(db, ctx.business_id)


@router.get("/invitations", response_model=list[BusinessInvitationOut])
def list_workspace_invitations(
    ctx: BusinessContext = Depends(require_permission("members.invite")),
    db: Session = Depends(get_db),
):
    """List workspace invitations issued for the active business."""
    return WorkspaceService.list_invitations(db, ctx.business_id)


@router.post("/invite", response_model=BusinessInvitationOut, status_code=status.HTTP_201_CREATED)
def invite_workspace_member(
    payload: MemberInviteRequest,
    ctx: BusinessContext = Depends(require_permission("members.invite")),
    db: Session = Depends(get_db),
):
    """Invite a user by email to join the active workspace with an explicit role."""
    return WorkspaceService.invite_member(
        db=db,
        business_id=ctx.business_id,
        actor_role=ctx.role,
        invited_by=ctx.user.id,
        email=payload.email,
        role=payload.role,
    )


@router.get("/my-invitations")
def list_my_pending_invitations(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List pending workspace invitations addressed to the authenticated user's email."""
    return WorkspaceService.list_my_invitations(db, current_user)


@router.post("/accept-invitation", response_model=WorkspaceMembershipOut)
def accept_workspace_invitation(
    payload: InvitationAcceptRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Accept an email-matched pending invitation and switch into the workspace."""
    return WorkspaceService.accept_invitation(db, current_user, payload.token)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_workspace_invitation(
    invitation_id: int,
    ctx: BusinessContext = Depends(require_permission("members.invite")),
    db: Session = Depends(get_db),
):
    WorkspaceService.revoke_invitation(db, ctx.business_id, invitation_id)


@router.patch("/{member_id}/role", response_model=BusinessMemberOut)
def update_member_role(
    member_id: int,
    payload: MemberRoleUpdateRequest,
    ctx: BusinessContext = Depends(require_permission("members.manage_roles")),
    db: Session = Depends(get_db),
):
    return WorkspaceService.update_member_role(
        db=db,
        business=ctx.business,
        actor_role=ctx.role,
        member_id=member_id,
        new_role=payload.role,
    )


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_workspace_member(
    member_id: int,
    ctx: BusinessContext = Depends(require_permission("members.manage_roles")),
    db: Session = Depends(get_db),
):
    WorkspaceService.remove_member(
        db=db,
        business=ctx.business,
        actor_role=ctx.role,
        actor_user_id=ctx.user.id,
        member_id=member_id,
    )
