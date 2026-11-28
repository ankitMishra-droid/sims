"""Authenticated, RBAC-enforced Phase 7/8 AI infrastructure, RAG documents & assistant routes."""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Dict, List, Optional
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session, sessionmaker

from ..core.ai_exceptions import AICreditError, AIErrorCode, AIServiceError
from ..core.ai_logging import get_ai_logger, log_ai_event
from ..core.ai_pricing import CostBreakdown, credits_float
from ..core.rate_limiter import rate_limit
from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_business_roles, require_permission
from ..models.ai_rag import AIDocument, AIDocumentChunk, AIMessage, AIUsageLog
from ..schemas.ai_schema import (
    AIActionConfirmRequest,
    AIAdminCreditAdjustRequest,
    AIAdminCreditAdjustResponse,
    AIAdminFailuresOut,
    AIAdminPolicyUpdateRequest,
    AIAdminRecoveryRequest,
    AIChatRequest,
    AIChatResponse,
    AIConversationCreateRequest,
    AIConversationDetailOut,
    AIConversationOut,
    AICreditAccountOut,
    AICreditTransactionOut,
    AICreditTransactionsPageOut,
    AIDocumentChunkOut,
    AIDocumentDetailResponse,
    AIDocumentOut,
    AIDocumentStatusOut,
    AIDocumentUploadResponse,
    AIHealthResponseOut,
    AIMessageOut,
    AIProbeRequest,
    AIUsageLogOut,
    AIUsageLogsPageOut,
    AIUsageSummaryOut,
    RetrievalEvidenceOut,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)
from ..services.ai.assistant_service import SIMSAssistantService
from ..services.ai.container import AIRuntimeContainer
from ..services.ai.conversation_service import ConversationService
from ..services.ai.credit_service import serialize_credit_account, serialize_credit_transaction
from ..services.ai.ingestion_service import DocumentIngestionService, run_background_ingestion
from ..services.ai.retrieval_service import TenantHybridRetrievalService

router = APIRouter(
    prefix="/api/ai",
    tags=["AI Infrastructure & Assistant"],
)

STATUS_ROLES = ["admin", "manager", "analyst", "staff"]
PROBE_ROLES = ["admin", "manager"]


def get_ai_container(request: Request) -> AIRuntimeContainer:
    """Resolve FastAPI lifespan AI container, initializing cleanly in test overrides."""
    container = getattr(request.app.state, "ai_container", None)
    if container is None:
        container = (
            getattr(request.app.state, "ai_container_override", None)
            or AIRuntimeContainer.from_env()
        )
        request.app.state.ai_container = container
    return container


def _to_http_exception(exc: AIServiceError) -> HTTPException:
    headers = (
        {"Retry-After": str(int(max(1, exc.retry_after_seconds)))}
        if exc.retry_after_seconds is not None
        else None
    )
    return HTTPException(
        status_code=exc.http_status or status.HTTP_502_BAD_GATEWAY,
        detail={
            "message": exc.safe_detail or exc.message,
            "error_code": exc.error_code.value,
            "retryable": exc.retryable,
            "retry_after_seconds": exc.retry_after_seconds,
            "conversation_id": getattr(exc, "conversation_id", None),
        },
        headers=headers,
    )


def _serialize_message(msg: AIMessage) -> AIMessageOut:
    return AIMessageOut(
        id=msg.id,
        conversation_id=msg.conversation_id,
        role=msg.role,
        content=msg.content,
        language=msg.language,
        sources=json.loads(msg.sources_json or "[]"),
        tool_calls=json.loads(msg.tool_calls_json or "[]"),
        pending_action=json.loads(msg.pending_action_json) if msg.pending_action_json else None,
        model_name=msg.model_name,
        prompt_tokens=msg.prompt_tokens,
        candidates_tokens=msg.candidates_tokens,
        total_tokens=msg.total_tokens,
        latency_ms=msg.latency_ms,
        status=msg.status,
        created_at=msg.created_at,
    )


