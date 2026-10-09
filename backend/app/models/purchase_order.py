import enum
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
from sqlalchemy.orm import relationship, Mapped
from ..database import base

# ============================================================
# Purchase Order
# ============================================================

class EnumStatus(enum.Enum):
    DRAFT = "Draft"
    SENT = "Sent"
    PARTIALLY_RECEIVED = "Partially Received"
    RECEIVED = "Received"
    CANCELLED = "Cancelled"

class PurchaseOrder(base):
    __tablename__ = "purchase_orders"

    po_id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id"),
        nullable=False
    )

    order_date = Column(
        DateTime,
        server_default=func.now()
    )

    expected_delivery_date = Column(
        DateTime,
        nullable=True
    )

    status = Column(
        String,
        default="pending"
    )

    total_amount = Column(Integer, nullable=False)

    notes = Column(String, nullable=False)

    # Many Purchase Orders -> One Supplier
    supplier = relationship(
        "Supplier",
        back_populates="purchase_orders"
    )

    # One Purchase Order -> Many Purchase Order Items
    items = relationship(
        "PurchaseOrderItems",
        back_populates="purchase_order"
    )


# ============================================================
# Purchase Order Items
# ============================================================

class PurchaseOrderItems(base):
    __tablename__ = "purchase_order_items"

    po_item_id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    po_id = Column(
        Integer,
        ForeignKey("purchase_orders.po_id"),
        nullable=False
    )

    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False
    )

    ordered_quantity = Column(
        Integer,
        default=0
    )

    received_quantity = Column(
        Integer,
        default=0
    )

    unit_cost = Column(Integer, nullable=False)

    # Many Purchase Order Items -> One Product
    product = relationship(
        "Product",
        back_populates="purchase_order_items"
    )

    # Many Purchase Order Items -> One Purchase Order
    purchase_order = relationship(
        "PurchaseOrder",
        back_populates="items"
    )
