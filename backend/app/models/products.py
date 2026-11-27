from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from ..database import base


class Product(base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("business_id", "sku", name="uq_product_business_sku"),
        CheckConstraint("current_stock >= 0", name="ck_product_stock_non_negative"),
        CheckConstraint("cost_price >= 0", name="ck_product_cost_non_negative"),
        CheckConstraint("selling_price >= 0", name="ck_product_selling_non_negative"),
        CheckConstraint("reorder_level >= 0", name="ck_product_reorder_non_negative"),
    )

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    sku = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False, default="General")
    unit = Column(String, nullable=False, default="piece")
    cost_price = Column(Float, nullable=False, default=0.0)
    selling_price = Column(Float, nullable=False, default=0.0)
    current_stock = Column(Integer, nullable=False, default=0)
    reorder_level = Column(Integer, nullable=False, default=10)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    supplier = relationship("Supplier", back_populates="products")
    sales = relationship("Sale", back_populates="product")
    inventory_logs = relationship("InventoryLog", back_populates="product")
    purchase_order_items = relationship("PurchaseOrderItem", back_populates="product")