def _serialize_document(doc: AIDocument) -> AIDocumentOut:
    base = AIDocumentOut.model_validate(doc)
    return base.model_copy(
        update={
            "credits_consumed": credits_float(doc.credits_consumed_units or 0),
            "credits_refunded": credits_float(doc.credits_refunded_units or 0),
            "total_tokens_used": int(doc.total_tokens_used or 0),
        }
    )


def _serialize_usage_log(log: AIUsageLog) -> AIUsageLogOut:
    return AIUsageLogOut(
        id=log.id,
        business_id=log.business_id,
        user_id=log.user_id,
        document_id=log.document_id,
        conversation_id=log.conversation_id,
        provider=log.provider or "gemini",
        operation_type=log.operation_type,
        processing_stage=log.processing_stage,
        model_name=log.model_name,
        prompt_tokens=int(log.prompt_tokens or 0),
        candidates_tokens=int(log.candidates_tokens or 0),
        total_tokens=int(log.total_tokens or 0),
        estimated_tokens=int(log.estimated_tokens or 0),
        embedding_inputs=log.embedding_inputs,
        credits_reserved=credits_float(log.credits_reserved_units or 0),
        credits_consumed=credits_float(log.credits_consumed_units or 0),
        credits_refunded=credits_float(log.credits_refunded_units or 0),
        usage_source=log.usage_source or "provider_reported",
        pricing_version=log.pricing_version or "2026-11-phase9-v1",
        duration_ms=log.duration_ms,
        request_id=log.request_id,
        idempotency_key=log.idempotency_key,
        status=log.status,
        error_code=log.error_code,
        error_category=log.error_category,
        created_at=log.created_at,
    )


# ---------------------------------------------------------------------------
# Phase 7 Health & Provider Connectivity
# ---------------------------------------------------------------------------


@router.get("/health", response_model=AIHealthResponseOut)
def get_ai_infrastructure_status(
    container: AIRuntimeContainer = Depends(get_ai_container),
    _ctx: BusinessContext = Depends(require_business_roles(STATUS_ROLES)),
) -> AIHealthResponseOut:
    """Return sanitized Gemini & Qdrant readiness without triggering billed API calls."""
    report = container.health_service.check_health(
        probe_qdrant=False,
        probe_gemini_embeddings=False,
        probe_gemini_llm=False,
    )
    return AIHealthResponseOut.model_validate(report)


@router.post(
    "/health/probe",
    response_model=AIHealthResponseOut,
    dependencies=[Depends(rate_limit("ai_probe", default_max=20, window_seconds=60))],
)
def probe_ai_infrastructure_connectivity(
    payload: AIProbeRequest,
    container: AIRuntimeContainer = Depends(get_ai_container),
    _ctx: BusinessContext = Depends(require_business_roles(PROBE_ROLES)),
) -> AIHealthResponseOut:
    """Execute explicit live connectivity & schema verification checks for AI providers."""
    report = container.health_service.check_health(
        probe_qdrant=payload.probe_qdrant,
        probe_gemini_embeddings=payload.probe_gemini_embeddings,
        probe_gemini_llm=payload.probe_gemini_llm,
    )
    return AIHealthResponseOut.model_validate(report)


# ---------------------------------------------------------------------------
# Phase 8 RAG Document Ingestion & Lifecycle
# ---------------------------------------------------------------------------


