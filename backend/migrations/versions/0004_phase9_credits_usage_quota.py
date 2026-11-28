"""Add Phase 9 AI credit accounts, immutable transaction ledger, metered usage & ingestion checkpoints.

Revision ID: 0004_phase9_credits_usage_quota
Revises: 0003_phase8_rag_assistant
Create Date: 2026-11-27 23:25:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_phase9_credits_usage_quota"
down_revision: Union[str, Sequence[str], None] = "0003_phase8_rag_assistant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CREDIT_UNIT_TYPE = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _col_names(insp, table_name: str) -> set[str]:
    if not insp.has_table(table_name):
        return set()
    return {col["name"] for col in insp.get_columns(table_name)}


def _index_names(insp, table_name: str) -> set[str]:
    if not insp.has_table(table_name):
        return set()
    return {idx["name"] for idx in insp.get_indexes(table_name) if idx.get("name")}


def _ensure_index(insp, name: str, table: str, cols: list[str], unique: bool = False) -> None:
    if name not in _index_names(insp, table):
        op.create_index(name, table, cols, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("ai_credit_accounts"):
        op.create_table(
            "ai_credit_accounts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False, unique=True),
            sa.Column("available_units", CREDIT_UNIT_TYPE, nullable=False, server_default="0"),
            sa.Column("reserved_units", CREDIT_UNIT_TYPE, nullable=False, server_default="0"),
            sa.Column("lifetime_granted_units", CREDIT_UNIT_TYPE, nullable=False, server_default="0"),
            sa.Column("lifetime_consumed_units", CREDIT_UNIT_TYPE, nullable=False, server_default="0"),
            sa.Column("lifetime_refunded_units", CREDIT_UNIT_TYPE, nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="ACTIVE"),
            sa.Column("plan_tier", sa.String(length=32), nullable=False, server_default="standard"),
            sa.Column("rpm_limit", sa.Integer(), nullable=True),
            sa.Column("daily_request_limit", sa.Integer(), nullable=True),
            sa.Column("daily_token_limit", sa.Integer(), nullable=True),
            sa.Column("max_credits_per_operation_units", CREDIT_UNIT_TYPE, nullable=True),
            sa.Column("max_concurrent_requests", sa.Integer(), nullable=True),
            sa.Column("max_context_turns", sa.Integer(), nullable=True),
            sa.Column("max_document_mb", sa.Integer(), nullable=True),
            sa.Column("policy_override_reason", sa.Text(), nullable=True),
            sa.Column(
                "policy_updated_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("available_units >= 0", name="ck_ai_cred_avail_non_neg"),
            sa.CheckConstraint("reserved_units >= 0", name="ck_ai_cred_resv_non_neg"),
            sa.CheckConstraint("lifetime_granted_units >= 0", name="ck_ai_cred_grant_non_neg"),
            sa.CheckConstraint("lifetime_consumed_units >= 0", name="ck_ai_cred_cons_non_neg"),
            sa.CheckConstraint("lifetime_refunded_units >= 0", name="ck_ai_cred_ref_non_neg"),
        )

    if not insp.has_table("ai_credit_transactions"):
        op.create_table(
            "ai_credit_transactions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("transaction_uid", sa.String(length=64), nullable=False, unique=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "usage_log_id",
                sa.Integer(),
                sa.ForeignKey("ai_usage_logs.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("request_id", sa.String(length=64), nullable=True),
            sa.Column("idempotency_key", sa.String(length=128), nullable=True),
            sa.Column("transaction_type", sa.String(length=32), nullable=False),
            sa.Column("credit_delta_units", CREDIT_UNIT_TYPE, nullable=False),
            sa.Column("amount_units", CREDIT_UNIT_TYPE, nullable=False),
            sa.Column("available_before_units", CREDIT_UNIT_TYPE, nullable=False),
            sa.Column("available_after_units", CREDIT_UNIT_TYPE, nullable=False),
            sa.Column("reserved_before_units", CREDIT_UNIT_TYPE, nullable=False),
            sa.Column("reserved_after_units", CREDIT_UNIT_TYPE, nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="POSTED"),
            sa.Column("operation_type", sa.String(length=48), nullable=True),
            sa.Column("billing_reference", sa.String(length=128), nullable=True),
            sa.Column("pricing_version", sa.String(length=32), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "business_id",
                "transaction_type",
                "idempotency_key",
                name="uq_ai_credit_tx_biz_type_idem",
            ),
            sa.CheckConstraint("amount_units >= 0", name="ck_ai_tx_amount_non_neg"),
            sa.CheckConstraint("available_after_units >= 0", name="ck_ai_tx_avail_after_non_neg"),
            sa.CheckConstraint("reserved_after_units >= 0", name="ck_ai_tx_resv_after_non_neg"),
        )

    # Extend ai_documents cleanly with Phase 9 resumable checkpoint/cost columns
    insp = sa.inspect(bind)
    doc_cols = _col_names(insp, "ai_documents")
    if doc_cols:
        with op.batch_alter_table("ai_documents") as batch_op:
            if "job_id" not in doc_cols:
                batch_op.add_column(sa.Column("job_id", sa.String(length=64), nullable=True))
            if "last_error_category" not in doc_cols:
                batch_op.add_column(sa.Column("last_error_category", sa.String(length=48), nullable=True))
            if "next_retry_at" not in doc_cols:
                batch_op.add_column(sa.Column("next_retry_at", sa.DateTime(), nullable=True))
            if "credits_reserved_units" not in doc_cols:
                batch_op.add_column(
                    sa.Column("credits_reserved_units", CREDIT_UNIT_TYPE, nullable=False, server_default="0")
                )
            if "credits_consumed_units" not in doc_cols:
                batch_op.add_column(
                    sa.Column("credits_consumed_units", CREDIT_UNIT_TYPE, nullable=False, server_default="0")
                )
            if "credits_refunded_units" not in doc_cols:
                batch_op.add_column(
                    sa.Column("credits_refunded_units", CREDIT_UNIT_TYPE, nullable=False, server_default="0")
                )
            if "total_tokens_used" not in doc_cols:
                batch_op.add_column(
                    sa.Column("total_tokens_used", sa.Integer(), nullable=False, server_default="0")
                )

    # Extend ai_usage_logs cleanly with Phase 9 metering & credit accounting columns
    usage_cols = _col_names(insp, "ai_usage_logs")
    if usage_cols:
        with op.batch_alter_table("ai_usage_logs") as batch_op:
            if "provider" not in usage_cols:
                batch_op.add_column(
                    sa.Column("provider", sa.String(length=32), nullable=False, server_default="gemini")
                )
            if "estimated_tokens" not in usage_cols:
                batch_op.add_column(sa.Column("estimated_tokens", sa.Integer(), nullable=True))
            if "pricing_version" not in usage_cols:
                batch_op.add_column(sa.Column("pricing_version", sa.String(length=32), nullable=True))
            if "idempotency_key" not in usage_cols:
                batch_op.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
            if "credits_reserved_units" not in usage_cols:
                batch_op.add_column(
                    sa.Column("credits_reserved_units", CREDIT_UNIT_TYPE, nullable=False, server_default="0")
                )
            if "credits_consumed_units" not in usage_cols:
                batch_op.add_column(
                    sa.Column("credits_consumed_units", CREDIT_UNIT_TYPE, nullable=False, server_default="0")
                )
            if "credits_refunded_units" not in usage_cols:
                batch_op.add_column(
                    sa.Column("credits_refunded_units", CREDIT_UNIT_TYPE, nullable=False, server_default="0")
                )
            if "usage_source" not in usage_cols:
                batch_op.add_column(
                    sa.Column(
                        "usage_source",
                        sa.String(length=32),
                        nullable=False,
                        server_default="provider_reported",
                    )
                )
            if "error_category" not in usage_cols:
                batch_op.add_column(sa.Column("error_category", sa.String(length=48), nullable=True))

    insp = sa.inspect(bind)
    _ensure_index(insp, "ix_ai_credit_accounts_business_id", "ai_credit_accounts", ["business_id"], unique=True)
    _ensure_index(insp, "ix_ai_credit_transactions_business_id", "ai_credit_transactions", ["business_id"])
    _ensure_index(insp, "ix_ai_credit_transactions_user_id", "ai_credit_transactions", ["user_id"])
    _ensure_index(insp, "ix_ai_credit_tx_biz_created", "ai_credit_transactions", ["business_id", "created_at"])
    _ensure_index(insp, "ix_ai_credit_tx_biz_type", "ai_credit_transactions", ["business_id", "transaction_type"])
    _ensure_index(insp, "ix_ai_credit_tx_req", "ai_credit_transactions", ["business_id", "request_id"])
    _ensure_index(insp, "ix_ai_usage_biz_idem", "ai_usage_logs", ["business_id", "idempotency_key"])
    _ensure_index(insp, "ix_ai_usage_biz_err_cat", "ai_usage_logs", ["business_id", "error_category"])

    # Safely initialize zero-balance credit accounts for any pre-existing active businesses without inventing free commercial grants
    if insp.has_table("businesses") and insp.has_table("ai_credit_accounts"):
        biz_rows = bind.execute(sa.text("SELECT id FROM businesses ORDER BY id ASC")).fetchall()
        for (biz_id,) in biz_rows:
            exists = bind.execute(
                sa.text("SELECT id FROM ai_credit_accounts WHERE business_id = :bid"),
                {"bid": biz_id},
            ).first()
            if not exists:
                bind.execute(
                    sa.text(
                        "INSERT INTO ai_credit_accounts "
                        "(business_id, available_units, reserved_units, lifetime_granted_units, "
                        "lifetime_consumed_units, lifetime_refunded_units, status, plan_tier) "
                        "VALUES (:bid, 0, 0, 0, 0, 0, 'ACTIVE', 'standard')"
                    ),
                    {"bid": biz_id},
                )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for idx_name, tbl_name in (
        ("ix_ai_usage_biz_idem", "ai_usage_logs"),
        ("ix_ai_usage_biz_err_cat", "ai_usage_logs"),
    ):
        if idx_name in _index_names(insp, tbl_name):
            op.drop_index(idx_name, table_name=tbl_name)

    usage_cols = _col_names(insp, "ai_usage_logs")
    if usage_cols:
        with op.batch_alter_table("ai_usage_logs") as batch_op:
            for col in (
                "error_category",
                "usage_source",
                "credits_refunded_units",
                "credits_consumed_units",
                "credits_reserved_units",
                "idempotency_key",
                "pricing_version",
                "estimated_tokens",
                "provider",
            ):
                if col in usage_cols:
                    batch_op.drop_column(col)

    doc_cols = _col_names(insp, "ai_documents")
    if doc_cols:
        with op.batch_alter_table("ai_documents") as batch_op:
            for col in (
                "total_tokens_used",
                "credits_refunded_units",
                "credits_consumed_units",
                "credits_reserved_units",
                "next_retry_at",
                "last_error_category",
                "job_id",
            ):
                if col in doc_cols:
                    batch_op.drop_column(col)

    for tbl in ("ai_credit_transactions", "ai_credit_accounts"):
        if insp.has_table(tbl):
            op.drop_table(tbl)
