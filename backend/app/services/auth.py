from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_refresh_token,
    generate_reset_token,
    hash_password,
    hash_reset_token,
    verify_password,
)
from ..dependencies.authentication import validate_jwt_user
from ..models.business import Business, BusinessMember
from ..models.users import PasswordResetToken, RevokedToken, User
from ..schemas.auth_schema import UserLoginRequest, UserRegisterRequest

logger = logging.getLogger("sims.auth")

SUPPORTED_LANGUAGE_CODES = {
    "en", "hi", "bho", "ur", "bn", "mr", "gu", "pa", "ta", "te", "kn", "ml"
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_language_code(lang: Optional[str]) -> str:
    code = (lang or "en").strip().lower()
    return code if code in SUPPORTED_LANGUAGE_CODES else "en"


class AuthService:
    @staticmethod
    def get_user_by_email(db: Session, email: str) -> Optional[User]:
        return db.query(User).filter(User.email.ilike(email.strip())).first()

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
        return db.query(User).filter(User.id == user_id).first()

    @classmethod
    def register_user(cls, db: Session, user_in: UserRegisterRequest) -> User:
        clean_email = user_in.email.strip().lower()
        existing = cls.get_user_by_email(db, clean_email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"An account with email '{clean_email}' already exists.",
            )

        allowed_roles = {"owner", "admin", "manager", "analyst", "staff", "supplier"}
        role = (user_in.role or "owner").strip().lower()
        if role not in allowed_roles:
            role = "staff"
        if not user_in.create_workspace and role in {"owner", "admin"}:
            role = "staff"

        allowed_types = {"retailer", "wholesaler", "supplier"}
        biz_type = (user_in.business_type or "").strip().lower()
        if biz_type not in allowed_types:
            biz_type = "supplier" if role == "supplier" else "retailer"

        lang = normalize_language_code(user_in.preferred_language)

        new_user = User(
            name=user_in.name.strip(),
            email=clean_email,
            password_hash=hash_password(user_in.password),
            role=role,
            preferred_language=lang,
            token_version=1,
            is_active=True,
        )
        db.add(new_user)
        db.flush()

        if user_in.create_workspace:
            biz_name = (user_in.business_name or "").strip() or f"{new_user.name}'s Workspace"
            business = Business(
                name=biz_name,
                business_type=biz_type,
                owner_user_id=new_user.id,
                default_language=lang,
                allow_negative_stock=False,
                onboarding_completed=False,
                is_active=True,
            )
            db.add(business)
            db.flush()

            member_role = "supplier" if (biz_type == "supplier" or role == "supplier") else role
            membership = BusinessMember(
                business_id=business.id,
                user_id=new_user.id,
                role=member_role,
                is_active=True,
            )
            db.add(membership)
            new_user.active_business_id = business.id

        db.commit()
        db.refresh(new_user)
        return new_user

    @classmethod
    def authenticate_user(cls, db: Session, login_data: UserLoginRequest) -> User:
        clean_email = login_data.email.strip().lower()
        user = cls.get_user_by_email(db, clean_email)
        if not user or not verify_password(login_data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated. Contact an administrator.",
            )

        return user

    @classmethod
    def create_token_for_user(cls, user: User) -> str:
        token_payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "name": user.name,
            "business_id": user.active_business_id,
            "token_version": user.token_version or 1,
        }
        return create_access_token(data=token_payload)

    @classmethod
    def create_token_pair_for_user(cls, user: User) -> Dict[str, Any]:
        payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "name": user.name,
            "business_id": user.active_business_id,
            "token_version": user.token_version or 1,
        }
        return {
            "access_token": create_access_token(data=payload),
            "refresh_token": create_refresh_token(data=payload),
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": user,
        }

    @classmethod
    def revoke_token_payload(cls, db: Session, payload: Dict[str, Any], user_id: int) -> None:
        jti = payload.get("jti")
        if not jti:
            return
        exists = db.query(RevokedToken.id).filter(RevokedToken.jti == jti).first()
        if exists:
            return
        exp_ts = payload.get("exp")
        expires_at = (
            datetime.fromtimestamp(exp_ts, tz=timezone.utc).replace(tzinfo=None)
            if exp_ts
            else _utcnow() + timedelta(days=1)
        )
        db.add(
            RevokedToken(
                jti=jti,
                user_id=user_id,
                token_type=payload.get("type", "access"),
                expires_at=expires_at,
            )
        )

    @classmethod
    def logout(
        cls,
        db: Session,
        user: User,
        access_token: Optional[str],
        refresh_token: Optional[str] = None,
        revoke_all: bool = False,
    ) -> None:
        if access_token:
            _, access_payload = validate_jwt_user(access_token, expected_type="access", db=db)
            cls.revoke_token_payload(db, access_payload, user.id)

        if refresh_token:
            try:
                refresh_user, refresh_payload = validate_jwt_user(refresh_token, expected_type="refresh", db=db)
                if refresh_user.id == user.id:
                    cls.revoke_token_payload(db, refresh_payload, user.id)
            except HTTPException:
                pass

        if revoke_all:
            user.token_version = (user.token_version or 1) + 1

        db.commit()

    @classmethod
    def refresh_session(cls, db: Session, refresh_token: str) -> Dict[str, Any]:
        user, payload = validate_jwt_user(refresh_token, expected_type="refresh", db=db)
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user account.",
            )
        cls.revoke_token_payload(db, payload, user.id)
        db.commit()
        return cls.create_token_pair_for_user(user)

    @classmethod
    def update_profile(
        cls,
        db: Session,
        user: User,
        name: Optional[str] = None,
        preferred_language: Optional[str] = None,
    ) -> User:
        if name is not None:
            clean = name.strip()
            if len(clean) < 2:
                raise HTTPException(status_code=400, detail="Name must be at least 2 characters.")
            user.name = clean
        if preferred_language is not None:
            user.preferred_language = normalize_language_code(preferred_language)
        db.commit()
        db.refresh(user)
        return user

    @classmethod
    def change_password(
        cls,
        db: Session,
        user: User,
        current_password: str,
        new_password: str,
    ) -> Dict[str, Any]:
        if not verify_password(current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect.",
            )
        if verify_password(new_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from your current password.",
            )
        user.password_hash = hash_password(new_password)
        user.token_version = (user.token_version or 1) + 1
        db.commit()
        db.refresh(user)
        return cls.create_token_pair_for_user(user)

    @classmethod
    def request_password_reset(cls, db: Session, email: str) -> Optional[str]:
        """Issue a single-use SHA-256 hashed reset token. Never expose token over HTTP."""
        clean_email = email.strip().lower()
        user = cls.get_user_by_email(db, clean_email)
        if not user or not user.is_active:
            return None

        raw_token = generate_reset_token()
        token_hash = hash_reset_token(raw_token)
        # Invalidate prior unused tokens for this user
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        ).update({"used_at": _utcnow()})

        reset_row = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=_utcnow() + timedelta(minutes=15),
        )
        db.add(reset_row)
        db.commit()

        cls._dispatch_password_reset_notification(clean_email, raw_token)
        return raw_token

    @staticmethod
    def _mask_email(email: str) -> str:
        if "@" not in email:
            return "***"
        local, domain = email.split("@", 1)
        prefix = local[:1] if local else ""
        return f"{prefix}***@{domain}"

    @staticmethod
    def _dispatch_password_reset_notification(email: str, raw_token: str) -> None:
        smtp_host = os.getenv("SMTP_HOST")
        app_env = os.getenv("APP_ENV", "development").lower()
        if not smtp_host and app_env != "production":
            outbox_path = Path(__file__).resolve().parent.parent.parent / "dev_mail_outbox.log"
            with outbox_path.open("a", encoding="utf-8") as fh:
                fh.write(f"[{_utcnow().isoformat()}] TO={email} RESET_TOKEN={raw_token}\n")
        logger.info("Password reset token generated for account %s", AuthService._mask_email(email))

    @classmethod
    def confirm_password_reset(cls, db: Session, raw_token: str, new_password: str) -> None:
        token_hash = hash_reset_token(raw_token.strip())
        reset_row = (
            db.query(PasswordResetToken)
            .filter(PasswordResetToken.token_hash == token_hash)
            .first()
        )
        if not reset_row or reset_row.used_at is not None or reset_row.expires_at < _utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token.",
            )

        user = db.query(User).filter(User.id == reset_row.user_id, User.is_active.is_(True)).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account unavailable for password reset.",
            )

        user.password_hash = hash_password(new_password)
        user.token_version = (user.token_version or 1) + 1
        reset_row.used_at = _utcnow()
        db.commit()