@router.post(
    "/documents",
    response_model=AIDocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("ai_doc_upload", default_max=25, window_seconds=60))],
)
async def upload_rag_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    doc_category: str = Form("general"),
    replace_duplicate: bool = Form(False),
    async_process: bool = Form(True),
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.documents.write")),
) -> AIDocumentUploadResponse:
    """Validate, deduplicate, stage, and queue/process a tenant-scoped business document."""
    svc = DocumentIngestionService(container)
    try:
        account = container.credit_service.ensure_credit_account(
            db, business_id=ctx.business_id, user_id=ctx.user.id
        )
        max_doc_bytes = (
            account.max_document_mb or container.settings.ai_max_document_mb
        ) * 1024 * 1024
        chunks: List[bytes] = []
        total_read = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > max_doc_bytes:
                raise HTTPException(
                    status_code=413,
                    detail={
                        "message": f"Document exceeds workspace upload limit of {account.max_document_mb or container.settings.ai_max_document_mb} MB.",
                        "error_code": "INVALID_REQUEST",
                        "retryable": False,
                    },
                )
            chunks.append(chunk)
        raw_bytes = b"".join(chunks)
        min_doc_units = container.pricing.estimate_embedding_batch_reserve_units(
            model_name=container.settings.gemini_embedding_model,
            texts=["document ingestion"],
            include_chunk_fee=True,
        )
        container.credit_service.check_tenant_policies(
            db, account=account, estimated_reserve_units=min_doc_units
        )
        if container.settings.ai_credits_enforced and account.available_units < min_doc_units:
            raise AICreditError(
                f"Insufficient AI credits ({credits_float(account.available_units)} available) to ingest documents.",
                error_code=AIErrorCode.INSUFFICIENT_AI_CREDITS,
                http_status=402,
            )
        doc, is_dup = svc.upload_document(
            db,
            business_id=ctx.business_id,
            user_id=ctx.user.id,
            filename=file.filename,
            raw_bytes=raw_bytes,
            mime_type=file.content_type,
            title=title,
            doc_category=doc_category,
            replace_duplicate=replace_duplicate,
        )
    except AIServiceError as exc:
        raise _to_http_exception(exc) from exc

    if is_dup:
        return AIDocumentUploadResponse(
            document=_serialize_document(doc),
            duplicate_detected=True,
            message="Identical document content already exists in workspace.",
        )

    if async_process:
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=db.get_bind())
        background_tasks.add_task(
            run_background_ingestion,
            session_factory,
            container,
            doc_id=doc.id,
            business_id=ctx.business_id,
        )
        msg = "Document uploaded and queued for ingestion."
    else:
        doc = svc.process_document(db, doc_id=doc.id, business_id=ctx.business_id)
        msg = f"Document ingestion finished with status {doc.status}."

    return AIDocumentUploadResponse(
        document=_serialize_document(doc),
        duplicate_detected=False,
        message=msg,
    )


@router.get("/documents", response_model=List[AIDocumentOut])
def list_rag_documents(
    status_filter: Annotated[Optional[str], Query(alias="status")] = None,
    file_type: Annotated[Optional[str], Query()] = None,
    language: Annotated[Optional[str], Query()] = None,
    search: Annotated[Optional[str], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_permission("ai.documents.read")),
) -> List[AIDocumentOut]:
    q = db.query(AIDocument).filter(
        AIDocument.business_id == ctx.business_id,
        AIDocument.status != "DELETED",
        AIDocument.deleted_at.is_(None),
    )
    if status_filter:
        q = q.filter(AIDocument.status == status_filter.strip().upper())
    if file_type:
        q = q.filter(AIDocument.file_type == file_type.strip().lower())
    if language:
        q = q.filter(AIDocument.detected_language == language.strip().lower())
    if search and search.strip():
        pat = f"%{search.strip()}%"
        q = q.filter((AIDocument.title.ilike(pat)) | (AIDocument.filename.ilike(pat)))

    docs = q.order_by(AIDocument.created_at.desc(), AIDocument.id.desc()).offset(offset).limit(limit).all()
    return [_serialize_document(d) for d in docs]


