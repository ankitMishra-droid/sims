"""Diagnostics and live health verification for Gemini LLM, Embeddings, and Qdrant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import uuid4

from ...core.ai_config import AIProviderSettings
from ...core.ai_exceptions import AIServiceError
from ...core.ai_logging import redact_sensitive_text
from .gemini_client import GeminiClientManager
from .gemini_embeddings import GeminiEmbeddingService
from .gemini_llm import GeminiLLMService
from .qdrant_service import QdrantVectorService


@dataclass(frozen=True)
class ComponentHealthStatus:
    name: str
    status: str  # unconfigured | configured | operational | degraded | unavailable
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


class AIHealthService:
    """Produces sanitized status summaries and explicit live provider checks."""

    def __init__(
        self,
        *,
        settings: AIProviderSettings,
        gemini_client: GeminiClientManager,
        llm_service: GeminiLLMService,
        embedding_service: GeminiEmbeddingService,
        qdrant_service: QdrantVectorService,
    ) -> None:
        self._settings = settings
        self._gemini_client = gemini_client
        self._llm = llm_service
        self._embeddings = embedding_service
        self._qdrant = qdrant_service

    def _safe_error(self, exc: AIServiceError) -> str:
        return redact_sensitive_text(
            exc.safe_detail or exc.message,
            extra_secrets=(self._settings.gemini_api_key, self._settings.qdrant_api_key),
        )

    def _gemini_llm_status(self, *, live_probe: bool, req_id: str) -> ComponentHealthStatus:
        if not self._gemini_client.is_configured:
            return ComponentHealthStatus(
                name="gemini_llm",
                status="unconfigured",
                configured=False,
                detail="GEMINI_API_KEY is not configured.",
                model=self._settings.gemini_llm_model,
            )
        if not live_probe:
            snap = self._llm.circuit_breaker.get_snapshot(f"gemini:{self._settings.gemini_llm_model}")
            if snap.get("state") == "open":
                quota_active = bool(snap.get("quota_cooldown_active"))
                return ComponentHealthStatus(
                    name="gemini_llm",
                    status="degraded",
                    configured=True,
                    detail=(
                        f"Gemini provider quota cooldown active ({snap.get('retry_after_seconds')}s remaining)."
                        if quota_active
                        else "Primary model circuit breaker open; temporary cooldown active."
                    ),
                    model=self._settings.gemini_llm_model,
                    error_code="QUOTA_EXHAUSTED" if quota_active else "CIRCUIT_OPEN",
                )
            return ComponentHealthStatus(
                name="gemini_llm",
                status="configured",
                configured=True,
                detail="Credentials present; live LLM probe skipped.",
                model=self._settings.gemini_llm_model,
            )
        try:
            res = self._llm.probe_connectivity(request_id=req_id)
            return ComponentHealthStatus(
                name="gemini_llm",
                status="operational",
                configured=True,
                detail="Live Gemini LLM probe succeeded.",
                model=res.model,
                latency_ms=round(res.latency_ms, 2),
            )
        except AIServiceError as exc:
            status = "degraded" if exc.retryable else "unavailable"
            return ComponentHealthStatus(
                name="gemini_llm",
                status=status,
                configured=True,
                detail=self._safe_error(exc),
                model=self._settings.gemini_llm_model,
                error_code=exc.error_code.value,
            )

    def _gemini_embeddings_status(self, *, live_probe: bool, req_id: str) -> ComponentHealthStatus:
        if not self._gemini_client.is_configured:
            return ComponentHealthStatus(
                name="gemini_embeddings",
                status="unconfigured",
                configured=False,
                detail="GEMINI_API_KEY is not configured.",
                model=self._settings.gemini_embedding_model,
                dimensions=self._settings.gemini_embedding_dimensions,
            )
        if not live_probe:
            return ComponentHealthStatus(
                name="gemini_embeddings",
                status="configured",
                configured=True,
                detail="Credentials present; live embedding probe skipped.",
                model=self._settings.gemini_embedding_model,
                dimensions=self._settings.gemini_embedding_dimensions,
            )
        try:
            res = self._embeddings.embed_texts(
                ["SIMS Phase 7 embedding connectivity check."],
                task_type="RETRIEVAL_QUERY",
                request_id=req_id,
            )
            return ComponentHealthStatus(
                name="gemini_embeddings",
                status="operational",
                configured=True,
                detail="Live Gemini embedding probe succeeded.",
                model=res.model,
                dimensions=res.dimensions,
                latency_ms=round(res.latency_ms, 2),
            )
        except AIServiceError as exc:
            status = "degraded" if exc.retryable else "unavailable"
            return ComponentHealthStatus(
                name="gemini_embeddings",
                status=status,
                configured=True,
                detail=self._safe_error(exc),
                model=self._settings.gemini_embedding_model,
                dimensions=self._settings.gemini_embedding_dimensions,
                error_code=exc.error_code.value,
            )

    def _qdrant_status(self, *, live_probe: bool, req_id: str) -> ComponentHealthStatus:
        host = self._settings.qdrant_endpoint_host
        col = self._settings.effective_collection_name
        if not self._qdrant.is_configured:
            return ComponentHealthStatus(
                name="qdrant",
                status="unconfigured",
                configured=False,
                detail="QDRANT_URL is not configured.",
                collection_name=col,
                dimensions=self._settings.gemini_embedding_dimensions,
            )
        if not live_probe:
            return ComponentHealthStatus(
                name="qdrant",
                status="configured",
                configured=True,
                detail="Endpoint configured; live Qdrant probe skipped.",
                collection_name=col,
                dimensions=self._settings.gemini_embedding_dimensions,
                endpoint_host=host,
            )
        try:
            info = self._qdrant.inspect_collection_status(collection_name=col, request_id=req_id)
            if info.exists and not info.matches_expected_schema:
                return ComponentHealthStatus(
                    name="qdrant",
                    status="unavailable",
                    configured=True,
                    detail=(
                        f"Collection {info.collection_name!r} schema mismatch "
                        f"(size={info.vector_size}, distance={info.distance})."
                    ),
                    collection_name=info.collection_name,
                    collection_exists=True,
                    schema_matches=False,
                    dimensions=info.vector_size,
                    endpoint_host=host,
                    latency_ms=round(info.latency_ms, 2),
                    error_code="COLLECTION_MISMATCH",
                )
            detail = (
                f"Connected; collection {info.collection_name!r} verified."
                if info.exists
                else f"Connected; collection {info.collection_name!r} not initialized yet."
            )
            return ComponentHealthStatus(
                name="qdrant",
                status="operational",
                configured=True,
                detail=detail,
                collection_name=info.collection_name,
                collection_exists=info.exists,
                schema_matches=info.matches_expected_schema if info.exists else None,
                dimensions=info.vector_size or self._settings.gemini_embedding_dimensions,
                endpoint_host=host,
                latency_ms=round(info.latency_ms, 2),
            )
        except AIServiceError as exc:
            status = "degraded" if exc.retryable else "unavailable"
            return ComponentHealthStatus(
                name="qdrant",
                status=status,
                configured=True,
                detail=self._safe_error(exc),
                collection_name=col,
                dimensions=self._settings.gemini_embedding_dimensions,
                endpoint_host=host,
                error_code=exc.error_code.value,
            )

    def check_health(
        self,
        *,
        probe_qdrant: bool = False,
        probe_gemini_embeddings: bool = False,
        probe_gemini_llm: bool = False,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        req_id = request_id or str(uuid4())
        llm = self._gemini_llm_status(live_probe=probe_gemini_llm, req_id=req_id)
        emb = self._gemini_embeddings_status(live_probe=probe_gemini_embeddings, req_id=req_id)
        qdrant = self._qdrant_status(live_probe=probe_qdrant, req_id=req_id)
        components = [llm, emb, qdrant]

        statuses = {c.status for c in components}
        if "unavailable" in statuses:
            overall = "unavailable"
        elif "degraded" in statuses:
            overall = "degraded"
        elif all(c.status == "operational" for c in components):
            overall = "operational"
        elif all(c.status == "unconfigured" for c in components):
            overall = "unconfigured"
        else:
            overall = "configured"

        return {
            "overall_status": overall,
            "environment": self._settings.app_env,
            "request_id": req_id,
            "circuit_breakers": self._llm.circuit_breaker.snapshot_all(),
            "components": {
                c.name: {
                    "status": c.status,
                    "configured": c.configured,
                    "detail": c.detail,
                    "model": c.model,
                    "dimensions": c.dimensions,
                    "collection_name": c.collection_name,
                    "collection_exists": c.collection_exists,
                    "schema_matches": c.schema_matches,
                    "endpoint_host": c.endpoint_host,
                    "latency_ms": c.latency_ms,
                    "error_code": c.error_code,
                }
                for c in components
            },
        }
