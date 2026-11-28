from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false as sa_false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class PurchaseOrder(base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("business_id", "order_number", name="uq_po_business_order_number"),
        Index("ix_po_biz_status", "business_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    order_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        SQLEnum(PurchaseOrderStatus),
        nullable=False,
        default=PurchaseOrderStatus.DRAFT,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    order_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    expected_delivery_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=_utcnow, onupdate=_utcnow)

    # Supplier portal collaboration fields
    shared_with_supplier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    shared_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    supplier_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    supplier_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    supplier_acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    supplier_dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa_false())

    supplier = relationship("Supplier", back_populates="purchase_orders")
    items = relationship(
        "PurchaseOrderItem",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
    )
    receipts = relationship(
        "GoodsReceipt",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
    )
    supplier_actions = relationship(
        "PurchaseOrderSupplierAction",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
    )


class PurchaseOrderItem(base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        Index("ix_po_items_po_prod", "purchase_order_id", "product_id"),
        CheckConstraint("ordered_quantity > 0", name="ck_po_item_ordered_gt_zero"),
        CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= ordered_quantity",
            name="ck_po_item_received_bounds",
        ),
        CheckConstraint("unit_cost >= 0", name="ck_po_item_cost_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    purchase_order_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_orders.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    ordered_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    received_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    purchase_order = relationship("PurchaseOrder", back_populates="items")
    product = relationship("Product", back_populates="purchase_order_items")


class GoodsReceipt(base):
    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint("business_id", "receipt_number", name="uq_receipt_business_number"),
        UniqueConstraint("business_id", "idempotency_key", name="uq_receipt_business_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    receipt_number: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    purchase_order_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_orders.id"), nullable=False, index=True)
    received_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa_false())
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    purchase_order = relationship("PurchaseOrder", back_populates="receipts")
    items = relationship("GoodsReceiptItem", back_populates="goods_receipt", cascade="all, delete-orphan")


class GoodsReceiptItem(base):
    __tablename__ = "goods_receipt_items"
    __table_args__ = (
        CheckConstraint("quantity_received > 0", name="ck_receipt_item_qty_gt_zero"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    goods_receipt_id: Mapped[int] = mapped_column(Integer, ForeignKey("goods_receipts.id"), nullable=False, index=True)
    purchase_order_item_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_order_items.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)

    goods_receipt = relationship("GoodsReceipt", back_populates="items")


class PurchaseOrderSupplierAction(base):
    __tablename__ = "purchase_order_supplier_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    purchase_order_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_orders.id"), nullable=False, index=True)
    supplier_business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    purchase_order = relationship("PurchaseOrder", back_populates="supplier_actions")
