"""Add Phase 6 inventory intelligence persistence and product ordering policy columns.

Revision ID: 0002_phase6_intelligence
Revises: 0001_initial_schema
Create Date: 2026-11-27 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_phase6_intelligence"
down_revision: Union[str, Sequence[str], None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_names(insp, table_name: str) -> set[str]:
    if not insp.has_table(table_name):
        return set()
    return {c["name"] for c in insp.get_columns(table_name)}


def _index_names(insp, table_name: str) -> set[str]:
    if not insp.has_table(table_name):
        return set()
    return {idx["name"] for idx in insp.get_indexes(table_name) if idx.get("name")}


def _unique_names(insp, table_name: str) -> set[str]:
    if not insp.has_table(table_name):
        return set()
    names = {uc["name"] for uc in insp.get_unique_constraints(table_name) if uc.get("name")}
    names.update(idx["name"] for idx in insp.get_indexes(table_name) if idx.get("unique") and idx.get("name"))
    return names


def _ensure_index(insp, index_name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    existing = _unique_names(insp, table_name) if unique else _index_names(insp, table_name)
    if index_name not in existing:
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Extend products table with optional ordering/cold-start policy columns
    if insp.has_table("products"):
        existing_cols = _col_names(insp, "products")
        new_cols = [
            sa.Column("min_order_quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("order_pack_size", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("max_stock_level", sa.Integer(), nullable=True),
            sa.Column("review_period_days", sa.Integer(), nullable=False, server_default="7"),
            sa.Column("service_level_target", sa.Float(), nullable=False, server_default="0.95"),
            sa.Column("initial_daily_demand", sa.Float(), nullable=True),
        ]
        missing_cols = [c for c in new_cols if c.name not in existing_cols]
        if missing_cols:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("products") as batch_op:
                    for col in missing_cols:
                        batch_op.add_column(col)
            else:
                for col in missing_cols:
                    op.add_column("products", col)

        # Ensure check constraints exist on PostgreSQL if not already present
        if bind.dialect.name != "sqlite":
            existing_cks = {ck["name"] for ck in insp.get_check_constraints("products") if ck.get("name")}
            ck_specs = [
                ("ck_product_moq_ge_1", "min_order_quantity >= 1"),
                ("ck_product_pack_ge_1", "order_pack_size >= 1"),
                ("ck_product_max_stock_gt_0", "max_stock_level IS NULL OR max_stock_level > 0"),
                ("ck_product_review_period_non_neg", "review_period_days >= 0"),
                (
                    "ck_product_service_level_bounds",
                    "service_level_target >= 0.5 AND service_level_target <= 0.9999",
                ),
                (
                    "ck_product_init_demand_non_neg",
                    "initial_daily_demand IS NULL OR initial_daily_demand >= 0",
                ),
            ]
            for ck_name, ck_sql in ck_specs:
                if ck_name not in existing_cks:
                    op.create_check_constraint(ck_name, "products", ck_sql)

    # 2. product_forecasts table
    if not insp.has_table("product_forecasts"):
        op.create_table(
            "product_forecasts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("data_cutoff_date", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("data_sufficiency", sa.String(length=32), nullable=False, server_default="NEW"),
            sa.Column("champion_model", sa.String(length=80), nullable=False, server_default="ColdStartBaseline"),
            sa.Column("model_version", sa.String(length=40), nullable=False, server_default="phase6-v1"),
            sa.Column("selection_reason", sa.Text(), nullable=True),
            sa.Column("is_cold_start", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("history_days_observed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("non_zero_demand_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stockout_days_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_daily_demand", sa.Float(), nullable=False, server_default="0"),
            sa.Column("demand_std_dev", sa.Float(), nullable=False, server_default="0"),
            sa.Column("cv", sa.Float(), nullable=True),
            sa.Column("adi", sa.Float(), nullable=True),
            sa.Column("expected_total_demand", sa.Float(), nullable=False, server_default="0"),
            sa.Column("daily_forecast_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("historical_summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("evaluation_summary_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "business_id",
                "product_id",
                "horizon_days",
                name="uq_product_forecast_biz_prod_horizon",
            ),
            sa.CheckConstraint("horizon_days >= 1", name="ck_pf_horizon_ge_1"),
            sa.CheckConstraint("avg_daily_demand >= 0", name="ck_pf_avg_demand_non_neg"),
            sa.CheckConstraint("demand_std_dev >= 0", name="ck_pf_std_non_neg"),
            sa.CheckConstraint("expected_total_demand >= 0", name="ck_pf_expected_total_non_neg"),
        )

    # 3. model_evaluations table
    if not insp.has_table("model_evaluations"):
        op.create_table(
            "model_evaluations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("model_name", sa.String(length=80), nullable=False),
            sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_champion", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("evaluation_strategy", sa.String(length=50), nullable=False, server_default="rolling_origin"),
            sa.Column("folds_evaluated", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("train_window_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("test_window_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("data_cutoff_date", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("mae", sa.Float(), nullable=True),
            sa.Column("rmse", sa.Float(), nullable=True),
            sa.Column("mape", sa.Float(), nullable=True),
            sa.Column("smape", sa.Float(), nullable=True),
            sa.Column("wape", sa.Float(), nullable=True),
            sa.Column("mase", sa.Float(), nullable=True),
            sa.Column("training_time_seconds", sa.Float(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="EVALUATED"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("evaluated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    # 4. replenishment_recommendations table
    if not insp.has_table("replenishment_recommendations"):
        op.create_table(
            "replenishment_recommendations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
            sa.Column("recommendation_type", sa.String(length=40), nullable=False, server_default="REORDER_NOW"),
            sa.Column("urgency", sa.String(length=24), nullable=False, server_default="MEDIUM"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="NEW"),
            sa.Column("dedup_key", sa.String(length=120), nullable=False),
            sa.Column("on_hand_stock", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("incoming_stock", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reserved_stock", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("inventory_position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_daily_demand", sa.Float(), nullable=False, server_default="0"),
            sa.Column("demand_std_dev", sa.Float(), nullable=False, server_default="0"),
            sa.Column("lead_time_days", sa.Float(), nullable=False, server_default="7"),
            sa.Column("lead_time_std_days", sa.Float(), nullable=False, server_default="0"),
            sa.Column("lead_time_source", sa.String(length=40), nullable=False, server_default="supplier_default"),
            sa.Column("review_period_days", sa.Integer(), nullable=False, server_default="7"),
            sa.Column("service_level", sa.Float(), nullable=False, server_default="0.95"),
            sa.Column("lead_time_demand", sa.Float(), nullable=False, server_default="0"),
            sa.Column("safety_stock", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reorder_point", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("target_stock_level", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("suggested_order_qty", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("adjusted_order_qty", sa.Integer(), nullable=True),
            sa.Column("days_of_cover_on_hand", sa.Float(), nullable=True),
            sa.Column("days_of_cover_position", sa.Float(), nullable=True),
            sa.Column("projected_stockout_date", sa.DateTime(), nullable=True),
            sa.Column("estimated_order_cost", sa.Float(), nullable=False, server_default="0"),
            sa.Column("forecast_model_used", sa.String(length=80), nullable=True),
            sa.Column("data_sufficiency", sa.String(length=32), nullable=False, server_default="NEW"),
            sa.Column("explanation_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("explanation_details_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("linked_purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=True),
            sa.Column("dismiss_reason", sa.Text(), nullable=True),
            sa.Column("actioned_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("actioned_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("suggested_order_qty >= 0", name="ck_rr_suggested_qty_non_neg"),
            sa.CheckConstraint("safety_stock >= 0", name="ck_rr_safety_stock_non_neg"),
            sa.CheckConstraint("reorder_point >= 0", name="ck_rr_rop_non_neg"),
        )

    insp = sa.inspect(bind)
    _ensure_index(insp, "ix_product_forecasts_business_id", "product_forecasts", ["business_id"])
    _ensure_index(insp, "ix_product_forecasts_product_id", "product_forecasts", ["product_id"])
    _ensure_index(insp, "ix_prod_forecast_biz_prod", "product_forecasts", ["business_id", "product_id"])

    _ensure_index(insp, "ix_model_evaluations_business_id", "model_evaluations", ["business_id"])
    _ensure_index(insp, "ix_model_evaluations_product_id", "model_evaluations", ["product_id"])
    _ensure_index(insp, "ix_model_eval_biz_prod_date", "model_evaluations", ["business_id", "product_id", "evaluated_at"])
    _ensure_index(insp, "ix_model_eval_biz_prod_model", "model_evaluations", ["business_id", "product_id", "model_name"])

    _ensure_index(insp, "ix_replen_rec_business_id", "replenishment_recommendations", ["business_id"])
    _ensure_index(insp, "ix_replen_rec_product_id", "replenishment_recommendations", ["product_id"])
    _ensure_index(insp, "ix_replen_rec_supplier_id", "replenishment_recommendations", ["supplier_id"])
    _ensure_index(insp, "ix_replen_rec_linked_po", "replenishment_recommendations", ["linked_purchase_order_id"])
    _ensure_index(insp, "ix_replen_rec_biz_status", "replenishment_recommendations", ["business_id", "status"])
    _ensure_index(insp, "ix_replen_rec_biz_prod", "replenishment_recommendations", ["business_id", "product_id"])
    _ensure_index(insp, "ix_replen_rec_biz_dedup", "replenishment_recommendations", ["business_id", "dedup_key"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for tbl in (
        "replenishment_recommendations",
        "model_evaluations",
        "product_forecasts",
    ):
        if insp.has_table(tbl):
            op.drop_table(tbl)

    if insp.has_table("products"):
        existing_cols = _col_names(insp, "products")
        cols_to_drop = [
            col
            for col in (
                "initial_daily_demand",
                "service_level_target",
                "review_period_days",
                "max_stock_level",
                "order_pack_size",
                "min_order_quantity",
            )
            if col in existing_cols
        ]
        if cols_to_drop:
            with op.batch_alter_table("products") as batch_op:
                for col in cols_to_drop:
                    batch_op.drop_column(col)
