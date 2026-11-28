from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false as sa_false,
    func,
    true as sa_true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ProductForecast(base):
    """Persisted multi-horizon demand forecast snapshot for a product in a tenant workspace."""

    __tablename__ = "product_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "product_id",
            "horizon_days",
            name="uq_product_forecast_biz_prod_horizon",
        ),
        Index("ix_prod_forecast_biz_prod", "business_id", "product_id"),
        CheckConstraint("horizon_days >= 1", name="ck_pf_horizon_ge_1"),
        CheckConstraint("avg_daily_demand >= 0", name="ck_pf_avg_demand_non_neg"),
        CheckConstraint("demand_std_dev >= 0", name="ck_pf_std_non_neg"),
        CheckConstraint("expected_total_demand >= 0", name="ck_pf_expected_total_non_neg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    data_cutoff_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    data_sufficiency: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW")
    champion_model: Mapped[str] = mapped_column(String(80), nullable=False, default="ColdStartBaseline")
    previous_champion_model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False, default="phase6-v1")
    dataset_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    forecast_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="workspace_product_horizon", server_default="workspace_product_horizon")
    hierarchical_level: Mapped[str] = mapped_column(String(48), nullable=False, default="LEVEL_1_TENANT_PRODUCT", server_default="LEVEL_1_TENANT_PRODUCT")
    selection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_cold_start: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa_false())
    is_synthetic_dataset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa_false())
    history_days_observed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    non_zero_demand_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stockout_days_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_daily_demand: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    demand_std_dev: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    adi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_total_demand: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    daily_forecast_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    historical_summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    evaluation_summary_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    training_config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_quality_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    champion_selected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    training_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    product = relationship("Product", back_populates="forecasts")


class ModelEvaluation(base):
    """Persisted out-of-sample chronological validation metrics per product & model."""

    __tablename__ = "model_evaluations"
    __table_args__ = (
        Index("ix_model_eval_biz_prod_date", "business_id", "product_id", "evaluated_at"),
        Index("ix_model_eval_biz_prod_model", "business_id", "product_id", "model_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa_true())
    is_champion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa_false())
    evaluation_strategy: Mapped[str] = mapped_column(String(50), nullable=False, default="rolling_origin")
    folds_evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    train_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    test_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    forecast_horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    observations_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    data_cutoff_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    training_start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    training_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    backtest_start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    backtest_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    mae: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mse: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rmse: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mape: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    smape: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wape: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mase: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bias: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stability_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False, default="ml-v2", server_default="ml-v2")
    dataset_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    training_time_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="EVALUATED")
    eligibility_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trained_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, server_default=func.now())

    product = relationship("Product", back_populates="model_evaluations")


class ModelTrainingRun(base):
    """Controlled training run, artifact provenance, and champion selection audit log."""

    __tablename__ = "model_training_runs"
    __table_args__ = (
        Index("ix_mtr_biz_prod_horizon", "business_id", "product_id", "horizon_days", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    forecast_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="workspace_product_horizon")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="COMPLETED")
    dataset_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False, default="ml-v2")
    champion_model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    previous_champion_model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    selection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    candidate_models_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    training_config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, server_default=func.now())

    product = relationship("Product")


class ReplenishmentRecommendation(base):
    """Persisted, deduplicated, explainable replenishment & inventory risk recommendation."""

    __tablename__ = "replenishment_recommendations"
    __table_args__ = (
        Index("ix_replen_rec_biz_status", "business_id", "status"),
        Index("ix_replen_rec_biz_prod", "business_id", "product_id"),
        Index("ix_replen_rec_biz_dedup", "business_id", "dedup_key"),
        CheckConstraint("suggested_order_qty >= 0", name="ck_rr_suggested_qty_non_neg"),
        CheckConstraint("safety_stock >= 0", name="ck_rr_safety_stock_non_neg"),
        CheckConstraint("reorder_point >= 0", name="ck_rr_rop_non_neg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)
    recommendation_type: Mapped[str] = mapped_column(String(40), nullable=False, default="REORDER_NOW")
    urgency: Mapped[str] = mapped_column(String(24), nullable=False, default="MEDIUM")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="NEW", server_default="NEW")
    dedup_key: Mapped[str] = mapped_column(String(120), nullable=False)
    on_hand_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    incoming_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inventory_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_daily_demand: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    demand_std_dev: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    lead_time_days: Mapped[float] = mapped_column(Float, nullable=False, default=7.0)
    lead_time_std_days: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    lead_time_source: Mapped[str] = mapped_column(String(40), nullable=False, default="supplier_default")
    review_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    service_level: Mapped[float] = mapped_column(Float, nullable=False, default=0.95)
    lead_time_demand: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reorder_point: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_stock_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suggested_order_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    adjusted_order_qty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    days_of_cover_on_hand: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    days_of_cover_position: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    projected_stockout_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    estimated_order_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    forecast_model_used: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    data_sufficiency: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW")
    explanation_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    explanation_details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    linked_purchase_order_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("purchase_orders.id"),
        nullable=True,
        index=True,
    )
    dismiss_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actioned_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    actioned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    product = relationship("Product", back_populates="replenishment_recommendations")
