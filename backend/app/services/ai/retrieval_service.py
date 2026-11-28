"""Hybrid tenant-scoped RAG retrieval (Qdrant vector similarity + exact-ID/lexical RRF fusion)."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from sqlalchemy.orm import Session

from ...core.ai_exceptions import AIServiceError
from ...models.ai_rag import AIDocument, AIDocumentChunk
from .container import AIRuntimeContainer
from .language_detection import detect_language
from .text_normalization import normalize_text_preserve_scripts

_EXACT_ID_RE = re.compile(r"\b(?:[A-Z]{2,}[A-Z0-9_-]*-[A-Z0-9_-]+|[A-Z0-9]{2,}[_-][A-Z0-9_-]{2,})\b")
_WORD_RE = re.compile(r"[\w\u0900-\u097F]+", re.UNICODE)

_EN_STOPWORDS = {
    "the", "is", "are", "was", "were", "a", "an", "in", "on", "at", "to", "for",
    "of", "and", "or", "with", "how", "what", "which", "when", "where", "who", "why",
    "do", "does", "did", "can", "i", "we", "you", "my", "our", "me", "please", "explain",
}
_HI_STOPWORDS = {
    "है", "हैं", "था", "थे", "का", "की", "के", "को", "में", "से", "पर", "और",
    "या", "क्या", "कैसे", "कौन", "कौनसे", "कितना", "कब", "कहाँ", "बताएं", "बताओ", "करो",
}


@dataclass(frozen=True)
class QueryAnalysis:
    raw_query: str
    focused_query: str
    detected_language: str
    exact_identifiers: List[str]
    terms: List[str]


@dataclass(frozen=True)
class RetrievedChunkEvidence:
    document_id: int
    document_title: str
    filename: str
    file_type: str
    doc_category: str
    document_version: str
    chunk_id: str
    chunk_index: int
    page_number: Optional[int]
    section_heading: Optional[str]
    sheet_name: Optional[str]
    language: str
    excerpt: str
    vector_score: float
    lexical_score: float
    combined_score: float
    match_reason: str


@dataclass(frozen=True)
class RetrievalResult:
    request_id: str
    query_analysis: QueryAnalysis
    evidence: List[RetrievedChunkEvidence]
    semantic_used: bool
    lexical_used: bool
    vector_error_code: Optional[str] = None
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    query_embed_tokens: Optional[int] = None
    query_embed_model: Optional[str] = None
    query_embed_error: Optional[str] = None


def analyze_user_query(
    query: str,
    *,
    recent_user_context: Optional[str] = None,
) -> QueryAnalysis:
    """Detect language, extract exact identifiers, and build focused standalone retrieval text."""
    normalized = normalize_text_preserve_scripts(query)
    lang_res = detect_language(normalized)
    exact_ids = list(dict.fromkeys(_EXACT_ID_RE.findall(normalized.upper())))

    tokens = [
        tok.lower()
        for tok in _WORD_RE.findall(normalized)
        if len(tok) >= 2 and tok.lower() not in _EN_STOPWORDS and tok not in _HI_STOPWORDS
    ]
    terms = list(dict.fromkeys(tokens))

    # Include compact prior context ONLY when query uses short follow-up pronouns (< 7 words)
    focused = normalized
    word_count = len(normalized.split())
    if recent_user_context and word_count <= 7:
        ctx_norm = normalize_text_preserve_scripts(recent_user_context)
        if ctx_norm and any(
            pron in normalized.lower()
            for pron in ("it", "that", "this", "they", "those", "same", "iske", "iska", "woh", "yeh")
        ):
            focused = f"{ctx_norm[:180]} | {normalized}"

    return QueryAnalysis(
        raw_query=query,
        focused_query=focused,
        detected_language=lang_res.language,
        exact_identifiers=exact_ids,
        terms=terms,
    )


def _compute_lexical_score(text: str, analysis: QueryAnalysis) -> tuple[float, bool]:
    """Compute bounded [0, 1] lexical + exact identifier score over chunk text."""
    if not text:
        return 0.0, False
    text_upper = text.upper()
    text_lower = text.lower()
    exact_hits = sum(1 for ident in analysis.exact_identifiers if ident in text_upper)

    if not analysis.terms and exact_hits == 0:
        return 0.0, False

    matched_terms = sum(1 for term in analysis.terms if term in text_lower)
    term_recall = matched_terms / max(1, len(analysis.terms)) if analysis.terms else 0.0
    exact_boost = min(0.55, exact_hits * 0.45)
    score = min(1.0, term_recall * 0.65 + exact_boost)
    return round(score, 4), (exact_hits > 0)


def _jaccard_overlap(a: str, b: str) -> float:
    sa = set(_WORD_RE.findall(a.lower()))
    sb = set(_WORD_RE.findall(b.lower()))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class TenantHybridRetrievalService:
    """Combines tenant-scoped Qdrant semantic search with exact-ID & lexical RRF fusion."""

    RRF_K = 40.0

    def __init__(self, container: AIRuntimeContainer) -> None:
        self._container = container
        self._settings = container.settings

    def retrieve(
        self,
        db: Session,
        *,
        business_id: int,
        query: str,
        top_k: int = 5,
        min_score: float = 0.12,
        language: Optional[str] = None,
        doc_category: Optional[str] = None,
        document_ids: Optional[Sequence[int]] = None,
        recent_user_context: Optional[str] = None,
        max_chunks_per_doc: int = 3,
        request_id: Optional[str] = None,
    ) -> RetrievalResult:
        started = time.perf_counter()
        req_id = request_id or str(uuid4())
        analysis = analyze_user_query(query, recent_user_context=recent_user_context)

        # 1. Resolve authorized active documents belonging STRICTLY to business_id
        doc_q = db.query(AIDocument).filter(
            AIDocument.business_id == business_id,
            AIDocument.status.in_(("COMPLETED", "PARTIALLY_COMPLETED")),
            AIDocument.deleted_at.is_(None),
        )
        if language and language != "auto":
            doc_q = doc_q.filter(AIDocument.detected_language.in_((language, "mixed")))
        if doc_category:
            doc_q = doc_q.filter(AIDocument.doc_category == doc_category)
        if document_ids:
            doc_q = doc_q.filter(AIDocument.id.in_(list(document_ids)))

        active_docs: Dict[int, AIDocument] = {d.id: d for d in doc_q.all()}
        if not active_docs:
            return RetrievalResult(
                request_id=req_id,
                query_analysis=analysis,
                evidence=[],
                semantic_used=False,
                lexical_used=False,
                latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            )

        # 2. Fetch indexed chunks for active authorized documents cleanly
        chunk_rows = (
            db.query(AIDocumentChunk)
            .filter(
                AIDocumentChunk.business_id == business_id,
                AIDocumentChunk.document_id.in_(list(active_docs.keys())),
                AIDocumentChunk.embedding_status == "INDEXED",
            )
            .all()
        )
        chunks_by_uid: Dict[tuple[int, str], AIDocumentChunk] = {
            (c.document_id, c.chunk_uid): c for c in chunk_rows
        }

        # 3. Run Qdrant semantic vector retrieval when configured & operational
        semantic_used = False
        vector_error_code: Optional[str] = None
        embed_executed = False
        query_embed_tokens: Optional[int] = None
        query_embed_model: Optional[str] = None
        query_embed_error: Optional[str] = None
        semantic_scores: Dict[int, float] = {}
        semantic_order: List[int] = []

        if self._container.gemini_client.is_configured and self._container.qdrant_service.is_configured:
            try:
                emb_res = self._container.embedding_service.embed_texts(
                    [analysis.focused_query],
                    task_type="RETRIEVAL_QUERY",
                    tenant_id=business_id,
                    request_id=req_id,
                )
                embed_executed = True
                query_embed_tokens = emb_res.prompt_tokens
                query_embed_model = emb_res.model
                q_vec = emb_res.vectors[0]
                str_doc_ids = [str(did) for did in active_docs]
                qdrant_res = self._container.qdrant_service.search(
                    business_id,
                    q_vec,
                    limit=min(40, max(12, top_k * 4)),
                    document_ids=str_doc_ids,
                    languages=[language, "mixed"] if language and language not in ("auto", "all") else None,
                    request_id=req_id,
                )
                semantic_used = True
                for hit in qdrant_res.hits:
                    try:
                        did = int(hit.document_id)
                    except (TypeError, ValueError):
                        continue
                    doc_obj = active_docs.get(did)
                    if not doc_obj or hit.tenant_id != business_id:
                        continue
                    if hit.document_version != doc_obj.version_label:
                        continue
                    chunk_obj = chunks_by_uid.get((did, hit.chunk_id))
                    if not chunk_obj:
                        continue
                    if chunk_obj.id not in semantic_scores:
                        semantic_scores[chunk_obj.id] = max(0.0, float(hit.score))
                        semantic_order.append(chunk_obj.id)
            except AIServiceError as exc:
                vector_error_code = exc.error_code.value
                if not embed_executed:
                    query_embed_error = exc.error_code.value

        # 4. Run tenant-scoped lexical & exact-identifier scoring
        lexical_used = bool(chunk_rows)
        lexical_scores: Dict[int, float] = {}
        exact_flags: Dict[int, bool] = {}
        for chunk in chunk_rows:
            l_score, has_exact = _compute_lexical_score(chunk.text, analysis)
            if l_score > 0.0:
                lexical_scores[chunk.id] = l_score
                exact_flags[chunk.id] = has_exact

        lexical_order = sorted(lexical_scores.keys(), key=lambda cid: lexical_scores[cid], reverse=True)

        # 5. Merge Semantic + Lexical via RRF + exact-identifier & score weighting
        semantic_rank = {cid: idx + 1 for idx, cid in enumerate(semantic_order)}
        lexical_rank = {cid: idx + 1 for idx, cid in enumerate(lexical_order)}
        candidate_ids = set(semantic_order) | set(lexical_order[: max(20, top_k * 4)])
        chunk_lookup = {c.id: c for c in chunk_rows}

        scored: List[tuple[float, AIDocumentChunk]] = []
        for cid in candidate_ids:
            chunk = chunk_lookup.get(cid)
            if not chunk:
                continue
            v_score = semantic_scores.get(cid, 0.0)
            l_score = lexical_scores.get(cid, 0.0)
            has_exact = exact_flags.get(cid, False)

            rrf = 0.0
            if cid in semantic_rank:
                rrf += 1.0 / (self.RRF_K + semantic_rank[cid])
            if cid in lexical_rank:
                rrf += 0.85 / (self.RRF_K + lexical_rank[cid])

            if semantic_used:
                combined = 0.55 * v_score + 0.30 * l_score + min(0.25, rrf * 6.0)
            else:
                combined = l_score

            if has_exact:
                combined = min(1.0, combined + 0.15)

            if combined >= min_score or (has_exact and l_score >= 0.3):
                scored.append((round(min(1.0, combined), 4), chunk))

        scored.sort(key=lambda pair: pair[0], reverse=True)

        # 6. Deduplicate near-identical chunks & enforce per-document source diversity
        selected: List[RetrievedChunkEvidence] = []
        per_doc_counts: Dict[int, int] = {}
        for combined_score, chunk in scored:
            if len(selected) >= top_k:
                break
            doc_obj = active_docs[chunk.document_id]
            if per_doc_counts.get(doc_obj.id, 0) >= max_chunks_per_doc:
                continue
            if any(_jaccard_overlap(chunk.text, prev.excerpt) > 0.85 for prev in selected):
                continue

            v_score = semantic_scores.get(chunk.id, 0.0)
            l_score = lexical_scores.get(chunk.id, 0.0)
            if exact_flags.get(chunk.id):
                reason = "hybrid_exact_id" if v_score > 0 else "exact_identifier"
            elif v_score > 0 and l_score > 0:
                reason = "hybrid_semantic_lexical"
            elif v_score > 0:
                reason = "semantic_vector"
            else:
                reason = "lexical_match"

            selected.append(
                RetrievedChunkEvidence(
                    document_id=doc_obj.id,
                    document_title=doc_obj.title,
                    filename=doc_obj.filename,
                    file_type=doc_obj.file_type,
                    doc_category=doc_obj.doc_category,
                    document_version=doc_obj.version_label,
                    chunk_id=chunk.chunk_uid,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    section_heading=chunk.section_heading,
                    sheet_name=chunk.sheet_name,
                    language=chunk.language,
                    excerpt=chunk.text,
                    vector_score=round(v_score, 4),
                    lexical_score=round(l_score, 4),
                    combined_score=combined_score,
                    match_reason=reason,
                )
            )
            per_doc_counts[doc_obj.id] = per_doc_counts.get(doc_obj.id, 0) + 1

        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return RetrievalResult(
            request_id=req_id,
            query_analysis=analysis,
            evidence=selected,
            semantic_used=semantic_used,
            lexical_used=lexical_used,
            vector_error_code=vector_error_code,
            latency_ms=latency_ms,
            metadata={
                "candidate_count": len(scored),
                "active_documents": len(active_docs),
                "embed_executed": embed_executed,
            },
            query_embed_tokens=query_embed_tokens,
            query_embed_model=query_embed_model,
            query_embed_error=query_embed_error,
        )
