from sqlalchemy import (
    Column,
    Integer,
    DateTime,
    String,
    Float,
    Boolean,
    ForeignKey,
    func
)
from sqlalchemy.orm import relationship
from ..database import base

# supplier model
class Supplier(base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    contact_person = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(30), nullable=True)
    address = Column(String(255), nullable=True)
    lead_time_days = Column(Integer, nullable=False, default=7)
    is_active = Column(Boolean, nullable=False, default=True)

    # One Supplier -> Many Products
    products = relationship(
        "Product",
        back_populates="supplier"
    )

    # One Supplier -> Many Purchase Orders
    purchase_orders = relationship(
        "PurchaseOrder",
        back_populates="supplier"
    )
