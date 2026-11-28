"""Add Phase 8 RAG document ingestion, conversation history, and AI usage telemetry tables.

Revision ID: 0003_phase8_rag_assistant
Revises: 0002_phase6_intelligence
Create Date: 2026-11-27 22:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_phase8_rag_assistant"
down_revision: Union[str, Sequence[str], None] = "0002_phase6_intelligence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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

    if not insp.has_table("ai_documents"):
        op.create_table(
            "ai_documents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("file_type", sa.String(length=24), nullable=False),
            sa.Column("mime_type", sa.String(length=120), nullable=False, server_default="application/octet-stream"),
            sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("storage_path", sa.Text(), nullable=True),
            sa.Column("doc_category", sa.String(length=32), nullable=False, server_default="general"),
            sa.Column("detected_language", sa.String(length=16), nullable=False, server_default="en"),
            sa.Column("language_confidence", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("document_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("version_label", sa.String(length=32), nullable=False, server_default="v1"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="UPLOADED"),
            sa.Column("current_stage", sa.String(length=32), nullable=False, server_default="UPLOADED"),
            sa.Column("last_checkpoint_stage", sa.String(length=32), nullable=True),
            sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ocr_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ocr_status", sa.String(length=40), nullable=False, server_default="not_needed"),
            sa.Column("total_pages", sa.Integer(), nullable=True),
            sa.Column("total_chunks", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("processed_chunks", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("embedded_chunks", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("indexed_chunks", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_chunks", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("embedding_model", sa.String(length=80), nullable=False, server_default="gemini-embedding-001"),
            sa.Column("embedding_version", sa.String(length=32), nullable=False, server_default="v1"),
            sa.Column("embedding_dimensions", sa.Integer(), nullable=False, server_default="1536"),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("last_request_id", sa.String(length=64), nullable=True),
            sa.Column("processing_duration_ms", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint("file_size_bytes >= 0", name="ck_ai_doc_size_non_neg"),
            sa.CheckConstraint("document_version >= 1", name="ck_ai_doc_version_ge_1"),
            sa.CheckConstraint("total_chunks >= 0", name="ck_ai_doc_total_chunks_non_neg"),
        )

    if not insp.has_table("ai_document_chunks"):
        op.create_table(
            "ai_document_chunks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column(
                "document_id",
                sa.Integer(),
                sa.ForeignKey("ai_documents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("chunk_uid", sa.String(length=64), nullable=False),
            sa.Column("qdrant_point_id", sa.String(length=64), nullable=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("section_heading", sa.String(length=255), nullable=True),
            sa.Column("sheet_name", sa.String(length=128), nullable=True),
            sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
            sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("chunk_strategy", sa.String(length=32), nullable=False, server_default="general"),
            sa.Column("embedding_status", sa.String(length=24), nullable=False, server_default="PENDING"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("document_id", "chunk_index", name="uq_ai_chunk_doc_idx"),
        )

    if not insp.has_table("ai_conversations"):
        op.create_table(
            "ai_conversations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False, server_default="New Conversation"),
            sa.Column("preferred_language", sa.String(length=16), nullable=False, server_default="auto"),
            sa.Column("context_summary", sa.Text(), nullable=True),
            sa.Column("last_page_context_json", sa.Text(), nullable=True),
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if not insp.has_table("ai_messages"):
        op.create_table(
            "ai_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "conversation_id",
                sa.Integer(),
                sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
            sa.Column("sources_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("tool_calls_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("pending_action_json", sa.Text(), nullable=True),
            sa.Column("model_name", sa.String(length=80), nullable=True),
            sa.Column("prompt_tokens", sa.Integer(), nullable=True),
            sa.Column("candidates_tokens", sa.Integer(), nullable=True),
            sa.Column("total_tokens", sa.Integer(), nullable=True),
            sa.Column("latency_ms", sa.Float(), nullable=True),
            sa.Column("request_id", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="COMPLETED"),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if not insp.has_table("ai_usage_logs"):
        op.create_table(
            "ai_usage_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column(
                "document_id",
                sa.Integer(),
                sa.ForeignKey("ai_documents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "conversation_id",
                sa.Integer(),
                sa.ForeignKey("ai_conversations.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("operation_type", sa.String(length=48), nullable=False),
            sa.Column("processing_stage", sa.String(length=32), nullable=True),
            sa.Column("model_name", sa.String(length=80), nullable=True),
            sa.Column("prompt_tokens", sa.Integer(), nullable=True),
            sa.Column("candidates_tokens", sa.Integer(), nullable=True),
            sa.Column("total_tokens", sa.Integer(), nullable=True),
            sa.Column("embedding_inputs", sa.Integer(), nullable=True),
            sa.Column("duration_ms", sa.Float(), nullable=True),
            sa.Column("request_id", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="ok"),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("provider_metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    insp = sa.inspect(bind)
    _ensure_index(insp, "ix_ai_documents_business_id", "ai_documents", ["business_id"])
    _ensure_index(insp, "ix_ai_documents_uploaded_by_user_id", "ai_documents", ["uploaded_by_user_id"])
    _ensure_index(insp, "ix_ai_docs_biz_status", "ai_documents", ["business_id", "status"])
    _ensure_index(insp, "ix_ai_docs_biz_hash", "ai_documents", ["business_id", "content_hash"])
    _ensure_index(insp, "ix_ai_docs_biz_created", "ai_documents", ["business_id", "created_at"])

    _ensure_index(insp, "ix_ai_document_chunks_business_id", "ai_document_chunks", ["business_id"])
    _ensure_index(insp, "ix_ai_document_chunks_document_id", "ai_document_chunks", ["document_id"])
    _ensure_index(
        insp,
        "ix_ai_chunks_biz_doc_status",
        "ai_document_chunks",
        ["business_id", "document_id", "embedding_status"],
    )
    _ensure_index(insp, "ix_ai_chunks_biz_lang", "ai_document_chunks", ["business_id", "language"])

    _ensure_index(insp, "ix_ai_conversations_business_id", "ai_conversations", ["business_id"])
    _ensure_index(insp, "ix_ai_conversations_user_id", "ai_conversations", ["user_id"])
    _ensure_index(
        insp,
        "ix_ai_conv_biz_user_updated",
        "ai_conversations",
        ["business_id", "user_id", "updated_at"],
    )

    _ensure_index(insp, "ix_ai_messages_conversation_id", "ai_messages", ["conversation_id"])
    _ensure_index(insp, "ix_ai_messages_business_id", "ai_messages", ["business_id"])
    _ensure_index(insp, "ix_ai_messages_user_id", "ai_messages", ["user_id"])
    _ensure_index(insp, "ix_ai_msg_conv_created", "ai_messages", ["conversation_id", "created_at"])
    _ensure_index(insp, "ix_ai_msg_biz_user", "ai_messages", ["business_id", "user_id"])

    _ensure_index(insp, "ix_ai_usage_logs_business_id", "ai_usage_logs", ["business_id"])
    _ensure_index(insp, "ix_ai_usage_logs_user_id", "ai_usage_logs", ["user_id"])
    _ensure_index(insp, "ix_ai_usage_biz_created", "ai_usage_logs", ["business_id", "created_at"])
    _ensure_index(insp, "ix_ai_usage_op_status", "ai_usage_logs", ["operation_type", "status"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for tbl in (
        "ai_usage_logs",
        "ai_messages",
        "ai_conversations",
        "ai_document_chunks",
        "ai_documents",
    ):
        if insp.has_table(tbl):
            op.drop_table(tbl)