@router.get("/documents/{doc_id}", response_model=AIDocumentDetailResponse)
def get_rag_document_detail(
    doc_id: int,
    chunk_limit: Annotated[int, Query(ge=1, le=200)] = 50,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_permission("ai.documents.read")),
) -> AIDocumentDetailResponse:
    doc = (
        db.query(AIDocument)
        .filter(
            AIDocument.id == doc_id,
            AIDocument.business_id == ctx.business_id,
            AIDocument.status != "DELETED",
            AIDocument.deleted_at.is_(None),
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found in workspace.")
    chunks = (
        db.query(AIDocumentChunk)
        .filter(
            AIDocumentChunk.document_id == doc.id,
            AIDocumentChunk.business_id == ctx.business_id,
        )
        .order_by(AIDocumentChunk.chunk_index.asc())
        .limit(chunk_limit)
        .all()
    )
    return AIDocumentDetailResponse(
        document=_serialize_document(doc),
        chunks=[AIDocumentChunkOut.model_validate(c) for c in chunks],
    )


@router.get("/documents/{doc_id}/status", response_model=AIDocumentStatusOut)
def get_rag_document_status(
    doc_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_permission("ai.documents.read")),
) -> AIDocumentStatusOut:
    doc = (
        db.query(AIDocument)
        .filter(
            AIDocument.id == doc_id,
            AIDocument.business_id == ctx.business_id,
            AIDocument.status != "DELETED",
            AIDocument.deleted_at.is_(None),
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found in workspace.")

    progress = 100.0 if doc.status == "COMPLETED" else (
        round((doc.indexed_chunks / doc.total_chunks) * 100.0, 1) if doc.total_chunks > 0 else 0.0
    )
    return AIDocumentStatusOut(
        id=doc.id,
        status=doc.status,
        current_stage=doc.current_stage,
        last_checkpoint_stage=doc.last_checkpoint_stage,
        job_id=doc.job_id,
        total_pages=doc.total_pages,
        total_chunks=doc.total_chunks,
        processed_chunks=doc.processed_chunks,
        embedded_chunks=doc.embedded_chunks,
        indexed_chunks=doc.indexed_chunks,
        failed_chunks=doc.failed_chunks,
        ocr_required=doc.ocr_required,
        ocr_status=doc.ocr_status,
        error_code=doc.error_code,
        error_message=doc.error_message,
        last_error_category=doc.last_error_category,
        next_retry_at=doc.next_retry_at,
        retryable=doc.retryable,
        credits_consumed=credits_float(doc.credits_consumed_units or 0),
        credits_refunded=credits_float(doc.credits_refunded_units or 0),
        total_tokens_used=int(doc.total_tokens_used or 0),
        progress_percent=progress,
    )


@router.post("/documents/{doc_id}/retry", response_model=AIDocumentOut)
def retry_rag_document(
    doc_id: int,
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.documents.write")),
) -> AIDocumentOut:
    svc = DocumentIngestionService(container)
    try:
        doc = svc.retry_document(db, doc_id=doc_id, business_id=ctx.business_id)
        return _serialize_document(doc)
    except AIServiceError as exc:
        raise _to_http_exception(exc) from exc


@router.post("/documents/{doc_id}/reindex", response_model=AIDocumentOut)
def reindex_rag_document(
    doc_id: int,
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.documents.write")),
) -> AIDocumentOut:
    svc = DocumentIngestionService(container)
    try:
        doc = svc.reindex_document(db, doc_id=doc_id, business_id=ctx.business_id)
        return _serialize_document(doc)
    except AIServiceError as exc:
        raise _to_http_exception(exc) from exc


@router.post("/documents/{doc_id}/cancel", response_model=AIDocumentOut)
def cancel_rag_document(
    doc_id: int,
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.documents.write")),
) -> AIDocumentOut:
    svc = DocumentIngestionService(container)
    try:
        doc = svc.cancel_document(db, doc_id=doc_id, business_id=ctx.business_id)
        return _serialize_document(doc)
    except AIServiceError as exc:
        raise _to_http_exception(exc) from exc


@router.delete("/documents/{doc_id}")
def delete_rag_document(
    doc_id: int,
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.documents.write")),
) -> Dict[str, Any]:
    svc = DocumentIngestionService(container)
    try:
        return svc.delete_document(db, doc_id=doc_id, business_id=ctx.business_id)
    except AIServiceError as exc:
        raise _to_http_exception(exc) from exc


# ---------------------------------------------------------------------------
# Phase 8 Hybrid Retrieval & Evaluation Diagnostic Route
# ---------------------------------------------------------------------------


@router.post("/retrieve", response_model=RetrievalSearchResponse)
def retrieve_workspace_knowledge(
    payload: RetrievalSearchRequest,
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.documents.read")),
) -> RetrievalSearchResponse:
    retrieval = TenantHybridRetrievalService(container)
    req_id = str(uuid4())
    reserve_units = container.pricing.estimate_embedding_batch_reserve_units(
        model_name=container.settings.gemini_embedding_model,
        texts=[payload.query],
        include_chunk_fee=False,
    )
    reservation = None
    try:
        reservation = container.credit_service.reserve_credits(
            db,
            business_id=ctx.business_id,
            user_id=ctx.user.id,
            operation_type="query_embed",
            model_name=container.settings.gemini_embedding_model,
            estimated_reserve_units=reserve_units,
            request_id=req_id,
            processing_stage="RETRIEVAL",
            reason="Knowledge base search query",
        )
        res = retrieval.retrieve(
            db,
            business_id=ctx.business_id,
            query=payload.query,
            top_k=payload.top_k,
            min_score=payload.min_score,
            language=payload.language,
            doc_category=payload.doc_category,
            document_ids=payload.document_ids,
            request_id=req_id,
        )
    except AIServiceError as exc:
        if reservation is not None:
            container.credit_service.refund_failed_reservation(
                db,
                reservation=reservation,
                error_code=exc.error_code.value,
                error_category="transient" if exc.retryable else "client",
                duration_ms=0.0,
                user_id=ctx.user.id,
                reason="Refund after failed retrieval search",
            )
        raise _to_http_exception(exc) from exc

    if res.metadata.get("embed_executed"):
        breakdown = container.pricing.calculate_embedding_batch_cost(
            model_name=res.query_embed_model or container.settings.gemini_embedding_model,
            texts=[res.query_analysis.focused_query],
            actual_tokens=res.query_embed_tokens,
            include_chunk_fee=False,
            operation_type="query_embed",
        )
        container.credit_service.capture_usage(
            db,
            reservation=reservation,
            breakdown=breakdown,
            duration_ms=res.latency_ms,
            user_id=ctx.user.id,
            provider_metadata={"semantic_used": res.semantic_used, "lexical_used": res.lexical_used},
        )
    else:
        # No Gemini embedding API call executed (lexical-only or zero documents) -> 100% credit refund
        container.credit_service.refund_failed_reservation(
            db,
            reservation=reservation,
            error_code="NOT_BILLED_LEXICAL_ONLY",
            error_category="none",
            duration_ms=res.latency_ms,
            user_id=ctx.user.id,
            reason="Zero Gemini embedding call executed (lexical-only retrieval)",
        )
    return RetrievalSearchResponse(
        request_id=res.request_id,
        detected_language=res.query_analysis.detected_language,
        focused_query=res.query_analysis.focused_query,
        exact_identifiers=res.query_analysis.exact_identifiers,
        semantic_used=res.semantic_used,
        lexical_used=res.lexical_used,
        vector_error_code=res.vector_error_code,
        latency_ms=res.latency_ms,
        evidence=[
            RetrievalEvidenceOut(
                document_id=ev.document_id,
                document_title=ev.document_title,
                filename=ev.filename,
                file_type=ev.file_type,
                doc_category=ev.doc_category,
                document_version=ev.document_version,
                chunk_id=ev.chunk_id,
                chunk_index=ev.chunk_index,
                page_number=ev.page_number,
                section_heading=ev.section_heading,
                sheet_name=ev.sheet_name,
                language=ev.language,
                excerpt=ev.excerpt,
                vector_score=ev.vector_score,
                lexical_score=ev.lexical_score,
                combined_score=ev.combined_score,
                match_reason=ev.match_reason,
            )
            for ev in res.evidence
        ],
    )


# ---------------------------------------------------------------------------
# Phase 8 Multilingual AI Assistant & Conversation Persistence
# ---------------------------------------------------------------------------


@router.post("/conversations", response_model=AIConversationOut, status_code=status.HTTP_201_CREATED)
def create_ai_conversation(
    payload: AIConversationCreateRequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_permission("ai.chat")),
) -> AIConversationOut:
    conv = ConversationService.create_conversation(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        title=payload.title,
        preferred_language=payload.preferred_language,
        page_context=payload.page_context,
    )
    return AIConversationOut.model_validate(conv)


@router.get("/conversations", response_model=List[AIConversationOut])
def list_ai_conversations(
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_permission("ai.chat")),
) -> List[AIConversationOut]:
    rows = ConversationService.list_conversations(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        limit=limit,
        offset=offset,
    )
    return [AIConversationOut.model_validate(c) for c in rows]


@router.get("/conversations/{conv_id}", response_model=AIConversationDetailOut)
def get_ai_conversation_detail(
    conv_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_permission("ai.chat")),
) -> AIConversationDetailOut:
    try:
        conv, messages = ConversationService.get_conversation_with_messages(
            db,
            conv_id=conv_id,
            business_id=ctx.business_id,
            user_id=ctx.user.id,
        )
    except AIServiceError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return AIConversationDetailOut(
        conversation=AIConversationOut.model_validate(conv),
        messages=[_serialize_message(m) for m in messages],
    )


