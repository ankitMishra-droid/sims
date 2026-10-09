from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, Numeric, String, Text, Enum as SQLEnum
)
from sqlalchemy.orm import relationship

from ..database import base


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class PurchaseOrder(base):
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, index=True)

    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id"),
        nullable=False
    )

    status = Column(
        SQLEnum(PurchaseOrderStatus),
        nullable=False,
        default=PurchaseOrderStatus.DRAFT
    )

    order_date = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    expected_delivery_date = Column(
        DateTime,
        nullable=True
    )

    notes = Column(Text, nullable=True)

    supplier = relationship("Supplier")

    items = relationship(
        "PurchaseOrderItem",
        back_populates="purchase_order",
        cascade="all, delete-orphan"
    )


class PurchaseOrderItem(base):
    __tablename__ = "purchase_order_items"

    id = Column(Integer, primary_key=True, index=True)

    purchase_order_id = Column(
        Integer,
        ForeignKey("purchase_orders.id"),
        nullable=False
    )

    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False
    )

    ordered_quantity = Column(
        Integer,
        nullable=False
    )

    received_quantity = Column(
        Integer,
        nullable=False,
        default=0
    )

    unit_cost = Column(
        Numeric(12, 2),
        nullable=False
    )

    purchase_order = relationship(
        "PurchaseOrder",
        back_populates="items"
    )

    product = relationship("Product", back_populates="purchase_order_items")