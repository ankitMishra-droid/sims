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

# ============================================================
# Supplier
# ============================================================

class Supplier(base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(Integer, nullable=False)
    address = Column(String, nullable=False)
    #How many days does this supplier normally take to deliver an order? it tells us when should i order more stock
    lead_time_days = Column(Integer, default=7) # Lead Time Days=Stock Available Date−Purchase Order Date
    is_active = Column(Boolean, default=True)

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
