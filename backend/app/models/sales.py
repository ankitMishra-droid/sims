from datetime import datetime, timezone
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
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


class Sale(base):
    __tablename__ = "sales"
    __table_args__ = (
        Index("ix_sales_biz_prod_date", "business_id", "product_id", "sales_date"),
        UniqueConstraint("business_id", "idempotency_key", name="uq_sale_business_idempotency"),
        CheckConstraint("quantity_sold > 0", name="ck_sale_qty_gt_zero"),
        CheckConstraint("selling_price >= 0", name="ck_sale_price_non_negative"),
        CheckConstraint("revenue >= 0", name="ck_sale_revenue_non_negative"),
    )

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    sales_date = Column(DateTime, default=_utcnow, server_default=func.now(), index=True)
    quantity_sold = Column(Integer, nullable=False)
    selling_price = Column(Float, nullable=False)
    revenue = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="COMPLETED")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    idempotency_key = Column(String(120), nullable=True)
    notes = Column(Text, nullable=True)

    product = relationship("Product", back_populates="sales")
