"""Pydantic schemas for Phase 7 diagnostics and Phase 8 RAG documents, retrieval, & assistant."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class AIProbeRequest(BaseModel):
    probe_qdrant: bool = Field(True, description="Verify Qdrant connectivity and collection schema.")
    probe_gemini_embeddings: bool = Field(
        False, description="Run minimal Gemini embedding generation check."
    )
    probe_gemini_llm: bool = Field(
        False, description="Run minimal Gemini LLM generation check."
    )


class AIComponentHealthOut(BaseModel):
    status: str
    configured: bool
    detail: str
    model: Optional[str] = None
    dimensions: Optional[int] = None
    collection_name: Optional[str] = None
    collection_exists: Optional[bool] = None
    schema_matches: Optional[bool] = None
    endpoint_host: Optional[str] = None
    latency_ms: Optional[float] = None
    error_code: Optional[str] = None


class AIHealthResponseOut(BaseModel):
    overall_status: str
    environment: str
    request_id: str
    circuit_breakers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    components: Dict[str, AIComponentHealthOut]


class AIDocumentChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    chunk_uid: str
    page_number: Optional[int] = None
    section_heading: Optional[str] = None
    sheet_name: Optional[str] = None
    language: str
    char_count: int
    token_estimate: int
    chunk_strategy: str
    embedding_status: str
    text: str


class AIDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    uploaded_by_user_id: int
    filename: str
    title: str
    file_type: str
    mime_type: str
    file_size_bytes: int
    doc_category: str
    detected_language: str
    language_confidence: float
    document_version: int
    version_label: str
    status: str
    current_stage: str
    last_checkpoint_stage: Optional[str] = None
    job_id: Optional[str] = None
    ocr_required: bool
    ocr_status: str
    total_pages: Optional[int] = None
    total_chunks: int
    processed_chunks: int
    embedded_chunks: int
    indexed_chunks: int
    failed_chunks: int
    embedding_model: str
    embedding_version: str
    embedding_dimensions: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    last_error_category: Optional[str] = None
    next_retry_at: Optional[datetime] = None
    retryable: bool
    credits_consumed: float = 0.0
    credits_refunded: float = 0.0
    total_tokens_used: int = 0
    processing_duration_ms: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class AIDocumentUploadResponse(BaseModel):
    document: AIDocumentOut
    duplicate_detected: bool = False
    message: str


class AIDocumentDetailResponse(BaseModel):
    document: AIDocumentOut
    chunks: List[AIDocumentChunkOut]


class AIDocumentStatusOut(BaseModel):
    id: int
    status: str
    current_stage: str
    last_checkpoint_stage: Optional[str] = None
    job_id: Optional[str] = None
    total_pages: Optional[int] = None
    total_chunks: int
    processed_chunks: int
    embedded_chunks: int
    indexed_chunks: int
    failed_chunks: int
    ocr_required: bool
    ocr_status: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    last_error_category: Optional[str] = None
    next_retry_at: Optional[datetime] = None
    retryable: bool
    credits_consumed: float = 0.0
    credits_refunded: float = 0.0
    total_tokens_used: int = 0
    progress_percent: float


class RetrievalSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(5, ge=1, le=20)
    min_score: float = Field(0.12, ge=0.0, le=1.0)
    language: Optional[str] = None
    doc_category: Optional[str] = None
    document_ids: Optional[List[int]] = None


class RetrievalEvidenceOut(BaseModel):
    document_id: int
    document_title: str
    filename: str
    file_type: str
    doc_category: str
    document_version: str
    chunk_id: str
    chunk_index: int
    page_number: Optional[int] = None
    section_heading: Optional[str] = None
    sheet_name: Optional[str] = None
    language: str
    excerpt: str
    vector_score: float
    lexical_score: float
    combined_score: float
    match_reason: str


class RetrievalSearchResponse(BaseModel):
    request_id: str
    detected_language: str
    focused_query: str
    exact_identifiers: List[str]
    semantic_used: bool
    lexical_used: bool
    vector_error_code: Optional[str] = None
    latency_ms: float
    evidence: List[RetrievalEvidenceOut]


class AIConversationCreateRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    preferred_language: str = Field("auto", pattern="^(auto|en|hi|mixed)$")
    page_context: Optional[Dict[str, Any]] = None


class AIConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    user_id: int
    title: str
    preferred_language: str
    created_at: datetime
    updated_at: datetime


class AIMessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    language: str
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    pending_action: Optional[Dict[str, Any]] = None
    model_name: Optional[str] = None
    prompt_tokens: Optional[int] = None
    candidates_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    status: str
    created_at: datetime


class AIConversationDetailOut(BaseModel):
    conversation: AIConversationOut
    messages: List[AIMessageOut]


class AIChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[int] = None
    preferred_language: str = Field("auto", pattern="^(auto|en|hi|mixed)$")
    page_context: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = Field(None, min_length=1, max_length=128)


class AIChatResponse(BaseModel):
    conversation: AIConversationOut
    message: AIMessageOut
    citations: List[Dict[str, Any]]
    tools_used: List[Dict[str, Any]]
    pending_action: Optional[Dict[str, Any]] = None
    response_language: str
    request_id: str
    idempotent_replay: bool = False
    credits_used: float = 0.0
    credits_reserved: float = 0.0
    credits_refunded: float = 0.0
    usage_source: str = "provider_reported"
    pricing_version: Optional[str] = None


class AIActionConfirmRequest(BaseModel):
    message_id: int
    confirm: bool = True


# ---------------------------------------------------------------------------
# Phase 9: AI Credits, Usage Metering, Quota Policies & Admin Diagnostics
# ---------------------------------------------------------------------------


class AICreditLimitsOut(BaseModel):
    rpm_limit: int
    daily_request_limit: int
    daily_token_limit: int
    max_credits_per_operation: float
    max_concurrent_requests: int
    max_context_turns: int
    max_document_mb: int


class AICreditAccountOut(BaseModel):
    business_id: int
    status: str
    plan_tier: str
    available_credits: float
    reserved_credits: float
    lifetime_granted_credits: float
    lifetime_consumed_credits: float
    lifetime_refunded_credits: float
    credits_enforced: bool
    limits: AICreditLimitsOut
    policy_override_reason: Optional[str] = None
    updated_at: Optional[str] = None


class AICreditTransactionOut(BaseModel):
    id: int
    transaction_uid: str
    business_id: int
    user_id: Optional[int] = None
    usage_log_id: Optional[int] = None
    request_id: Optional[str] = None
    idempotency_key: str
    transaction_type: str
    credit_change: float
    amount: float
    available_before: float
    available_after: float
    reserved_before: float
    reserved_after: float
    status: str
    operation_type: Optional[str] = None
    billing_reference: Optional[str] = None
    pricing_version: str
    reason: str
    created_at: Optional[str] = None


class AICreditTransactionsPageOut(BaseModel):
    items: List[AICreditTransactionOut]
    total: int
    limit: int
    offset: int


class AIUsageLogOut(BaseModel):
    id: int
    business_id: int
    user_id: Optional[int] = None
    document_id: Optional[int] = None
    conversation_id: Optional[int] = None
    provider: str
    operation_type: str
    processing_stage: Optional[str] = None
    model_name: Optional[str] = None
    prompt_tokens: int
    candidates_tokens: int
    total_tokens: int
    estimated_tokens: int
    embedding_inputs: Optional[int] = None
    credits_reserved: float
    credits_consumed: float
    credits_refunded: float
    usage_source: str
    pricing_version: str
    duration_ms: Optional[float] = None
    request_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    status: str
    error_code: Optional[str] = None
    error_category: Optional[str] = None
    created_at: datetime


class AIUsageLogsPageOut(BaseModel):
    items: List[AIUsageLogOut]
    total: int
    limit: int
    offset: int


class AIUsageSummaryOut(BaseModel):
    window_days: int
    account: AICreditAccountOut
    totals: Dict[str, Any]
    by_operation: List[Dict[str, Any]]
    by_model: List[Dict[str, Any]]
    daily_trends: List[Dict[str, Any]]


class AIAdminCreditAdjustRequest(BaseModel):
    credit_delta: float
    transaction_type: str = Field(
        ...,
        pattern="^(INITIAL_GRANT|PURCHASE|PROMOTIONAL_CREDIT|ADMIN_ADJUSTMENT|MANUAL_ADJUSTMENT|PLAN_ALLOCATION|EXPIRATION)$",
    )
    reason: str = Field(..., min_length=3, max_length=500)
    idempotency_key: str = Field(..., min_length=3, max_length=128)
    billing_reference: Optional[str] = Field(None, max_length=128)


class AIAdminCreditAdjustResponse(BaseModel):
    account: AICreditAccountOut
    transaction: AICreditTransactionOut


class AIAdminPolicyUpdateRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    status: Optional[str] = Field(None, pattern="^(ACTIVE|SUSPENDED)$")
    plan_tier: Optional[str] = Field(None, min_length=2, max_length=32)
    rpm_limit: Optional[int] = Field(None, ge=1, le=5000)
    daily_request_limit: Optional[int] = Field(None, ge=1, le=1000000)
    daily_token_limit: Optional[int] = Field(None, ge=100, le=100000000)
    max_credits_per_operation: Optional[float] = Field(None, gt=0, le=10000)
    max_concurrent_requests: Optional[int] = Field(None, ge=1, le=100)
    max_context_turns: Optional[int] = Field(None, ge=2, le=30)
    max_document_mb: Optional[int] = Field(None, ge=1, le=100)


class AIAdminFailuresOut(BaseModel):
    recent_failures: List[AIUsageLogOut]
    paused_documents: List[AIDocumentOut]
    circuit_breakers: Dict[str, Any]


class AIAdminRecoveryRequest(BaseModel):
    mode: str = Field("retry", pattern="^(retry|reindex)$")
    reason: str = Field("Administrator document ingestion recovery", min_length=3, max_length=500)
