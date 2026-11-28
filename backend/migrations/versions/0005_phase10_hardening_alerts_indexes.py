"""Add Phase 10 persistent stock alert states and hot multi-tenant composite indexes.

Revision ID: 0005_phase10_hardening_alerts_indexes
Revises: 0004_phase9_credits_usage_quota
Create Date: 2026-11-28 00:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_phase10_hardening_alerts_indexes"
down_revision: Union[str, Sequence[str], None] = "0004_phase9_credits_usage_quota"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_names(insp, table_name: str) -> set[str]:
    if not insp.has_table(table_name):
        return set()
    return {idx["name"] for idx in insp.get_indexes(table_name) if idx.get("name")}


def _ensure_index(insp, name: str, table: str, cols: list[str], unique: bool = False) -> None:
    if insp.has_table(table) and name not in _index_names(insp, table):
        op.create_index(name, table, cols, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("stock_alert_states"):
        op.create_table(
            "stock_alert_states",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("alert_key", sa.String(length=120), nullable=False),
            sa.Column("alert_type", sa.String(length=32), nullable=False, server_default="LOW_STOCK"),
            sa.Column(
                "product_id",
                sa.Integer(),
                sa.ForeignKey("products.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="ACTIVE"),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("severity_snapshot", sa.String(length=24), nullable=True),
            sa.Column("stock_snapshot", sa.Integer(), nullable=True),
            sa.Column("read_at", sa.DateTime(), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(), nullable=True),
            sa.Column("dismissed_until", sa.DateTime(), nullable=True),
            sa.Column(
                "actioned_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "alert_key", name="uq_stock_alert_state_biz_key"),
        )

    insp = sa.inspect(bind)
    _ensure_index(insp, "ix_stock_alert_states_business_id", "stock_alert_states", ["business_id"])
    _ensure_index(insp, "ix_stock_alert_states_product_id", "stock_alert_states", ["product_id"])
    _ensure_index(
        insp,
        "ix_stock_alert_state_biz_status",
        "stock_alert_states",
        ["business_id", "status", "dismissed_until"],
    )

    # Hot multi-tenant composite indexes across operational tables
    _ensure_index(insp, "ix_products_biz_active", "products", ["business_id", "is_active"])
    _ensure_index(insp, "ix_sales_biz_status_date", "sales", ["business_id", "status", "sales_date"])
    _ensure_index(insp, "ix_po_supplier_shared", "purchase_orders", ["supplier_id", "shared_with_supplier"])
    _ensure_index(
        insp,
        "ix_ai_docs_biz_deleted_created",
        "ai_documents",
        ["business_id", "deleted_at", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for idx_name, tbl_name in (
        ("ix_ai_docs_biz_deleted_created", "ai_documents"),
        ("ix_po_supplier_shared", "purchase_orders"),
        ("ix_sales_biz_status_date", "sales"),
        ("ix_products_biz_active", "products"),
    ):
        if idx_name in _index_names(insp, tbl_name):
            op.drop_index(idx_name, table_name=tbl_name)

    if insp.has_table("stock_alert_states"):
        op.drop_table("stock_alert_states")
