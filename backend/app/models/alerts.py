from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false as sa_false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class StockAlertState(base):
    """Persists per-tenant alert read/unread state and cooldown-guarded dismissal."""

    __tablename__ = "stock_alert_states"
    __table_args__ = (
        UniqueConstraint("business_id", "alert_key", name="uq_stock_alert_state_biz_key"),
        Index(
            "ix_stock_alert_state_biz_status",
            "business_id",
            "status",
            "dismissed_until",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    alert_key: Mapped[str] = mapped_column(String(120), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False, default="LOW_STOCK")
    product_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", server_default="ACTIVE")
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa_false())
    severity_snapshot: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    stock_snapshot: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    dismissed_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    actioned_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )
