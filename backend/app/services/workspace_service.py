from datetime import datetime, timedelta, timezone
import secrets
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..core.permissions import UserRole, get_permissions_for_role
from ..models.business import Business, BusinessInvitation, BusinessMember, BusinessOnboardingProgress
from ..models.users import User
from ..schemas.business_schema import BusinessCreateRequest, BusinessUpdateRequest
from .auth import AuthService, normalize_language_code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


VALID_BUSINESS_TYPES = {"retailer", "wholesaler", "supplier"}
ASSIGNABLE_MEMBER_ROLES = {"admin", "manager", "analyst", "staff", "supplier"}


class WorkspaceService:
    @staticmethod
    def list_user_workspaces(db: Session, user: User) -> List[dict]:
        rows = (
            db.query(BusinessMember, Business)
            .join(Business, Business.id == BusinessMember.business_id)
            .filter(
                BusinessMember.user_id == user.id,
                BusinessMember.is_active.is_(True),
                Business.is_active.is_(True),
            )
            .order_by(Business.id.asc())
            .all()
        )
        result = []
        for member, biz in rows:
            result.append(
                {
                    "business": biz,
                    "role": member.role,
                    "permissions": get_permissions_for_role(member.role),
                    "is_active_workspace": biz.id == user.active_business_id,
                }
            )
        return result

    @staticmethod
    def create_business(db: Session, user: User, payload: BusinessCreateRequest) -> dict:
        btype = (payload.business_type or "retailer").strip().lower()
        if btype not in VALID_BUSINESS_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="business_type must be one of: retailer, wholesaler, supplier",
            )

        lang = normalize_language_code(payload.default_language or user.preferred_language)
        biz = Business(
            name=payload.name.strip(),
            business_type=btype,
            owner_user_id=user.id,
            default_language=lang,
            contact_email=str(payload.contact_email) if payload.contact_email else None,
            contact_phone=payload.contact_phone.strip() if payload.contact_phone else None,
            address=payload.address.strip() if payload.address else None,
            gstin_or_tax_id=payload.gstin_or_tax_id.strip() if payload.gstin_or_tax_id else None,
            currency=(payload.currency or "INR").strip().upper(),
            low_stock_threshold_default=payload.low_stock_threshold_default,
            allow_negative_stock=payload.allow_negative_stock,
            onboarding_completed=False,
            is_active=True,
        )
        db.add(biz)
        db.flush()

        member_role = UserRole.SUPPLIER.value if btype == "supplier" else UserRole.OWNER.value
        member = BusinessMember(
            business_id=biz.id,
            user_id=user.id,
            role=member_role,
            is_active=True,
        )
        db.add(member)

        # Ensure owner keeps access across newly created workspace
        user.active_business_id = biz.id
        if user.role == UserRole.STAFF.value and member_role == UserRole.OWNER.value:
            user.role = UserRole.OWNER.value

        db.add(
            BusinessOnboardingProgress(
                business_id=biz.id,
                user_id=user.id,
                current_step=1,
                completed_steps_json="[]",
                skipped_steps_json="[]",
                step_data_json="{}",
                is_completed=False,
            )
        )
        db.commit()
        db.refresh(biz)
        db.refresh(user)
        return {
            "business": biz,
            "role": member_role,
            "permissions": get_permissions_for_role(member_role),
            "is_active_workspace": True,
        }

    @staticmethod
    def switch_workspace(db: Session, user: User, business_id: int) -> dict:
        row = (
            db.query(BusinessMember, Business)
            .join(Business, Business.id == BusinessMember.business_id)
            .filter(
                BusinessMember.business_id == business_id,
                BusinessMember.user_id == user.id,
                BusinessMember.is_active.is_(True),
                Business.is_active.is_(True),
            )
            .first()
        )
        if not row:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you are not an active member of this workspace.",
            )
        member, biz = row
        user.active_business_id = biz.id
        db.commit()
        db.refresh(user)
        token_bundle = AuthService.create_token_pair_for_user(user)
        return {
            "token": token_bundle,
            "workspace": {
                "business": biz,
                "role": member.role,
                "permissions": get_permissions_for_role(member.role),
                "is_active_workspace": True,
            },
        }

    @staticmethod
    def update_business(db: Session, business: Business, payload: BusinessUpdateRequest) -> Business:
        updates = payload.model_dump(exclude_unset=True)
        if "business_type" in updates and updates["business_type"] is not None:
            btype = str(updates["business_type"]).strip().lower()
            if btype not in VALID_BUSINESS_TYPES:
                raise HTTPException(status_code=400, detail="Invalid business_type.")
            business.business_type = btype
        if "default_language" in updates and updates["default_language"] is not None:
            business.default_language = normalize_language_code(updates["default_language"])
        if "name" in updates and updates["name"] is not None:
            business.name = updates["name"].strip()
        for field in ("contact_phone", "address", "gstin_or_tax_id"):
            if field in updates:
                setattr(business, field, updates[field].strip() if updates[field] else None)
        if "contact_email" in updates:
            business.contact_email = str(updates["contact_email"]) if updates["contact_email"] else None
        if "currency" in updates and updates["currency"] is not None:
            business.currency = updates["currency"].strip().upper()
        for bool_or_int in ("low_stock_threshold_default", "allow_negative_stock"):
            if bool_or_int in updates and updates[bool_or_int] is not None:
                setattr(business, bool_or_int, updates[bool_or_int])

        db.commit()
        db.refresh(business)
        return business

    @staticmethod
    def list_members(db: Session, business_id: int) -> List[dict]:
        rows = (
            db.query(BusinessMember, User)
            .join(User, User.id == BusinessMember.user_id)
            .filter(BusinessMember.business_id == business_id)
            .order_by(BusinessMember.id.asc())
            .all()
        )
        return [
            {
                "id": m.id,
                "business_id": m.business_id,
                "user_id": u.id,
                "user_name": u.name,
                "user_email": u.email,
                "role": m.role,
                "is_active": bool(m.is_active),
                "created_at": m.created_at,
            }
            for m, u in rows
        ]

    @staticmethod
    def invite_member(
        db: Session,
        business_id: int,
        actor_role: str,
        invited_by: int,
        email: str,
        role: str,
    ) -> BusinessInvitation:
        norm_role = (role or "staff").strip().lower()
        if norm_role not in ASSIGNABLE_MEMBER_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"Role must be one of: {', '.join(sorted(ASSIGNABLE_MEMBER_ROLES))}",
            )
        if norm_role == UserRole.ADMIN.value and actor_role != UserRole.OWNER.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the workspace owner can invite Admin members.",
            )

        clean_email = email.strip().lower()
        existing_user = AuthService.get_user_by_email(db, clean_email)
        if existing_user:
            existing_member = (
                db.query(BusinessMember)
                .filter(
                    BusinessMember.business_id == business_id,
                    BusinessMember.user_id == existing_user.id,
                    BusinessMember.is_active.is_(True),
                )
                .first()
            )
            if existing_member:
                raise HTTPException(status_code=400, detail="User is already an active member of this workspace.")

        invite = BusinessInvitation(
            business_id=business_id,
            email=clean_email,
            role=norm_role,
            token=secrets.token_urlsafe(24),
            invited_by=invited_by,
            status="PENDING",
            expires_at=_utcnow() + timedelta(days=7),
        )
        db.add(invite)
        db.commit()
        db.refresh(invite)
        return invite

    @staticmethod
    def list_invitations(db: Session, business_id: int) -> List[BusinessInvitation]:
        return (
            db.query(BusinessInvitation)
            .filter(BusinessInvitation.business_id == business_id)
            .order_by(BusinessInvitation.id.desc())
            .all()
        )

    @staticmethod
    def list_my_invitations(db: Session, user: User) -> List[dict]:
        rows = (
            db.query(BusinessInvitation, Business)
            .join(Business, Business.id == BusinessInvitation.business_id)
            .filter(
                BusinessInvitation.email.ilike(user.email),
                BusinessInvitation.status == "PENDING",
                BusinessInvitation.expires_at >= _utcnow(),
                Business.is_active.is_(True),
            )
            .order_by(BusinessInvitation.id.desc())
            .all()
        )
        return [
            {
                "id": inv.id,
                "business_id": inv.business_id,
                "business_name": biz.name,
                "business_type": biz.business_type,
                "role": inv.role,
                "token": inv.token,
                "expires_at": inv.expires_at,
            }
            for inv, biz in rows
        ]

    @staticmethod
    def accept_invitation(db: Session, user: User, token: str) -> dict:
        inv = (
            db.query(BusinessInvitation)
            .filter(BusinessInvitation.token == token.strip())
            .first()
        )
        if not inv or inv.status != "PENDING" or inv.expires_at < _utcnow():
            raise HTTPException(status_code=400, detail="Invalid or expired workspace invitation.")
        if inv.email.strip().lower() != user.email.strip().lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This invitation belongs to a different email address.",
            )

        biz = db.query(Business).filter(Business.id == inv.business_id, Business.is_active.is_(True)).first()
        if not biz:
            raise HTTPException(status_code=404, detail="Target workspace is no longer active.")

        member = (
            db.query(BusinessMember)
            .filter(
                BusinessMember.business_id == inv.business_id,
                BusinessMember.user_id == user.id,
            )
            .first()
        )
        if member:
            member.role = inv.role
            member.is_active = True
        else:
            member = BusinessMember(
                business_id=inv.business_id,
                user_id=user.id,
                role=inv.role,
                is_active=True,
            )
            db.add(member)

        inv.status = "ACCEPTED"
        inv.accepted_at = _utcnow()
        user.active_business_id = inv.business_id
        db.commit()
        db.refresh(user)
        return {
            "business": biz,
            "role": member.role,
            "permissions": get_permissions_for_role(member.role),
            "is_active_workspace": True,
        }

    @staticmethod
    def revoke_invitation(db: Session, business_id: int, invitation_id: int) -> None:
        inv = (
            db.query(BusinessInvitation)
            .filter(
                BusinessInvitation.id == invitation_id,
                BusinessInvitation.business_id == business_id,
            )
            .first()
        )
        if not inv:
            raise HTTPException(status_code=404, detail="Invitation not found.")
        inv.status = "REVOKED"
        db.commit()

    @staticmethod
    def update_member_role(
        db: Session,
        business: Business,
        actor_role: str,
        member_id: int,
        new_role: str,
    ) -> dict:
        norm_role = (new_role or "").strip().lower()
        if norm_role not in ASSIGNABLE_MEMBER_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"Role must be one of: {', '.join(sorted(ASSIGNABLE_MEMBER_ROLES))}",
            )

        member = (
            db.query(BusinessMember)
            .filter(
                BusinessMember.id == member_id,
                BusinessMember.business_id == business.id,
            )
            .first()
        )
        if not member:
            raise HTTPException(status_code=404, detail="Workspace member not found.")

        if member.role == UserRole.OWNER.value or member.user_id == business.owner_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace owner's role cannot be changed.",
            )

        if actor_role != UserRole.OWNER.value and (
            norm_role == UserRole.ADMIN.value or member.role == UserRole.ADMIN.value
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the workspace owner can assign or modify Admin roles.",
            )

        member.role = norm_role
        db.commit()
        user = db.query(User).filter(User.id == member.user_id).first()
        return {
            "id": member.id,
            "business_id": member.business_id,
            "user_id": member.user_id,
            "user_name": user.name if user else "",
            "user_email": user.email if user else "",
            "role": member.role,
            "is_active": bool(member.is_active),
            "created_at": member.created_at,
        }

    @staticmethod
    def remove_member(
        db: Session,
        business: Business,
        actor_role: str,
        actor_user_id: int,
        member_id: int,
    ) -> None:
        member = (
            db.query(BusinessMember)
            .filter(
                BusinessMember.id == member_id,
                BusinessMember.business_id == business.id,
            )
            .first()
        )
        if not member:
            raise HTTPException(status_code=404, detail="Workspace member not found.")

        if member.role == UserRole.OWNER.value or member.user_id == business.owner_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot remove the workspace owner.",
            )
        if member.user_id == actor_user_id:
            raise HTTPException(status_code=400, detail="Use workspace leave/switch instead of removing yourself.")
        if member.role == UserRole.ADMIN.value and actor_role != UserRole.OWNER.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the workspace owner can remove an Admin.",
            )

        member.is_active = False
        user = db.query(User).filter(User.id == member.user_id).first()
        if user and user.active_business_id == business.id:
            fallback = (
                db.query(BusinessMember)
                .filter(
                    BusinessMember.user_id == user.id,
                    BusinessMember.is_active.is_(True),
                    BusinessMember.business_id != business.id,
                )
                .order_by(BusinessMember.id.asc())
                .first()
            )
            user.active_business_id = fallback.business_id if fallback else None
        db.commit()
