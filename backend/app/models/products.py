from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import base


class Product(base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("business_id", "sku", name="uq_product_business_sku"),
        CheckConstraint("current_stock >= 0", name="ck_product_stock_non_negative"),
        CheckConstraint("cost_price >= 0", name="ck_product_cost_non_negative"),
        CheckConstraint("selling_price >= 0", name="ck_product_selling_non_negative"),
        CheckConstraint("reorder_level >= 0", name="ck_product_reorder_non_negative"),
        CheckConstraint("min_order_quantity >= 1", name="ck_product_moq_ge_1"),
        CheckConstraint("order_pack_size >= 1", name="ck_product_pack_ge_1"),
        CheckConstraint(
            "max_stock_level IS NULL OR max_stock_level > 0",
            name="ck_product_max_stock_gt_0",
        ),
        CheckConstraint("review_period_days >= 0", name="ck_product_review_period_non_neg"),
        CheckConstraint(
            "service_level_target >= 0.5 AND service_level_target <= 0.9999",
            name="ck_product_service_level_bounds",
        ),
        CheckConstraint(
            "initial_daily_demand IS NULL OR initial_daily_demand >= 0",
            name="ck_product_init_demand_non_neg",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False, default="General")
    unit: Mapped[str] = mapped_column(String, nullable=False, default="piece")
    cost_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    selling_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reorder_level: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    min_order_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    order_pack_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    max_stock_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    review_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7, server_default="7")
    service_level_target: Mapped[float] = mapped_column(Float, nullable=False, default=0.95, server_default="0.95")
    initial_daily_demand: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    supplier = relationship("Supplier", back_populates="products")
    sales = relationship("Sale", back_populates="product")
    inventory_logs = relationship("InventoryLog", back_populates="product")
    purchase_order_items = relationship("PurchaseOrderItem", back_populates="product")
    forecasts = relationship("ProductForecast", back_populates="product")
    model_evaluations = relationship("ModelEvaluation", back_populates="product")
    replenishment_recommendations = relationship(
        "ReplenishmentRecommendation",
        back_populates="product",
    )
