from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from ..database import base


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Business(base):
    __tablename__ = "businesses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    business_type = Column(String(30), nullable=False, default="retailer")
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    default_language = Column(String(10), nullable=False, default="en")
    contact_email = Column(String(120), nullable=True)
    contact_phone = Column(String(30), nullable=True)
    address = Column(String(255), nullable=True)
    gstin_or_tax_id = Column(String(50), nullable=True)
    currency = Column(String(10), nullable=False, default="INR")
    low_stock_threshold_default = Column(Integer, nullable=False, default=10)
    allow_negative_stock = Column(Boolean, nullable=False, default=False)
    onboarding_completed = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    members = relationship("BusinessMember", back_populates="business", cascade="all, delete-orphan")
    invitations = relationship("BusinessInvitation", back_populates="business", cascade="all, delete-orphan")
    onboarding_progress = relationship(
        "BusinessOnboardingProgress",
        back_populates="business",
        uselist=False,
        cascade="all, delete-orphan",
    )


class BusinessMember(base):
    __tablename__ = "business_members"
    __table_args__ = (
        UniqueConstraint("business_id", "user_id", name="uq_business_member"),
    )

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(30), nullable=False, default="staff")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    business = relationship("Business", back_populates="members")
    user = relationship("User", foreign_keys=[user_id], back_populates="memberships")


class BusinessInvitation(base):
    __tablename__ = "business_invitations"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    email = Column(String(120), nullable=False, index=True)
    role = Column(String(30), nullable=False, default="staff")
    token = Column(String(96), unique=True, nullable=False, index=True)
    invited_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, ACCEPTED, REVOKED
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    business = relationship("Business", back_populates="invitations")


class BusinessOnboardingProgress(base):
    __tablename__ = "business_onboarding_progress"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    current_step = Column(Integer, nullable=False, default=1)
    completed_steps_json = Column(Text, nullable=False, default="[]")
    skipped_steps_json = Column(Text, nullable=False, default="[]")
    step_data_json = Column(Text, nullable=False, default="{}")
    is_completed = Column(Boolean, nullable=False, default=False)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    business = relationship("Business", back_populates="onboarding_progress")
