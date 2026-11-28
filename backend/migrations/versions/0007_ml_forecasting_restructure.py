"""Add ML forecasting restructure, multi-metric provenance, training runs, and synthetic markers.

Revision ID: 0007_ml_forecasting_restructure
Revises: 0006_existing_users_free_credits
Create Date: 2026-11-28 08:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_ml_forecasting_restructure"
down_revision: Union[str, Sequence[str], None] = "0006_existing_users_free_credits"
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


def _add_missing_columns(bind, insp, table_name: str, columns: list[sa.Column]) -> None:
    if not insp.has_table(table_name):
        return
    existing = _col_names(insp, table_name)
    missing = [col for col in columns if col.name not in existing]
    if not missing:
        return
    for col in missing:
        op.add_column(table_name, col)


def _drop_existing_columns(bind, insp, table_name: str, col_names: tuple[str, ...]) -> None:
    if not insp.has_table(table_name):
        return
    existing = _col_names(insp, table_name)
    to_drop = [name for name in col_names if name in existing]
    if not to_drop:
        return
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text(f"DROP TABLE IF EXISTS _alembic_tmp_{table_name}"))
        with op.batch_alter_table(table_name) as batch_op:
            for name in to_drop:
                batch_op.drop_column(name)
    else:
        for name in to_drop:
            op.drop_column(table_name, name)


def _ensure_index(insp, index_name: str, table_name: str, cols: list[str]) -> None:
    if insp.has_table(table_name) and index_name not in _index_names(insp, table_name):
        op.create_index(index_name, table_name, cols, unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for tbl in ("products", "sales", "inventory_logs", "purchase_orders", "goods_receipts"):
        _add_missing_columns(
            bind,
            insp,
            tbl,
            [sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false())],
        )

    _add_missing_columns(
        bind,
        insp,
        "product_forecasts",
        [
            sa.Column("previous_champion_model", sa.String(length=80), nullable=True),
            sa.Column("dataset_version", sa.String(length=64), nullable=True),
            sa.Column(
                "forecast_scope",
                sa.String(length=64),
                nullable=False,
                server_default="workspace_product_horizon",
            ),
            sa.Column(
                "hierarchical_level",
                sa.String(length=48),
                nullable=False,
                server_default="LEVEL_1_TENANT_PRODUCT",
            ),
            sa.Column("is_synthetic_dataset", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("training_config_json", sa.Text(), nullable=True),
            sa.Column("data_quality_json", sa.Text(), nullable=True),
            sa.Column("champion_selected_at", sa.DateTime(), nullable=True),
            sa.Column("training_completed_at", sa.DateTime(), nullable=True),
        ],
    )

    _add_missing_columns(
        bind,
        insp,
        "model_evaluations",
        [
            sa.Column("display_name", sa.String(length=80), nullable=True),
            sa.Column("forecast_horizon_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("observations_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("training_start_date", sa.DateTime(), nullable=True),
            sa.Column("training_end_date", sa.DateTime(), nullable=True),
            sa.Column("backtest_start_date", sa.DateTime(), nullable=True),
            sa.Column("backtest_end_date", sa.DateTime(), nullable=True),
            sa.Column("mse", sa.Float(), nullable=True),
            sa.Column("bias", sa.Float(), nullable=True),
            sa.Column("stability_score", sa.Float(), nullable=True),
            sa.Column("model_version", sa.String(length=40), nullable=False, server_default="ml-v2"),
            sa.Column("dataset_version", sa.String(length=64), nullable=True),
            sa.Column("eligibility_reason", sa.Text(), nullable=True),
            sa.Column("trained_at", sa.DateTime(), nullable=True),
        ],
    )

    insp = sa.inspect(bind)
    if not insp.has_table("model_training_runs"):
        op.create_table(
            "model_training_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column(
                "forecast_scope",
                sa.String(length=64),
                nullable=False,
                server_default="workspace_product_horizon",
            ),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="COMPLETED"),
            sa.Column("dataset_version", sa.String(length=64), nullable=True),
            sa.Column("model_version", sa.String(length=40), nullable=False, server_default="ml-v2"),
            sa.Column("champion_model", sa.String(length=80), nullable=True),
            sa.Column("previous_champion_model", sa.String(length=80), nullable=True),
            sa.Column("selection_reason", sa.Text(), nullable=True),
            sa.Column("candidate_models_json", sa.Text(), nullable=True),
            sa.Column("training_config_json", sa.Text(), nullable=True),
            sa.Column("artifact_path", sa.String(length=255), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    insp = sa.inspect(bind)
    _ensure_index(insp, "ix_model_training_runs_business_id", "model_training_runs", ["business_id"])
    _ensure_index(insp, "ix_model_training_runs_product_id", "model_training_runs", ["product_id"])
    _ensure_index(
        insp,
        "ix_mtr_biz_prod_horizon",
        "model_training_runs",
        ["business_id", "product_id", "horizon_days", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("model_training_runs"):
        op.drop_table("model_training_runs")

    _drop_existing_columns(
        bind,
        insp,
        "model_evaluations",
        (
            "trained_at",
            "eligibility_reason",
            "dataset_version",
            "model_version",
            "stability_score",
            "bias",
            "mse",
            "backtest_end_date",
            "backtest_start_date",
            "training_end_date",
            "training_start_date",
            "observations_count",
            "forecast_horizon_days",
            "display_name",
        ),
    )

    _drop_existing_columns(
        bind,
        insp,
        "product_forecasts",
        (
            "training_completed_at",
            "champion_selected_at",
            "data_quality_json",
            "training_config_json",
            "is_synthetic_dataset",
            "hierarchical_level",
            "forecast_scope",
            "dataset_version",
            "previous_champion_model",
        ),
    )

    for tbl in ("goods_receipts", "purchase_orders", "inventory_logs", "sales", "products"):
        _drop_existing_columns(bind, insp, tbl, ("is_synthetic",))
