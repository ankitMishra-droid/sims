"""Checkpointed, resumable, tenant-scoped RAG document ingestion & lifecycle service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional, Sequence
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from ...core.ai_exceptions import AIErrorCode, AIInvalidRequestError, AIServiceError
from ...core.ai_logging import get_ai_logger, log_ai_event, redact_sensitive_text
from ...models.ai_rag import AIDocument, AIDocumentChunk, AIUsageLog
from .container import AIRuntimeContainer
from .document_chunking import ChunkDraft, chunk_extracted_segments
from .document_extraction import extract_document_content
from .document_validation import (
    remove_staged_file,
    save_staged_document,
    validate_uploaded_document,
)
from .language_detection import detect_language
from .qdrant_service import VectorDocumentRecord, compute_deterministic_point_id

_TERMINAL_OR_ACTIVE_RETRY_ALLOWED = {
    "FAILED",
    "QUOTA_PAUSED",
    "PAUSED_QUOTA",
    "PAUSED_RETRYABLE",
    "PARTIALLY_COMPLETED",
    "CANCELLED",
    "VALIDATING",
}


def _classify_ingestion_error(exc: AIServiceError) -> str:
    code = exc.error_code
    if code == AIErrorCode.INSUFFICIENT_AI_CREDITS:
        return "credits"
    if code == AIErrorCode.TENANT_QUOTA_EXCEEDED:
        return "tenant_quota"
    if code == AIErrorCode.QUOTA_EXHAUSTED:
        return "quota"
    if code == AIErrorCode.RATE_LIMIT_RETRYABLE:
        return "rate_limit"
    if code == AIErrorCode.CIRCUIT_OPEN:
        return "circuit_open"
    if code == AIErrorCode.COLLECTION_MISMATCH:
        return "schema_mismatch"
    if code == AIErrorCode.TIMEOUT_ERROR:
        return "timeout"
    if exc.retryable:
        return "transient"
    return "client"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DocumentIngestionService:
    """Manages document staging, resumable chunked indexing, retry, cancel, reindex, and deletion."""

    def __init__(
        self,
        container: AIRuntimeContainer,
        *,
        batch_size: int = 16,
    ) -> None:
        self._container = container
        self._settings = container.settings
        self._batch_size = max(1, min(batch_size, 64))
        self._logger = get_ai_logger("ingestion")

    @staticmethod
    def _require_tenant_document(db: Session, *, doc_id: int, business_id: int) -> AIDocument:
        doc = (
            db.query(AIDocument)
            .filter(
                AIDocument.id == doc_id,
                AIDocument.business_id == business_id,
                AIDocument.status != "DELETED",
                AIDocument.deleted_at.is_(None),
            )
            .first()
        )
        if not doc:
            raise AIInvalidRequestError("Document not found in workspace.", provider="ingestion")
        return doc

    def _record_usage(
        self,
        db: Session,
        *,
        doc: AIDocument,
        operation_type: str,
        stage: str,
        status: str,
        request_id: str,
        embedding_inputs: Optional[int] = None,
        duration_ms: Optional[float] = None,
        error_code: Optional[str] = None,
    ) -> None:
        log_row = AIUsageLog(
            business_id=doc.business_id,
            user_id=doc.uploaded_by_user_id,
            document_id=doc.id,
            operation_type=operation_type,
            processing_stage=stage,
            model_name=doc.embedding_model,
            embedding_inputs=embedding_inputs,
            duration_ms=duration_ms,
            request_id=request_id,
            status=status,
            error_code=error_code,
        )
        db.add(log_row)

    def upload_document(
        self,
        db: Session,
        *,
        business_id: int,
        user_id: int,
        filename: Optional[str],
        raw_bytes: bytes,
        mime_type: Optional[str],
        title: Optional[str] = None,
        doc_category: str = "general",
        replace_duplicate: bool = False,
    ) -> tuple[AIDocument, bool]:
        """Validate upload bytes, check workspace duplicates, stage bytes cleanly, and persist AIDocument."""
        validated = validate_uploaded_document(
            filename=filename,
            raw_bytes=raw_bytes,
            claimed_mime_type=mime_type,
            settings=self._settings,
            title=title,
        )

        # Duplicate detection by workspace + content hash
        existing = (
            db.query(AIDocument)
            .filter(
                AIDocument.business_id == business_id,
                AIDocument.content_hash == validated.content_hash,
                AIDocument.status != "DELETED",
                AIDocument.deleted_at.is_(None),
            )
            .order_by(AIDocument.id.desc())
            .first()
        )
        if existing and not replace_duplicate:
            return existing, True

        version_num = 1
        same_title_latest = (
            db.query(func.max(AIDocument.document_version))
            .filter(
                AIDocument.business_id == business_id,
                AIDocument.filename == validated.filename,
                AIDocument.status != "DELETED",
            )
            .scalar()
        )
        if same_title_latest:
            version_num = int(same_title_latest) + 1

        staged_path = save_staged_document(
            upload_dir=getattr(self._settings, "ai_upload_dir", "./ai_uploads"),
            business_id=business_id,
            document_uuid=str(uuid4()),
            filename=validated.filename,
            raw_bytes=validated.raw_bytes,
        )

        clean_cat = (doc_category or "general").strip().lower()
        if clean_cat not in ("general", "faq", "table", "catalog", "manual", "policy"):
            clean_cat = "general"

        doc = AIDocument(
            business_id=business_id,
            uploaded_by_user_id=user_id,
            filename=validated.filename,
            title=validated.title,
            file_type=validated.file_type,
            mime_type=validated.mime_type,
            file_size_bytes=validated.file_size_bytes,
            content_hash=validated.content_hash,
            storage_path=staged_path,
            doc_category=clean_cat,
            detected_language="en",
            language_confidence=1.0,
            document_version=version_num,
            version_label=f"v{version_num}",
            status="PENDING",
            current_stage="UPLOADED",
            last_checkpoint_stage="UPLOADED",
            job_id=f"ing-{uuid4().hex[:12]}",
            total_pages=validated.total_pages,
            embedding_model=self._settings.gemini_embedding_model,
            embedding_version=self._settings.gemini_embedding_version,
            embedding_dimensions=self._settings.gemini_embedding_dimensions,
        )
        db.add(doc)
        try:
            db.commit()
        except Exception:
            db.rollback()
            remove_staged_file(staged_path)
            raise
        db.refresh(doc)
        return doc, False

    def process_document(
        self,
        db: Session,
        *,
        doc_id: int,
        business_id: int,
        request_id: Optional[str] = None,
    ) -> AIDocument:
        """Execute resumable extraction -> chunking -> embedding -> Qdrant indexing pipeline."""
        req_id = request_id or str(uuid4())
        started = time.perf_counter()
        doc = self._require_tenant_document(db, doc_id=doc_id, business_id=business_id)

        if doc.status == "COMPLETED" and doc.indexed_chunks == doc.total_chunks and doc.total_chunks > 0:
            return doc

        if doc.cancel_requested or doc.status == "CANCELLED":
            doc.status = "CANCELLED"
            doc.current_stage = "CANCELLED"
            db.commit()
            return doc

        doc.job_id = doc.job_id or f"ing-{uuid4().hex[:12]}"
        doc.last_request_id = req_id
        doc.error_code = None
        doc.error_message = None
        doc.last_error_category = None
        doc.next_retry_at = None
        doc.retryable = False
        db.commit()

        batch_usage_settled = False
        try:
            # Stage 1-4: Extract, normalize, detect language & chunk ONLY if chunks are not yet persisted
            existing_chunks = (
                db.query(AIDocumentChunk)
                .filter(AIDocumentChunk.document_id == doc.id, AIDocumentChunk.business_id == business_id)
                .order_by(AIDocumentChunk.chunk_index.asc())
                .all()
            )
            if existing_chunks and (
                doc.embedding_model != self._settings.gemini_embedding_model
                or doc.embedding_dimensions != self._settings.gemini_embedding_dimensions
            ):
                raise AIInvalidRequestError(
                    (
                        f"Existing chunks use {doc.embedding_model} ({doc.embedding_dimensions} dims), "
                        f"incompatible with active configuration {self._settings.gemini_embedding_model} "
                        f"({self._settings.gemini_embedding_dimensions} dims). Trigger reindex instead of resume."
                    ),
                    provider="ingestion",
                    error_code=AIErrorCode.COLLECTION_MISMATCH,
                )

            if not existing_chunks:
                doc.status = "VALIDATING"
                doc.current_stage = "VALIDATING"
                db.commit()
                if not doc.storage_path or not Path(doc.storage_path).exists():
                    raise AIInvalidRequestError(
                        "Staged source file is missing; please re-upload the document.",
                        provider="ingestion",
                    )
                raw_bytes = Path(doc.storage_path).read_bytes()

                doc.status = "EXTRACTING"
                doc.current_stage = "EXTRACTING"
                db.commit()

                try:
                    extracted = extract_document_content(doc.file_type, raw_bytes)
                except AIInvalidRequestError as ext_err:
                    msg_lower = ext_err.message.lower()
                    if "scanned" in msg_lower or "image-based" in msg_lower:
                        doc.ocr_required = True
                        doc.ocr_status = "unsupported_scanned_pdf"
                        db.commit()
                    raise

                doc.total_pages = extracted.total_pages or doc.total_pages
                doc.ocr_required = extracted.ocr_required
                doc.ocr_status = extracted.ocr_status
                doc.status = "NORMALIZING"
                doc.current_stage = "NORMALIZING"
                doc.last_checkpoint_stage = "EXTRACTED"

                sample_text = "\n".join(seg.text for seg in extracted.segments[:8])[:6000]
                lang_res = detect_language(sample_text)
                doc.detected_language = lang_res.language
                doc.language_confidence = lang_res.confidence
                meta = dict(extracted.metadata or {})
                meta["script"] = lang_res.script
                doc.metadata_json = json.dumps(meta)
                db.commit()

                doc.status = "CHUNKING"
                doc.current_stage = "CHUNKING"
                db.commit()

                drafts: List[ChunkDraft] = chunk_extracted_segments(
                    extracted.segments,
                    file_type=doc.file_type,
                    doc_category=doc.doc_category,
                    chunk_size=getattr(self._settings, "ai_chunk_size_chars", 900),
                    chunk_overlap=getattr(self._settings, "ai_chunk_overlap_chars", 120),
                )
                if not drafts:
                    raise AIInvalidRequestError(
                        "Document produced zero meaningful text chunks after normalization.",
                        provider="ingestion",
                    )

                for d in drafts:
                    point_id = compute_deterministic_point_id(
                        tenant_id=business_id,
                        document_id=str(doc.id),
                        document_version=doc.version_label,
                        chunk_id=d.chunk_uid,
                    )
                    db.add(
                        AIDocumentChunk(
                            business_id=business_id,
                            document_id=doc.id,
                            chunk_index=d.chunk_index,
                            chunk_uid=d.chunk_uid,
                            qdrant_point_id=point_id,
                            text=d.text,
                            content_hash=d.content_hash,
                            page_number=d.page_number,
                            section_heading=d.section_heading,
                            sheet_name=d.sheet_name,
                            language=d.language,
                            char_count=d.char_count,
                            token_estimate=d.token_estimate,
                            chunk_strategy=d.chunk_strategy,
                            embedding_status="PENDING",
                        )
                    )
                doc.total_chunks = len(drafts)
                doc.processed_chunks = len(drafts)
                doc.last_checkpoint_stage = "CHUNKED"
                db.commit()

                existing_chunks = (
                    db.query(AIDocumentChunk)
                    .filter(
                        AIDocumentChunk.document_id == doc.id,
                        AIDocumentChunk.business_id == business_id,
                    )
                    .order_by(AIDocumentChunk.chunk_index.asc())
                    .all()
                )

            # Stage 5-6: Resumable batched embedding + Qdrant indexing for remaining unindexed chunks
            pending_chunks = [c for c in existing_chunks if c.embedding_status != "INDEXED"]
            if pending_chunks:
                doc.status = "EMBEDDING"
                doc.current_stage = "EMBEDDING"
                db.commit()

                for start in range(0, len(pending_chunks), self._batch_size):
                    db.refresh(doc)
                    if doc.cancel_requested or doc.status == "CANCELLED":
                        indexed_now = sum(1 for c in existing_chunks if c.embedding_status == "INDEXED")
                        doc.indexed_chunks = indexed_now
                        doc.embedded_chunks = indexed_now
                        doc.status = "CANCELLED"
                        doc.current_stage = "CANCELLED"
                        db.commit()
                        return doc

                    batch = pending_chunks[start : start + self._batch_size]
                    texts = [c.text for c in batch]
                    batch_idem = (
                        f"ingest:{doc.id}:v{doc.document_version}:"
                        f"c{batch[0].chunk_uid}:{batch[-1].chunk_uid}"
                    )
                    batch_req_id = f"{req_id}:b{batch[0].chunk_index}"
                    batch_reserve_units = self._container.pricing.estimate_embedding_batch_reserve_units(
                        model_name=self._settings.gemini_embedding_model,
                        texts=texts,
                        include_chunk_fee=True,
                    )
                    reservation = self._container.credit_service.reserve_credits(
                        db,
                        business_id=business_id,
                        user_id=doc.uploaded_by_user_id,
                        operation_type="ingestion_embed",
                        model_name=self._settings.gemini_embedding_model,
                        estimated_reserve_units=batch_reserve_units,
                        request_id=batch_req_id,
                        idempotency_key=batch_idem,
                        document_id=doc.id,
                        processing_stage="EMBEDDING",
                        reason=f"Document embedding batch {batch[0].chunk_index}-{batch[-1].chunk_index} ({doc.filename})",
                    )
                    doc.credits_reserved_units = int(doc.credits_reserved_units or 0) + reservation.reserved_units
                    db.commit()

                    try:
                        emb_res = self._container.embedding_service.embed_documents(
                            texts,
                            title=doc.title,
                            tenant_id=business_id,
                            request_id=batch_req_id,
                        )

                        doc.status = "INDEXING"
                        doc.current_stage = "INDEXING"
                        records = [
                            VectorDocumentRecord(
                                tenant_id=business_id,
                                workspace_id=business_id,
                                document_id=str(doc.id),
                                source_id=f"doc:{doc.id}",
                                source_type=doc.doc_category or "general",
                                chunk_id=c.chunk_uid,
                                document_version=doc.version_label,
                                embedding_model=emb_res.model,
                                embedding_version=doc.embedding_version,
                                content_type=doc.mime_type,
                                language=c.language,
                                text=c.text,
                                metadata={
                                    "filename": doc.filename,
                                    "title": doc.title,
                                    "chunk_index": c.chunk_index,
                                    "page_number": c.page_number,
                                    "section_heading": c.section_heading,
                                    "sheet_name": c.sheet_name,
                                },
                            )
                            for c in batch
                        ]
                        upsert_res = self._container.qdrant_service.upsert_documents(
                            business_id,
                            records,
                            emb_res.vectors,
                            request_id=batch_req_id,
                        )
                    except AIServiceError as batch_exc:
                        batch_usage_settled = True
                        ref_log = self._container.credit_service.refund_failed_reservation(
                            db,
                            reservation=reservation,
                            error_code=batch_exc.error_code.value,
                            error_category=_classify_ingestion_error(batch_exc),
                            duration_ms=round((time.perf_counter() - started) * 1000.0, 2),
                            user_id=doc.uploaded_by_user_id,
                            document_id=doc.id,
                            reason=f"Full refund for failed ingestion batch {batch[0].chunk_index}-{batch[-1].chunk_index}",
                        )
                        doc.credits_refunded_units = int(doc.credits_refunded_units or 0) + int(
                            ref_log.credits_refunded_units or 0
                        )
                        db.commit()
                        raise
                    except Exception as raw_batch_exc:
                        batch_usage_settled = True
                        ref_log = self._container.credit_service.refund_failed_reservation(
                            db,
                            reservation=reservation,
                            error_code="INGESTION_ERROR",
                            error_category="internal",
                            duration_ms=round((time.perf_counter() - started) * 1000.0, 2),
                            user_id=doc.uploaded_by_user_id,
                            document_id=doc.id,
                            reason=f"Full refund after unexpected ingestion error ({type(raw_batch_exc).__name__})",
                        )
                        doc.credits_refunded_units = int(doc.credits_refunded_units or 0) + int(
                            ref_log.credits_refunded_units or 0
                        )
                        db.commit()
                        raise

                    for c, pt_id in zip(batch, upsert_res.point_ids):
                        c.embedding_status = "INDEXED"
                        c.qdrant_point_id = pt_id
                        c.last_error = None

                    doc.embedded_chunks = sum(
                        1 for c in existing_chunks if c.embedding_status == "INDEXED"
                    )
                    doc.indexed_chunks = doc.embedded_chunks
                    doc.failed_chunks = sum(
                        1 for c in existing_chunks if c.embedding_status == "FAILED"
                    )
                    doc.last_checkpoint_stage = f"INDEXED_{doc.indexed_chunks}_OF_{doc.total_chunks}"

                    breakdown = self._container.pricing.calculate_embedding_batch_cost(
                        model_name=emb_res.model,
                        texts=texts,
                        actual_tokens=emb_res.prompt_tokens,
                        include_chunk_fee=True,
                        operation_type="ingestion_embed",
                    )
                    usage_log = self._container.credit_service.capture_usage(
                        db,
                        reservation=reservation,
                        breakdown=breakdown,
                        duration_ms=emb_res.latency_ms,
                        user_id=doc.uploaded_by_user_id,
                        document_id=doc.id,
                        embedding_inputs=len(batch),
                        provider_metadata={
                            "batch_start": batch[0].chunk_index,
                            "batch_end": batch[-1].chunk_index,
                            "version": doc.version_label,
                            "job_id": doc.job_id,
                        },
                    )
                    doc.credits_consumed_units = int(doc.credits_consumed_units or 0) + int(
                        usage_log.credits_consumed_units or 0
                    )
                    doc.credits_refunded_units = int(doc.credits_refunded_units or 0) + int(
                        usage_log.credits_refunded_units or 0
                    )
                    doc.total_tokens_used = int(doc.total_tokens_used or 0) + int(
                        usage_log.total_tokens or 0
                    )
                    db.commit()

            doc.status = "COMPLETED"
            doc.current_stage = "COMPLETED"
            doc.last_checkpoint_stage = "COMPLETED"
            doc.completed_at = _utcnow()
            doc.processing_duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
            db.commit()
            remove_staged_file(doc.storage_path)
            doc.storage_path = None
            db.commit()

            log_ai_event(
                self._logger,
                logging.INFO,
                provider="ingestion",
                operation="process_document",
                status="ok",
                request_id=req_id,
                tenant_id=business_id,
                document_id=doc.id,
                total_chunks=doc.total_chunks,
                indexed_chunks=doc.indexed_chunks,
                latency_ms=doc.processing_duration_ms,
            )
            return doc

        except AIServiceError as exc:
            db.refresh(doc)
            indexed_count = (
                db.query(func.count(AIDocumentChunk.id))
                .filter(
                    AIDocumentChunk.document_id == doc.id,
                    AIDocumentChunk.embedding_status == "INDEXED",
                )
                .scalar()
                or 0
            )
            doc.indexed_chunks = int(indexed_count)
            doc.embedded_chunks = int(indexed_count)
            doc.error_code = exc.error_code.value
            doc.last_error_category = _classify_ingestion_error(exc)
            doc.error_message = redact_sensitive_text(
                exc.safe_detail or exc.message,
                extra_secrets=(self._settings.gemini_api_key, self._settings.qdrant_api_key),
            )
            doc.processing_duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
            if exc.error_code in (
                AIErrorCode.QUOTA_EXHAUSTED,
                AIErrorCode.RATE_LIMIT_RETRYABLE,
                AIErrorCode.INSUFFICIENT_AI_CREDITS,
                AIErrorCode.TENANT_QUOTA_EXCEEDED,
            ):
                doc.status = "QUOTA_PAUSED"
                doc.retryable = True
                if exc.retry_after_seconds is not None or exc.error_code == AIErrorCode.QUOTA_EXHAUSTED:
                    delay_s = float(
                        exc.retry_after_seconds
                        or getattr(self._settings, "gemini_quota_cooldown_seconds", 300.0)
                    )
                    doc.next_retry_at = _utcnow() + timedelta(seconds=max(1.0, delay_s))
            elif indexed_count > 0 and exc.error_code != AIErrorCode.COLLECTION_MISMATCH:
                doc.status = "PARTIALLY_COMPLETED"
                doc.retryable = True
            else:
                doc.status = "FAILED"
                doc.retryable = exc.retryable or exc.error_code in (
                    AIErrorCode.TRANSIENT_ERROR,
                    AIErrorCode.TIMEOUT_ERROR,
                    AIErrorCode.PROVIDER_UNCONFIGURED,
                )

            if not batch_usage_settled:
                self._record_usage(
                    db,
                    doc=doc,
                    operation_type="ingestion_embed",
                    stage=doc.current_stage,
                    status="error",
                    request_id=req_id,
                    duration_ms=doc.processing_duration_ms,
                    error_code=doc.error_code,
                )
            db.commit()
            log_ai_event(
                self._logger,
                logging.WARNING,
                provider=exc.provider,
                operation="process_document",
                status="paused_or_failed",
                request_id=req_id,
                tenant_id=business_id,
                document_id=doc.id,
                error_code=doc.error_code,
                indexed_chunks=doc.indexed_chunks,
                total_chunks=doc.total_chunks,
            )
            return doc

        except Exception as exc:
            doc.status = "FAILED"
            doc.error_code = "INGESTION_ERROR"
            doc.error_message = redact_sensitive_text(f"Processing failed: {type(exc).__name__}")
            doc.retryable = True
            doc.processing_duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
            db.commit()
            return doc

    def retry_document(
        self,
        db: Session,
        *,
        doc_id: int,
        business_id: int,
    ) -> AIDocument:
        doc = self._require_tenant_document(db, doc_id=doc_id, business_id=business_id)
        if doc.status not in _TERMINAL_OR_ACTIVE_RETRY_ALLOWED:
            if doc.status == "COMPLETED":
                return doc
            raise AIInvalidRequestError(
                f"Document in state {doc.status!r} cannot be retried right now.",
                provider="ingestion",
            )
        if doc.ocr_required and doc.ocr_status == "unsupported_scanned_pdf":
            raise AIInvalidRequestError(
                "Scanned PDF requires OCR and cannot be retried without text layer.",
                provider="ingestion",
            )
        if (
            doc.total_chunks > 0
            and (
                doc.embedding_model != self._settings.gemini_embedding_model
                or doc.embedding_dimensions != self._settings.gemini_embedding_dimensions
            )
        ):
            raise AIInvalidRequestError(
                (
                    f"Document embedding config ({doc.embedding_model}, {doc.embedding_dimensions} dims) "
                    f"differs from active runtime ({self._settings.gemini_embedding_model}, "
                    f"{self._settings.gemini_embedding_dimensions} dims). Use reindex instead of resume."
                ),
                provider="ingestion",
                error_code=AIErrorCode.COLLECTION_MISMATCH,
            )
        doc.cancel_requested = False
        doc.status = "PENDING"
        doc.error_code = None
        doc.error_message = None
        doc.last_error_category = None
        doc.next_retry_at = None
        db.commit()
        # Explicit operator resume allows a clean probe if embedding quota cooldown was active
        self._container.circuit_breaker.reset_key(
            f"gemini-embed:{doc.embedding_model or self._settings.gemini_embedding_model}"
        )
        return self.process_document(db, doc_id=doc.id, business_id=business_id)

    def reindex_document(
        self,
        db: Session,
        *,
        doc_id: int,
        business_id: int,
    ) -> AIDocument:
        """Re-embed and re-index existing chunks cleanly under current embedding settings without losing vectors until verified."""
        doc = self._require_tenant_document(db, doc_id=doc_id, business_id=business_id)
        chunks = (
            db.query(AIDocumentChunk)
            .filter(AIDocumentChunk.document_id == doc.id, AIDocumentChunk.business_id == business_id)
            .order_by(AIDocumentChunk.chunk_index.asc())
            .all()
        )
        if not chunks:
            return self.retry_document(db, doc_id=doc.id, business_id=business_id)

        old_version = doc.version_label
        new_version_num = doc.document_version + 1
        new_version_label = f"v{new_version_num}"
        doc.document_version = new_version_num
        doc.version_label = new_version_label
        doc.embedding_model = self._settings.gemini_embedding_model
        doc.embedding_version = self._settings.gemini_embedding_version
        doc.embedding_dimensions = self._settings.gemini_embedding_dimensions
        doc.status = "PENDING"
        doc.indexed_chunks = 0
        doc.embedded_chunks = 0
        for c in chunks:
            c.embedding_status = "PENDING"
            c.qdrant_point_id = compute_deterministic_point_id(
                tenant_id=business_id,
                document_id=str(doc.id),
                document_version=new_version_label,
                chunk_id=c.chunk_uid,
            )
        db.commit()

        updated = self.process_document(db, doc_id=doc.id, business_id=business_id)
        if updated.status == "COMPLETED" and self._container.qdrant_service.is_configured:
            try:
                self._container.qdrant_service.delete_document(
                    business_id,
                    str(doc.id),
                    document_version=old_version,
                )
            except Exception:
                # Best-effort old-version cleanup; replacement is verified & active
                pass
        return updated

    def cancel_document(self, db: Session, *, doc_id: int, business_id: int) -> AIDocument:
        doc = self._require_tenant_document(db, doc_id=doc_id, business_id=business_id)
        if doc.status == "COMPLETED":
            raise AIInvalidRequestError("Completed documents cannot be cancelled.", provider="ingestion")
        doc.cancel_requested = True
        if doc.status in ("UPLOADED", "PENDING", "QUOTA_PAUSED", "PARTIALLY_COMPLETED", "FAILED"):
            doc.status = "CANCELLED"
            doc.current_stage = "CANCELLED"
        db.commit()
        db.refresh(doc)
        return doc

    def delete_document(self, db: Session, *, doc_id: int, business_id: int) -> Dict[str, Any]:
        """Controlled two-phase deletion ensuring vectors are removed before marking document deleted."""
        doc = self._require_tenant_document(db, doc_id=doc_id, business_id=business_id)
        doc.status = "DELETING"
        doc.current_stage = "DELETING"
        db.commit()

        has_indexed = (
            db.query(func.count(AIDocumentChunk.id))
            .filter(
                AIDocumentChunk.document_id == doc.id,
                AIDocumentChunk.qdrant_point_id.isnot(None),
            )
            .scalar()
            or 0
        ) > 0

        if has_indexed and self._container.qdrant_service.is_configured:
            try:
                col_status = self._container.qdrant_service.inspect_collection_status()
                if col_status.exists:
                    self._container.qdrant_service.delete_document(business_id, str(doc.id))
            except AIServiceError as exc:
                doc.status = "PARTIALLY_COMPLETED"
                doc.error_code = exc.error_code.value
                doc.error_message = "Vector cleanup failed; document kept quarantined to prevent stale retrieval."
                db.commit()
                raise

        remove_staged_file(doc.storage_path)
        doc.storage_path = None
        doc.status = "DELETED"
        doc.current_stage = "DELETED"
        doc.deleted_at = _utcnow()
        db.query(AIDocumentChunk).filter(
            AIDocumentChunk.document_id == doc.id,
            AIDocumentChunk.business_id == business_id,
        ).delete()
        db.commit()
        return {"document_id": doc.id, "status": "DELETED"}


def run_background_ingestion(
    session_factory: sessionmaker,
    container: AIRuntimeContainer,
    *,
    doc_id: int,
    business_id: int,
) -> None:
    """FastAPI BackgroundTasks entrypoint operating inside an isolated DB session."""
    db = session_factory()
    try:
        svc = DocumentIngestionService(container)
        svc.process_document(db, doc_id=doc_id, business_id=business_id)
    finally:
        db.close()
