from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from ..database import base


class Supplier(base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_supplier_business_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    linked_business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    contact_person = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(30), nullable=True)
    address = Column(String(255), nullable=True)
    lead_time_days = Column(Integer, nullable=False, default=7)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    products = relationship("Product", back_populates="supplier")
    purchase_orders = relationship("PurchaseOrder", back_populates="supplier")
