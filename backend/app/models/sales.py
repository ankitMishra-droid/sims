from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false as sa_false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Sale(base):
    __tablename__ = "sales"
    __table_args__ = (
        Index("ix_sales_biz_prod_date", "business_id", "product_id", "sales_date"),
        UniqueConstraint("business_id", "idempotency_key", name="uq_sale_business_idempotency"),
        CheckConstraint("quantity_sold > 0", name="ck_sale_qty_gt_zero"),
        CheckConstraint("selling_price >= 0", name="ck_sale_price_non_negative"),
        CheckConstraint("revenue >= 0", name="ck_sale_revenue_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    sales_date: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, server_default=func.now(), index=True)
    quantity_sold: Mapped[int] = mapped_column(Integer, nullable=False)
    selling_price: Mapped[float] = mapped_column(Float, nullable=False)
    revenue: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED")
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa_false())
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    product = relationship("Product", back_populates="sales")
