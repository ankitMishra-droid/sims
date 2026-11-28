"""Phase 8 & Phase 9 SQLAlchemy models for RAG ingestion, chat, credit accounts, immutable ledger & metering."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import base

CREDIT_UNIT_TYPE = BigInteger().with_variant(Integer(), "sqlite")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AIDocument(base):
    """Tenant-scoped uploaded business document and resumable RAG ingestion state."""

    __tablename__ = "ai_documents"
    __table_args__ = (
        Index("ix_ai_docs_biz_status", "business_id", "status"),
        Index("ix_ai_docs_biz_hash", "business_id", "content_hash"),
        Index("ix_ai_docs_biz_created", "business_id", "created_at"),
        CheckConstraint("file_size_bytes >= 0", name="ck_ai_doc_size_non_neg"),
        CheckConstraint("document_version >= 1", name="ck_ai_doc_version_ge_1"),
        CheckConstraint("total_chunks >= 0", name="ck_ai_doc_total_chunks_non_neg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("businesses.id"), nullable=False, index=True
    )
    uploaded_by_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(24), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/octet-stream")
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    doc_category: Mapped[str] = mapped_column(String(32), nullable=False, default="general")
    detected_language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    language_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version_label: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="UPLOADED")
    current_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="UPLOADED")
    last_checkpoint_stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )

    ocr_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )
    ocr_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_needed")

    total_pages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedded_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    embedding_model: Mapped[str] = mapped_column(String(80), nullable=False, default="gemini-embedding-001")
    embedding_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False, default=1536)

    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    processing_duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Phase 9 resumable job checkpoint & cost tracking extensions
    job_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_error_category: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    credits_reserved_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False, default=0, server_default="1000")
    credits_consumed_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False, default=0, server_default="0")
    credits_refunded_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False, default=0, server_default="0")
    total_tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    chunks = relationship("AIDocumentChunk", back_populates="document", cascade="all, delete-orphan")


class AIDocumentChunk(base):
    """Persisted normalized chunk metadata and vector indexing checkpoints."""

    __tablename__ = "ai_document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_ai_chunk_doc_idx"),
        Index("ix_ai_chunks_biz_doc_status", "business_id", "document_id", "embedding_status"),
        Index("ix_ai_chunks_biz_lang", "business_id", "language"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("businesses.id"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    qdrant_point_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section_heading: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_strategy: Mapped[str] = mapped_column(String(32), nullable=False, default="general")
    embedding_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    document = relationship("AIDocument", back_populates="chunks")


class AIConversation(base):
    """Workspace- and user-scoped conversation session."""

    __tablename__ = "ai_conversations"
    __table_args__ = (
        Index("ix_ai_conv_biz_user_updated", "business_id", "user_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("businesses.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New Conversation")
    preferred_language: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    context_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_page_context_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    messages = relationship(
        "AIMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AIMessage.id",
    )


class AIMessage(base):
    """Individual user or assistant turn with verifiable citations, tool logs, and token usage."""

    __tablename__ = "ai_messages"
    __table_args__ = (
        Index("ix_ai_msg_conv_created", "conversation_id", "created_at"),
        Index("ix_ai_msg_biz_user", "business_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("businesses.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")

    sources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    tool_calls_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    pending_action_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    model_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    candidates_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="COMPLETED")
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    conversation = relationship("AIConversation", back_populates="messages")


class AIUsageLog(base):
    """Metered AI operation & credit settlement record scoped strictly per workspace."""

    __tablename__ = "ai_usage_logs"
    __table_args__ = (
        Index("ix_ai_usage_biz_created", "business_id", "created_at"),
        Index("ix_ai_usage_op_status", "operation_type", "status"),
        Index("ix_ai_usage_biz_idem", "business_id", "idempotency_key"),
        Index("ix_ai_usage_biz_err_cat", "business_id", "error_category"),
        CheckConstraint("credits_reserved_units >= 0", name="ck_ai_usage_reserved_non_neg"),
        CheckConstraint("credits_consumed_units >= 0", name="ck_ai_usage_consumed_non_neg"),
        CheckConstraint("credits_refunded_units >= 0", name="ck_ai_usage_refunded_non_neg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("businesses.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    document_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ai_documents.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ai_conversations.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="gemini", server_default="gemini")
    operation_type: Mapped[str] = mapped_column(String(48), nullable=False)
    processing_stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    candidates_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    embedding_inputs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    pricing_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    credits_reserved_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False, default=0, server_default="0")
    credits_consumed_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False, default=0, server_default="0")
    credits_refunded_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False, default=0, server_default="0")
    usage_source: Mapped[str] = mapped_column(String(32), nullable=False, default="provider_reported", server_default="provider_reported")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ok")
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_category: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    provider_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class AICreditAccount(base):
    """Tenant/workspace credit wallet & configurable AI usage policy controls."""

    __tablename__ = "ai_credit_accounts"
    __table_args__ = (
        CheckConstraint("available_units >= 0", name="ck_ai_cred_avail_non_neg"),
        CheckConstraint("reserved_units >= 0", name="ck_ai_cred_resv_non_neg"),
        CheckConstraint("lifetime_granted_units >= 0", name="ck_ai_cred_grant_non_neg"),
        CheckConstraint("lifetime_consumed_units >= 0", name="ck_ai_cred_cons_non_neg"),
        CheckConstraint("lifetime_refunded_units >= 0", name="ck_ai_cred_ref_non_neg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("businesses.id"), unique=True, nullable=False, index=True
    )
    available_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False, default=0, server_default="0")
    reserved_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False, default=0, server_default="0")
    lifetime_granted_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False, default=0, server_default="0")
    lifetime_consumed_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False, default=0, server_default="0")
    lifetime_refunded_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False, default=0, server_default="0")

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", server_default="ACTIVE")
    plan_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="standard", server_default="standard")

    # Tenant-level policy controls (NULL means inherit system AIProviderSettings default)
    rpm_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    daily_request_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    daily_token_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_credits_per_operation_units: Mapped[Optional[int]] = mapped_column(CREDIT_UNIT_TYPE, nullable=True)
    max_concurrent_requests: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_context_turns: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_document_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    policy_override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    policy_updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class AICreditTransaction(base):
    """Immutable double-checked financial credit transaction ledger."""

    __tablename__ = "ai_credit_transactions"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "transaction_type",
            "idempotency_key",
            name="uq_ai_credit_tx_biz_type_idem",
        ),
        Index("ix_ai_credit_tx_biz_created", "business_id", "created_at"),
        Index("ix_ai_credit_tx_biz_type", "business_id", "transaction_type"),
        Index("ix_ai_credit_tx_req", "business_id", "request_id"),
        CheckConstraint("amount_units >= 0", name="ck_ai_tx_amount_non_neg"),
        CheckConstraint("available_after_units >= 0", name="ck_ai_tx_avail_after_non_neg"),
        CheckConstraint("reserved_after_units >= 0", name="ck_ai_tx_resv_after_non_neg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    transaction_uid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    business_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("businesses.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    usage_log_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ai_usage_logs.id", ondelete="SET NULL"), nullable=True
    )
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    credit_delta_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False)
    amount_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False)
    available_before_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False)
    available_after_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False)
    reserved_before_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False)
    reserved_after_units: Mapped[int] = mapped_column(CREDIT_UNIT_TYPE, nullable=False)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="POSTED", server_default="POSTED")
    operation_type: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    billing_reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    pricing_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
