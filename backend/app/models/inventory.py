from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    false as sa_false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryLog(base):
    __tablename__ = "inventory_logs"
    __table_args__ = (
        Index("ix_inventory_logs_biz_prod_ts", "business_id", "product_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, server_default=func.now(), index=True)
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False, default="STOCK_ADJUSTMENT")
    stock_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stock_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    previous_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closing_stock: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa_false())
    reason: Mapped[str] = mapped_column(String, nullable=False)

    product = relationship("Product", back_populates="inventory_logs")

    @property
    def quantity(self) -> int:
        return (self.stock_in or 0) - (self.stock_out or 0)

    @property
    def resulting_stock(self) -> int:
        return self.closing_stock
