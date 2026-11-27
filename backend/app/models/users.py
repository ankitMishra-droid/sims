from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from ..database import base


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(30), nullable=False, default="staff")
    active_business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True, index=True)
    preferred_language = Column(String(10), nullable=False, default="en")
    token_version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    memberships = relationship("BusinessMember", foreign_keys="BusinessMember.user_id", back_populates="user")

    def __repr__(self):
        return f"<User id={self.id} email='{self.email}' role='{self.role}'>"


class RevokedToken(base):
    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_type = Column(String(20), nullable=False, default="access")
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=False, default=_utcnow)


class PasswordResetToken(base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(128), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