@router.delete("/conversations/{conv_id}")
def delete_ai_conversation(
    conv_id: int,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_permission("ai.chat")),
) -> Dict[str, Any]:
    try:
        return ConversationService.delete_conversation(
            db,
            conv_id=conv_id,
            business_id=ctx.business_id,
            user_id=ctx.user.id,
        )
    except AIServiceError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.post(
    "/chat",
    response_model=AIChatResponse,
    dependencies=[Depends(rate_limit("ai_chat", default_max=30, window_seconds=60))],
)
def chat_with_sims_assistant(
    payload: AIChatRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.chat")),
) -> AIChatResponse:
    assistant = SIMSAssistantService(container)
    resolved_idem = (idempotency_key or payload.idempotency_key or "").strip() or None
    try:
        result = assistant.chat(
            db,
            ctx,
            message=payload.message,
            conversation_id=payload.conversation_id,
            preferred_language=payload.preferred_language,
            page_context=payload.page_context,
            idempotency_key=resolved_idem,
        )
    except AIServiceError as exc:
        raise _to_http_exception(exc) from exc

    return AIChatResponse(
        conversation=AIConversationOut.model_validate(result["conversation"]),
        message=_serialize_message(result["assistant_message"]),
        citations=result["citations"],
        tools_used=result["tools_used"],
        pending_action=result["pending_action"],
        response_language=result["response_language"],
        request_id=result["request_id"],
        idempotent_replay=bool(result.get("idempotent_replay", False)),
        credits_used=float(result.get("credits_used", 0.0)),
        credits_reserved=float(result.get("credits_reserved", 0.0)),
        credits_refunded=float(result.get("credits_refunded", 0.0)),
        usage_source=str(result.get("usage_source", "provider_reported")),
        pricing_version=result.get("pricing_version"),
    )


@router.post("/conversations/{conv_id}/actions/confirm")
def confirm_ai_assistant_action(
    conv_id: int,
    payload: AIActionConfirmRequest,
    db: Session = Depends(get_db),
    ctx: BusinessContext = Depends(require_permission("ai.chat")),
) -> Dict[str, Any]:
    try:
        return SIMSAssistantService.confirm_pending_action(
            db,
            ctx,
            conv_id=conv_id,
            message_id=payload.message_id,
            confirm=payload.confirm,
        )
    except AIServiceError as exc:
        raise _to_http_exception(exc) from exc


# ---------------------------------------------------------------------------
# Phase 9: Tenant Credits, Usage Analytics, Pricing & Admin Governance
# ---------------------------------------------------------------------------


@router.get("/credits/balance", response_model=AICreditAccountOut)
def get_workspace_ai_credit_balance(
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.credits.read")),
) -> AICreditAccountOut:
    """Return authoritative persistent credit balance & active limits for current tenant."""
    account = container.credit_service.ensure_credit_account(
        db, business_id=ctx.business_id, user_id=ctx.user.id
    )
    return AICreditAccountOut.model_validate(
        serialize_credit_account(account, container.settings)
    )


@router.get("/credits/pricing")
def get_workspace_ai_pricing_schedule(
    container: AIRuntimeContainer = Depends(get_ai_container),
    _ctx: BusinessContext = Depends(require_permission("ai.credits.read")),
) -> Dict[str, Any]:
    """Return active versioned pricing rates and commercial approval flag."""
    return container.pricing.to_public_dict()


@router.get("/credits/transactions", response_model=AICreditTransactionsPageOut)
def list_workspace_credit_transactions(
    transaction_type: Annotated[Optional[str], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.credits.read")),
) -> AICreditTransactionsPageOut:
    rows, total = container.credit_service.list_transactions(
        db,
        business_id=ctx.business_id,
        transaction_type=transaction_type,
        limit=limit,
        offset=offset,
    )
    return AICreditTransactionsPageOut(
        items=[AICreditTransactionOut.model_validate(serialize_credit_transaction(tx)) for tx in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/usage/summary", response_model=AIUsageSummaryOut)
def get_workspace_ai_usage_summary(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.usage.read")),
) -> AIUsageSummaryOut:
    summary = container.credit_service.get_usage_summary(
        db,
        business_id=ctx.business_id,
        days=days,
    )
    return AIUsageSummaryOut.model_validate(summary)


@router.get("/usage/logs", response_model=AIUsageLogsPageOut)
def list_workspace_ai_usage_logs(
    status_filter: Annotated[Optional[str], Query(alias="status")] = None,
    operation_type: Annotated[Optional[str], Query()] = None,
    error_category: Annotated[Optional[str], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.usage.read")),
) -> AIUsageLogsPageOut:
    rows, total = container.credit_service.list_usage_logs(
        db,
        business_id=ctx.business_id,
        status_filter=status_filter,
        operation_type=operation_type,
        error_category=error_category,
        limit=limit,
        offset=offset,
    )
    return AIUsageLogsPageOut(
        items=[_serialize_usage_log(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/admin/credits/adjust", response_model=AIAdminCreditAdjustResponse)
def admin_adjust_workspace_ai_credits(
    payload: AIAdminCreditAdjustRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.credits.manage")),
) -> AIAdminCreditAdjustResponse:
    """Authorized admin/owner adjustment of workspace AI credits with immutable ledger audit."""
    resolved_idem = (idempotency_key or payload.idempotency_key).strip()
    try:
        account, tx = container.credit_service.admin_adjust_credits(
            db,
            business_id=ctx.business_id,
            admin_user_id=ctx.user.id,
            credit_delta=payload.credit_delta,
            transaction_type=payload.transaction_type,
            reason=payload.reason,
            idempotency_key=resolved_idem,
            billing_reference=payload.billing_reference,
        )
    except AIServiceError as exc:
        raise _to_http_exception(exc) from exc

    log_ai_event(
        get_ai_logger("billing"),
        logging.INFO,
        provider="billing",
        operation="admin_credit_adjust",
        status="ok",
        tenant_id=ctx.business_id,
        user_id=ctx.user.id,
        transaction_type=tx.transaction_type,
        credit_delta=payload.credit_delta,
    )
    return AIAdminCreditAdjustResponse(
        account=AICreditAccountOut.model_validate(
            serialize_credit_account(account, container.settings)
        ),
        transaction=AICreditTransactionOut.model_validate(serialize_credit_transaction(tx)),
    )


@router.put("/admin/policies", response_model=AICreditAccountOut)
def admin_update_workspace_ai_policies(
    payload: AIAdminPolicyUpdateRequest,
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.credits.manage")),
) -> AICreditAccountOut:
    """Authorized admin/owner update of workspace quota limits, tier, or AI suspension status."""
    try:
        account = container.credit_service.update_tenant_policy(
            db,
            business_id=ctx.business_id,
            admin_user_id=ctx.user.id,
            reason=payload.reason,
            status=payload.status,
            plan_tier=payload.plan_tier,
            rpm_limit=payload.rpm_limit,
            daily_request_limit=payload.daily_request_limit,
            daily_token_limit=payload.daily_token_limit,
            max_credits_per_operation=payload.max_credits_per_operation,
            max_concurrent_requests=payload.max_concurrent_requests,
            max_context_turns=payload.max_context_turns,
            max_document_mb=payload.max_document_mb,
        )
    except AIServiceError as exc:
        raise _to_http_exception(exc) from exc

    return AICreditAccountOut.model_validate(
        serialize_credit_account(account, container.settings)
    )


@router.get("/admin/failures", response_model=AIAdminFailuresOut)
def admin_inspect_workspace_ai_failures(
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.credits.manage")),
) -> AIAdminFailuresOut:
    """Return tenant-scoped recent AI error logs, paused ingestion docs, and circuit breaker state."""
    fail_rows, _ = container.credit_service.list_usage_logs(
        db,
        business_id=ctx.business_id,
        status_filter="error",
        limit=50,
        offset=0,
    )
    paused_docs = (
        db.query(AIDocument)
        .filter(
            AIDocument.business_id == ctx.business_id,
            AIDocument.status.in_(
                ("FAILED", "QUOTA_PAUSED", "PAUSED_QUOTA", "PAUSED_RETRYABLE", "PARTIALLY_COMPLETED")
            ),
            AIDocument.deleted_at.is_(None),
        )
        .order_by(AIDocument.updated_at.desc(), AIDocument.id.desc())
        .limit(50)
        .all()
    )
    return AIAdminFailuresOut(
        recent_failures=[_serialize_usage_log(r) for r in fail_rows],
        paused_documents=[_serialize_document(d) for d in paused_docs],
        circuit_breakers=container.circuit_breaker.snapshot_all(),
    )


@router.post("/admin/ingestion/{doc_id}/recover", response_model=AIDocumentOut)
def admin_recover_document_ingestion(
    doc_id: int,
    payload: AIAdminRecoveryRequest,
    db: Session = Depends(get_db),
    container: AIRuntimeContainer = Depends(get_ai_container),
    ctx: BusinessContext = Depends(require_permission("ai.credits.manage")),
) -> AIDocumentOut:
    """Authorized admin recovery endpoint to safely resume checkpointed ingestion or full-reindex."""
    svc = DocumentIngestionService(container)
    try:
        if payload.mode == "reindex":
            doc = svc.reindex_document(db, doc_id=doc_id, business_id=ctx.business_id)
        else:
            doc = svc.retry_document(db, doc_id=doc_id, business_id=ctx.business_id)
    except AIServiceError as exc:
        raise _to_http_exception(exc) from exc

    log_ai_event(
        get_ai_logger("ingestion"),
        logging.INFO,
        provider="ingestion",
        operation="admin_recover_document",
        status="ok",
        tenant_id=ctx.business_id,
        user_id=ctx.user.id,
        document_id=doc.id,
        mode=payload.mode,
    )
    return _serialize_document(doc)
