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
# Product
# ============================================================

class Product(base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)

    sku = Column(
        String,
        unique=True,
        index=True,
        nullable=False
    )

    name = Column(String, nullable=False)
    category = Column(String, nullable=False)

    unit = Column(
        String,
        default="piece"
    )

    cost_price = Column(
        Float,
        default=0
    )

    selling_price = Column(
        Float,
        default=0
    )

    current_stock = Column(
        Integer,
        default=0
    )

    # Reorder Point=(Average Daily Demand×Lead Time Days)+Safety Stock
    reorder_level = Column(
        Integer,
        default=10
    )

    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id"),
        nullable=True
    )

    is_active = Column(
        Boolean, default=True
    )

    # Many Products -> One Supplier
    supplier = relationship(
        "Supplier",
        back_populates="products"
    )

    # One Product -> Many Sales
    sales = relationship(
        "Sale",
        back_populates="product"
    )

    # One Product -> Many Inventory Logs
    inventory_logs = relationship(
        "InventoryLog",
        back_populates="product"
    )

    # One Product -> Many Purchase Order Items
    purchase_order_items = relationship(
        "PurchaseOrderItems",
        back_populates="product"
    )
