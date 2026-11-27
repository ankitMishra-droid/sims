"""Initial cross-dialect SIMS schema (SQLite & PostgreSQL compatible).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-27 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PO_STATUS_VALUES = ("DRAFT", "SENT", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED")


def _ensure_pg_po_status_enum(bind) -> None:
    if bind.dialect.name != "postgresql":
        return
    bind.execute(
        sa.text(
            """
            DO $$
            BEGIN
                CREATE TYPE purchaseorderstatus AS ENUM (
                    'DRAFT', 'SENT', 'PARTIALLY_RECEIVED', 'RECEIVED', 'CANCELLED'
                );
            EXCEPTION
                WHEN duplicate_object THEN NULL;
            END $$;
            """
        )
    )


def _po_status_type(bind):
    if bind.dialect.name == "postgresql":
        return postgresql.ENUM(*PO_STATUS_VALUES, name="purchaseorderstatus", create_type=False)
    return sa.Enum(*PO_STATUS_VALUES, name="purchaseorderstatus")


def _col_names(insp, table_name: str) -> set[str]:
    if not insp.has_table(table_name):
        return set()
    return {c["name"] for c in insp.get_columns(table_name)}


def _add_col_if_missing(insp, table_name: str, column: sa.Column) -> None:
    if column.name not in _col_names(insp, table_name):
        op.add_column(table_name, column)


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
    _ensure_pg_po_status_enum(bind)
    po_status_type = _po_status_type(bind)

    # 1. users (created first without circular FK to businesses; FK added if missing after businesses)
    if not insp.has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("email", sa.String(length=120), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("role", sa.String(length=30), nullable=False, server_default="staff"),
            sa.Column("active_business_id", sa.Integer(), nullable=True),
            sa.Column("preferred_language", sa.String(length=10), nullable=False, server_default="en"),
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    else:
        _add_col_if_missing(insp, "users", sa.Column("active_business_id", sa.Integer(), nullable=True))
        _add_col_if_missing(insp, "users", sa.Column("preferred_language", sa.String(length=10), nullable=True, server_default="en"))
        _add_col_if_missing(insp, "users", sa.Column("token_version", sa.Integer(), nullable=True, server_default="1"))

    # 2. businesses
    if not insp.has_table("businesses"):
        op.create_table(
            "businesses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("business_type", sa.String(length=30), nullable=False, server_default="retailer"),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("default_language", sa.String(length=10), nullable=False, server_default="en"),
            sa.Column("contact_email", sa.String(length=120), nullable=True),
            sa.Column("contact_phone", sa.String(length=30), nullable=True),
            sa.Column("address", sa.String(length=255), nullable=True),
            sa.Column("gstin_or_tax_id", sa.String(length=50), nullable=True),
            sa.Column("currency", sa.String(length=10), nullable=False, server_default="INR"),
            sa.Column("low_stock_threshold_default", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("allow_negative_stock", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    else:
        _add_col_if_missing(insp, "businesses", sa.Column("default_language", sa.String(length=10), nullable=True, server_default="en"))
        _add_col_if_missing(insp, "businesses", sa.Column("contact_email", sa.String(length=120), nullable=True))
        _add_col_if_missing(insp, "businesses", sa.Column("contact_phone", sa.String(length=30), nullable=True))
        _add_col_if_missing(insp, "businesses", sa.Column("address", sa.String(length=255), nullable=True))
        _add_col_if_missing(insp, "businesses", sa.Column("gstin_or_tax_id", sa.String(length=50), nullable=True))
        _add_col_if_missing(insp, "businesses", sa.Column("currency", sa.String(length=10), nullable=True, server_default="INR"))
        _add_col_if_missing(insp, "businesses", sa.Column("low_stock_threshold_default", sa.Integer(), nullable=True, server_default="10"))
        _add_col_if_missing(insp, "businesses", sa.Column("onboarding_completed", sa.Boolean(), nullable=True, server_default=sa.false()))

    if bind.dialect.name == "postgresql":
        fk_cols = {
            col
            for fk in insp.get_foreign_keys("users")
            for col in fk.get("constrained_columns", [])
        } if insp.has_table("users") else set()
        if "active_business_id" not in fk_cols:
            op.create_foreign_key(
                "fk_users_active_business_id",
                "users",
                "businesses",
                ["active_business_id"],
                ["id"],
            )

    # 3. business_members
    if not insp.has_table("business_members"):
        op.create_table(
            "business_members",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("role", sa.String(length=30), nullable=False, server_default="staff"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("business_id", "user_id", name="uq_business_member"),
        )

    # 4. business_invitations
    if not insp.has_table("business_invitations"):
        op.create_table(
            "business_invitations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("email", sa.String(length=120), nullable=False),
            sa.Column("role", sa.String(length=30), nullable=False, server_default="staff"),
            sa.Column("token", sa.String(length=96), nullable=False, unique=True),
            sa.Column("invited_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("accepted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    # 5. business_onboarding_progress
    if not insp.has_table("business_onboarding_progress"):
        op.create_table(
            "business_onboarding_progress",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False, unique=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("current_step", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("completed_steps_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("skipped_steps_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("step_data_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("is_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    # 6. revoked_tokens & password_reset_tokens
    if not insp.has_table("revoked_tokens"):
        op.create_table(
            "revoked_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("jti", sa.String(length=64), nullable=False, unique=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token_type", sa.String(length=20), nullable=False, server_default="access"),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if not insp.has_table("password_reset_tokens"):
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    # 7. suppliers
    if not insp.has_table("suppliers"):
        op.create_table(
            "suppliers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("linked_business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=True),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("contact_person", sa.String(length=100), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("phone", sa.String(length=30), nullable=True),
            sa.Column("address", sa.String(length=255), nullable=True),
            sa.Column("lead_time_days", sa.Integer(), nullable=False, server_default="7"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.UniqueConstraint("business_id", "name", name="uq_supplier_business_name"),
        )
    else:
        _add_col_if_missing(insp, "suppliers", sa.Column("business_id", sa.Integer(), nullable=True))
        _add_col_if_missing(insp, "suppliers", sa.Column("linked_business_id", sa.Integer(), nullable=True))
        _add_col_if_missing(insp, "suppliers", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        _add_col_if_missing(insp, "suppliers", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    # 8. products
    if not insp.has_table("products"):
        op.create_table(
            "products",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("sku", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=False, server_default="General"),
            sa.Column("unit", sa.String(), nullable=False, server_default="piece"),
            sa.Column("cost_price", sa.Float(), nullable=False, server_default="0"),
            sa.Column("selling_price", sa.Float(), nullable=False, server_default="0"),
            sa.Column("current_stock", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reorder_level", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.UniqueConstraint("business_id", "sku", name="uq_product_business_sku"),
            sa.CheckConstraint("current_stock >= 0", name="ck_product_stock_non_negative"),
            sa.CheckConstraint("cost_price >= 0", name="ck_product_cost_non_negative"),
            sa.CheckConstraint("selling_price >= 0", name="ck_product_selling_non_negative"),
            sa.CheckConstraint("reorder_level >= 0", name="ck_product_reorder_non_negative"),
        )
    else:
        _add_col_if_missing(insp, "products", sa.Column("business_id", sa.Integer(), nullable=True))
        _add_col_if_missing(insp, "products", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        _add_col_if_missing(insp, "products", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    # 9. sales
    if not insp.has_table("sales"):
        op.create_table(
            "sales",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("sales_date", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("quantity_sold", sa.Integer(), nullable=False),
            sa.Column("selling_price", sa.Float(), nullable=False),
            sa.Column("revenue", sa.Float(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="COMPLETED"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("idempotency_key", sa.String(length=120), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.UniqueConstraint("business_id", "idempotency_key", name="uq_sale_business_idempotency"),
            sa.CheckConstraint("quantity_sold > 0", name="ck_sale_qty_gt_zero"),
            sa.CheckConstraint("selling_price >= 0", name="ck_sale_price_non_negative"),
            sa.CheckConstraint("revenue >= 0", name="ck_sale_revenue_non_negative"),
        )
    else:
        _add_col_if_missing(insp, "sales", sa.Column("business_id", sa.Integer(), nullable=True))
        _add_col_if_missing(insp, "sales", sa.Column("status", sa.String(length=20), nullable=True, server_default="COMPLETED"))
        _add_col_if_missing(insp, "sales", sa.Column("created_by", sa.Integer(), nullable=True))
        _add_col_if_missing(insp, "sales", sa.Column("idempotency_key", sa.String(length=120), nullable=True))
        _add_col_if_missing(insp, "sales", sa.Column("notes", sa.Text(), nullable=True))

    # 10. inventory_logs
    if not insp.has_table("inventory_logs"):
        op.create_table(
            "inventory_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("movement_type", sa.String(length=30), nullable=False, server_default="STOCK_ADJUSTMENT"),
            sa.Column("stock_in", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stock_out", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("previous_stock", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("closing_stock", sa.Integer(), nullable=False),
            sa.Column("reference_type", sa.String(length=50), nullable=True),
            sa.Column("reference_id", sa.Integer(), nullable=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reason", sa.String(), nullable=False),
        )
    else:
        _add_col_if_missing(insp, "inventory_logs", sa.Column("business_id", sa.Integer(), nullable=True))
        _add_col_if_missing(insp, "inventory_logs", sa.Column("movement_type", sa.String(length=30), nullable=True))
        _add_col_if_missing(insp, "inventory_logs", sa.Column("previous_stock", sa.Integer(), nullable=True))
        _add_col_if_missing(insp, "inventory_logs", sa.Column("reference_type", sa.String(length=50), nullable=True))
        _add_col_if_missing(insp, "inventory_logs", sa.Column("reference_id", sa.Integer(), nullable=True))
        _add_col_if_missing(insp, "inventory_logs", sa.Column("user_id", sa.Integer(), nullable=True))

    # 11. purchase_orders
    if not insp.has_table("purchase_orders"):
        op.create_table(
            "purchase_orders",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("order_number", sa.String(length=40), nullable=True),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False),
            sa.Column("status", po_status_type, nullable=False, server_default="DRAFT"),
            sa.Column("total_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("order_date", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("expected_delivery_date", sa.DateTime(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("shared_with_supplier", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("shared_at", sa.DateTime(), nullable=True),
            sa.Column("supplier_status", sa.String(length=40), nullable=True),
            sa.Column("supplier_notes", sa.Text(), nullable=True),
            sa.Column("supplier_acknowledged_at", sa.DateTime(), nullable=True),
            sa.Column("supplier_dispatched_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("business_id", "order_number", name="uq_po_business_order_number"),
        )
    else:
        _add_col_if_missing(insp, "purchase_orders", sa.Column("business_id", sa.Integer(), nullable=True))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("order_number", sa.String(length=40), nullable=True))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("total_amount", sa.Numeric(12, 2), nullable=True, server_default="0"))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("created_by", sa.Integer(), nullable=True))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("sent_at", sa.DateTime(), nullable=True))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("received_at", sa.DateTime(), nullable=True))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("updated_at", sa.DateTime(), nullable=True))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("shared_with_supplier", sa.Boolean(), nullable=True, server_default=sa.false()))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("shared_at", sa.DateTime(), nullable=True))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("supplier_status", sa.String(length=40), nullable=True))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("supplier_notes", sa.Text(), nullable=True))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("supplier_acknowledged_at", sa.DateTime(), nullable=True))
        _add_col_if_missing(insp, "purchase_orders", sa.Column("supplier_dispatched_at", sa.DateTime(), nullable=True))

    # 12. purchase_order_items
    if not insp.has_table("purchase_order_items"):
        op.create_table(
            "purchase_order_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("ordered_quantity", sa.Integer(), nullable=False),
            sa.Column("received_quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
            sa.CheckConstraint("ordered_quantity > 0", name="ck_po_item_ordered_gt_zero"),
            sa.CheckConstraint("received_quantity >= 0 AND received_quantity <= ordered_quantity", name="ck_po_item_received_bounds"),
            sa.CheckConstraint("unit_cost >= 0", name="ck_po_item_cost_non_negative"),
        )

    # 13. goods_receipts & goods_receipt_items
    if not insp.has_table("goods_receipts"):
        op.create_table(
            "goods_receipts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("receipt_number", sa.String(length=40), nullable=False),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=False),
            sa.Column("received_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("idempotency_key", sa.String(length=120), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "receipt_number", name="uq_receipt_business_number"),
            sa.UniqueConstraint("business_id", "idempotency_key", name="uq_receipt_business_idempotency"),
        )

    if not insp.has_table("goods_receipt_items"):
        op.create_table(
            "goods_receipt_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("goods_receipt_id", sa.Integer(), sa.ForeignKey("goods_receipts.id"), nullable=False),
            sa.Column("purchase_order_item_id", sa.Integer(), sa.ForeignKey("purchase_order_items.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("quantity_received", sa.Integer(), nullable=False),
            sa.CheckConstraint("quantity_received > 0", name="ck_receipt_item_qty_gt_zero"),
        )

    # 14. purchase_order_supplier_actions
    if not insp.has_table("purchase_order_supplier_actions"):
        op.create_table(
            "purchase_order_supplier_actions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=False),
            sa.Column("supplier_business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("action", sa.String(length=40), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    # Refresh inspector after table/column creation and ensure indexes cleanly
    insp = sa.inspect(bind)

    # Drop legacy global-unique ix_products_sku if upgrading an old single-tenant database
    if insp.has_table("products"):
        for idx in insp.get_indexes("products"):
            if idx.get("name") == "ix_products_sku" and idx.get("unique"):
                op.drop_index("ix_products_sku", table_name="products")
                insp = sa.inspect(bind)
                break
        for uc in insp.get_unique_constraints("products"):
            if uc.get("column_names") == ["sku"] and uc.get("name"):
                op.drop_constraint(uc["name"], "products", type_="unique")
                insp = sa.inspect(bind)

    _ensure_index(insp, "ix_users_email", "users", ["email"], unique=True)
    _ensure_index(insp, "ix_users_active_business_id", "users", ["active_business_id"])
    _ensure_index(insp, "ix_businesses_owner_user_id", "businesses", ["owner_user_id"])
    _ensure_index(insp, "ix_business_members_business_id", "business_members", ["business_id"])
    _ensure_index(insp, "ix_business_members_user_id", "business_members", ["user_id"])
    _ensure_index(insp, "ix_business_invitations_business_id", "business_invitations", ["business_id"])
    _ensure_index(insp, "ix_business_invitations_email", "business_invitations", ["email"])
    _ensure_index(insp, "ix_suppliers_business_id", "suppliers", ["business_id"])
    _ensure_index(insp, "ix_suppliers_linked_business_id", "suppliers", ["linked_business_id"])
    _ensure_index(insp, "ix_suppliers_name", "suppliers", ["name"])
    _ensure_index(insp, "ix_products_business_id", "products", ["business_id"])
    _ensure_index(insp, "ix_products_supplier_id", "products", ["supplier_id"])
    _ensure_index(insp, "ix_products_sku", "products", ["sku"])
    _ensure_index(insp, "ix_sales_business_id", "sales", ["business_id"])
    _ensure_index(insp, "ix_sales_product_id", "sales", ["product_id"])
    _ensure_index(insp, "ix_sales_sales_date", "sales", ["sales_date"])
    _ensure_index(insp, "ix_sales_biz_prod_date", "sales", ["business_id", "product_id", "sales_date"])
    _ensure_index(insp, "ix_inventory_logs_business_id", "inventory_logs", ["business_id"])
    _ensure_index(insp, "ix_inventory_logs_product_id", "inventory_logs", ["product_id"])
    _ensure_index(insp, "ix_inventory_logs_timestamp", "inventory_logs", ["timestamp"])
    _ensure_index(insp, "ix_inventory_logs_biz_prod_ts", "inventory_logs", ["business_id", "product_id", "timestamp"])
    _ensure_index(insp, "ix_purchase_orders_business_id", "purchase_orders", ["business_id"])
    _ensure_index(insp, "ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"])
    _ensure_index(insp, "ix_purchase_orders_order_number", "purchase_orders", ["order_number"])
    _ensure_index(insp, "ix_po_biz_status", "purchase_orders", ["business_id", "status"])
    _ensure_index(insp, "ix_po_items_po_prod", "purchase_order_items", ["purchase_order_id", "product_id"])
    _ensure_index(insp, "ix_goods_receipts_business_id", "goods_receipts", ["business_id"])
    _ensure_index(insp, "ix_goods_receipts_purchase_order_id", "goods_receipts", ["purchase_order_id"])
    _ensure_index(insp, "ix_po_supplier_actions_po_id", "purchase_order_supplier_actions", ["purchase_order_id"])
    _ensure_index(insp, "ix_po_supplier_actions_sup_biz", "purchase_order_supplier_actions", ["supplier_business_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for tbl in (
        "purchase_order_supplier_actions",
        "goods_receipt_items",
        "goods_receipts",
        "purchase_order_items",
        "purchase_orders",
        "inventory_logs",
        "sales",
        "products",
        "suppliers",
        "password_reset_tokens",
        "revoked_tokens",
        "business_onboarding_progress",
        "business_invitations",
        "business_members",
    ):
        op.drop_table(tbl)

    if bind.dialect.name == "postgresql":
        op.drop_constraint("fk_users_active_business_id", "users", type_="foreignkey")
    op.drop_table("businesses")
    op.drop_table("users")

    if bind.dialect.name == "postgresql":
        sa.Enum(*PO_STATUS_VALUES, name="purchaseorderstatus").drop(bind, checkfirst=True)
