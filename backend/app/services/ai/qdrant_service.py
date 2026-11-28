"""Tenant-isolated Qdrant vector database client, collection manager, and search service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence
from uuid import NAMESPACE_URL, uuid4, uuid5

from qdrant_client import QdrantClient, models

from ...core.ai_config import AIProviderSettings
from ...core.ai_exceptions import (
    AIInvalidRequestError,
    QdrantCollectionMismatchError,
    TenantIsolationError,
    classify_qdrant_error,
)
from ...core.ai_logging import get_ai_logger, log_ai_event
from .gemini_embeddings import validate_and_normalize_vector
from .retry import execute_with_retry

_RESERVED_EXTRA_METADATA_KEYS = {
    "tenant_id",
    "workspace_id",
    "document_id",
    "source_id",
    "source_type",
    "chunk_id",
    "document_version",
    "embedding_model",
    "embedding_version",
    "content_type",
    "language",
    "created_at",
    "text",
}

_INDEXED_PAYLOAD_FIELDS: tuple[tuple[str, models.PayloadSchemaType], ...] = (
    ("tenant_id", models.PayloadSchemaType.INTEGER),
    ("workspace_id", models.PayloadSchemaType.INTEGER),
    ("document_id", models.PayloadSchemaType.KEYWORD),
    ("source_id", models.PayloadSchemaType.KEYWORD),
    ("source_type", models.PayloadSchemaType.KEYWORD),
    ("document_version", models.PayloadSchemaType.KEYWORD),
    ("embedding_model", models.PayloadSchemaType.KEYWORD),
    ("embedding_version", models.PayloadSchemaType.KEYWORD),
    ("language", models.PayloadSchemaType.KEYWORD),
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_deterministic_point_id(
    *,
    tenant_id: int,
    document_id: str,
    document_version: str,
    chunk_id: str,
) -> str:
    """Return deterministic UUIDv5 ensuring idempotent chunk upserts per tenant."""
    seed = f"sims:v1:tenant:{tenant_id}:doc:{document_id}:ver:{document_version}:chunk:{chunk_id}"
    return str(uuid5(NAMESPACE_URL, seed))


def _validate_positive_tenant_id(tenant_id: Any, *, field_name: str = "tenant_id") -> int:
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
        raise TenantIsolationError(
            f"{field_name} must be a positive integer.",
            provider="qdrant",
        )
    return tenant_id


def _require_non_empty_str(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AIInvalidRequestError(
            f"{field_name} must be a non-empty string.",
            provider="qdrant",
        )
    return value.strip()


@dataclass(frozen=True)
class VectorDocumentRecord:
    """Strict schema for vector payloads stored in Qdrant."""

    tenant_id: int
    document_id: str
    source_id: str
    source_type: str
    chunk_id: str
    text: str
    embedding_model: str
    embedding_version: str
    workspace_id: Optional[int] = None
    document_version: str = "v1"
    content_type: str = "text/plain"
    language: str = "en"
    created_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        tid = _validate_positive_tenant_id(self.tenant_id, field_name="tenant_id")
        wid = tid if self.workspace_id is None else _validate_positive_tenant_id(
            self.workspace_id, field_name="workspace_id"
        )
        doc_id = _require_non_empty_str(self.document_id, field_name="document_id")
        src_id = _require_non_empty_str(self.source_id, field_name="source_id")
        src_type = _require_non_empty_str(self.source_type, field_name="source_type")
        chunk_id = _require_non_empty_str(self.chunk_id, field_name="chunk_id")
        text = _require_non_empty_str(self.text, field_name="text")
        emb_model = _require_non_empty_str(self.embedding_model, field_name="embedding_model")
        emb_ver = _require_non_empty_str(self.embedding_version, field_name="embedding_version")
        doc_ver = _require_non_empty_str(self.document_version, field_name="document_version")
        ctype = _require_non_empty_str(self.content_type, field_name="content_type")
        lang = _require_non_empty_str(self.language, field_name="language")

        extra_clean: Dict[str, Any] = {}
        for k, v in self.metadata.items():
            if k in _RESERVED_EXTRA_METADATA_KEYS:
                raise TenantIsolationError(
                    f"Custom metadata cannot override reserved payload field {k!r}.",
                    provider="qdrant",
                )
            extra_clean[k] = v

        payload: Dict[str, Any] = {
            "tenant_id": tid,
            "workspace_id": wid,
            "document_id": doc_id,
            "source_id": src_id,
            "source_type": src_type,
            "chunk_id": chunk_id,
            "document_version": doc_ver,
            "embedding_model": emb_model,
            "embedding_version": emb_ver,
            "content_type": ctype,
            "language": lang,
            "created_at": self.created_at or _utc_now_iso(),
            "text": text,
        }
        if extra_clean:
            payload["metadata"] = extra_clean
        return payload


@dataclass(frozen=True)
class VectorSearchHit:
    point_id: str
    score: float
    tenant_id: int
    workspace_id: int
    document_id: str
    source_id: str
    source_type: str
    chunk_id: str
    document_version: str
    embedding_model: str
    embedding_version: str
    content_type: str
    language: str
    text: str
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QdrantUpsertResult:
    collection_name: str
    tenant_id: int
    upserted_count: int
    point_ids: List[str]
    latency_ms: float
    retries: int
    request_id: str


@dataclass(frozen=True)
class QdrantSearchResult:
    collection_name: str
    tenant_id: int
    hits: List[VectorSearchHit]
    latency_ms: float
    retries: int
    request_id: str


@dataclass(frozen=True)
class QdrantCollectionStatus:
    collection_name: str
    exists: bool
    vector_size: Optional[int]
    distance: Optional[str]
    points_count: Optional[int]
    matches_expected_schema: bool
    latency_ms: float


class QdrantVectorService:
    """Lifecycle-managed, strictly tenant-scoped Qdrant vector store service."""

    DEFAULT_UPSERT_BATCH_SIZE = 64

    def __init__(
        self,
        settings: AIProviderSettings,
        *,
        client: Optional[QdrantClient] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        jitter_fn: Optional[Callable[[float, float], float]] = None,
    ) -> None:
        self._settings = settings
        self._client: Optional[QdrantClient] = client
        self._owns_client = client is None
        self._lock = threading.RLock()
        self._verified_collections: set[str] = set()
        self._sleep_fn = sleep_fn
        self._jitter_fn = jitter_fn
        self._logger = get_ai_logger("qdrant")

    @property
    def settings(self) -> AIProviderSettings:
        return self._settings

    @property
    def is_configured(self) -> bool:
        return self._client is not None or self._settings.is_qdrant_configured

    @property
    def is_initialized(self) -> bool:
        return self._client is not None

    def get_client(self) -> QdrantClient:
        with self._lock:
            if self._client is not None:
                return self._client
            self._settings.validate_qdrant_ready()
            timeout_sec = max(1, math.ceil(self._settings.qdrant_timeout_seconds))
            if self._settings.qdrant_url == ":memory:":
                self._client = QdrantClient(":memory:")
            else:
                self._client = QdrantClient(
                    url=self._settings.qdrant_url,
                    api_key=self._settings.qdrant_api_key,
                    timeout=timeout_sec,
                    prefer_grpc=self._settings.qdrant_prefer_grpc,
                )
            self._owns_client = True
            return self._client

    def close(self) -> None:
        with self._lock:
            self._verified_collections.clear()
            if self._client is not None and self._owns_client:
                try:
                    self._client.close()
                except Exception:
                    pass
            self._client = None

    def _run_with_retry(self, operation: str, fn: Callable[[], Any], *, req_id: str, tenant_id: Optional[int] = None):
        def _on_retry(attempt_num: int, err: Any, delay: float) -> None:
            log_ai_event(
                self._logger,
                logging.WARNING,
                provider="qdrant",
                operation=f"{operation}_retry",
                status="retrying",
                request_id=req_id,
                tenant_id=tenant_id,
                retries=attempt_num,
                error_code=err.error_code.value,
                backoff_seconds=round(delay, 3),
                extra_secrets=(self._settings.qdrant_api_key,),
            )

        return execute_with_retry(
            fn,
            classifier=classify_qdrant_error,
            max_retries=self._settings.qdrant_max_retries,
            base_seconds=self._settings.gemini_retry_base_seconds,
            max_seconds=self._settings.gemini_retry_max_seconds,
            sleep_fn=self._sleep_fn,
            jitter_fn=self._jitter_fn,
            on_retry=_on_retry,
        )

    @staticmethod
    def _extract_vector_params(info: Any) -> tuple[Optional[int], Optional[str]]:
        config = getattr(info, "config", None)
        params = getattr(config, "params", None)
        vectors = getattr(params, "vectors", None)
        if vectors is None:
            return None, None
        if isinstance(vectors, dict):
            return None, None
        size = getattr(vectors, "size", None)
        distance = getattr(vectors, "distance", None)
        dist_val = getattr(distance, "value", None) or (str(distance) if distance is not None else None)
        return (int(size) if size is not None else None, dist_val)

    def ensure_collection(
        self,
        *,
        collection_name: Optional[str] = None,
        vector_size: Optional[int] = None,
        request_id: Optional[str] = None,
        force_recheck: bool = False,
    ) -> str:
        """Create collection + payload indexes if missing, or verify exact vector geometry."""
        target_col = (collection_name or self._settings.effective_collection_name).strip()
        target_dim = vector_size or self._settings.gemini_embedding_dimensions
        if target_dim < 128 or target_dim > 3072:
            raise AIInvalidRequestError(
                "Collection vector_size must be between 128 and 3072.",
                provider="qdrant",
            )

        with self._lock:
            if not force_recheck and target_col in self._verified_collections:
                return target_col

            req_id = request_id or str(uuid4())
            client = self.get_client()
            started = time.perf_counter()

            exists, retries = self._run_with_retry(
                "collection_exists",
                lambda: client.collection_exists(collection_name=target_col),
                req_id=req_id,
            )

            if not exists:
                _, create_retries = self._run_with_retry(
                    "create_collection",
                    lambda: client.create_collection(
                        collection_name=target_col,
                        vectors_config=models.VectorParams(
                            size=target_dim,
                            distance=models.Distance.COSINE,
                        ),
                    ),
                    req_id=req_id,
                )
                retries += create_retries
                self._ensure_payload_indexes(client, target_col, req_id=req_id)
            else:
                info, info_retries = self._run_with_retry(
                    "get_collection",
                    lambda: client.get_collection(collection_name=target_col),
                    req_id=req_id,
                )
                retries += info_retries
                actual_size, actual_dist = self._extract_vector_params(info)
                if actual_size != target_dim or (actual_dist or "").lower() != "cosine":
                    raise QdrantCollectionMismatchError(
                        f"Qdrant collection {target_col!r} vector schema mismatch: "
                        f"expected size={target_dim} distance='Cosine', "
                        f"found size={actual_size} distance={actual_dist!r}."
                    )
                self._ensure_payload_indexes(client, target_col, req_id=req_id)

            self._verified_collections.add(target_col)
            latency_ms = (time.perf_counter() - started) * 1000.0
            log_ai_event(
                self._logger,
                logging.INFO,
                provider="qdrant",
                operation="ensure_collection",
                status="ok",
                request_id=req_id,
                retries=retries,
                latency_ms=latency_ms,
                collection_name=target_col,
                vector_size=target_dim,
                created=not exists,
                extra_secrets=(self._settings.qdrant_api_key,),
            )
            return target_col

    def _ensure_payload_indexes(self, client: QdrantClient, collection_name: str, *, req_id: str) -> None:
        is_local_memory = getattr(client, "_client", None).__class__.__name__ == "QdrantLocal"
        if is_local_memory:
            return
        for field_name, schema_type in _INDEXED_PAYLOAD_FIELDS:
            try:
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=schema_type,
                    wait=True,
                )
            except Exception as exc:
                classified = classify_qdrant_error(exc)
                if classified.http_status in (400, 409):
                    continue
                log_ai_event(
                    self._logger,
                    logging.WARNING,
                    provider="qdrant",
                    operation="create_payload_index",
                    status="warning",
                    request_id=req_id,
                    collection_name=collection_name,
                    field_name=field_name,
                    error_code=classified.error_code.value,
                    extra_secrets=(self._settings.qdrant_api_key,),
                )
                raise classified from exc

    def inspect_collection_status(
        self,
        *,
        collection_name: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> QdrantCollectionStatus:
        """Inspect Qdrant connectivity and verify active collection schema safely."""
        target_col = (collection_name or self._settings.effective_collection_name).strip()
        req_id = request_id or str(uuid4())
        client = self.get_client()
        started = time.perf_counter()

        exists, _ = self._run_with_retry(
            "inspect_collection_exists",
            lambda: client.collection_exists(collection_name=target_col),
            req_id=req_id,
        )
        if not exists:
            return QdrantCollectionStatus(
                collection_name=target_col,
                exists=False,
                vector_size=None,
                distance=None,
                points_count=None,
                matches_expected_schema=False,
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )

        info, _ = self._run_with_retry(
            "inspect_get_collection",
            lambda: client.get_collection(collection_name=target_col),
            req_id=req_id,
        )
        actual_size, actual_dist = self._extract_vector_params(info)
        points_count = getattr(info, "points_count", None)
        matches = (
            actual_size == self._settings.gemini_embedding_dimensions
            and (actual_dist or "").lower() == "cosine"
        )
        return QdrantCollectionStatus(
            collection_name=target_col,
            exists=True,
            vector_size=actual_size,
            distance=actual_dist,
            points_count=int(points_count) if points_count is not None else None,
            matches_expected_schema=matches,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    def upsert_documents(
        self,
        tenant_id: int,
        records: Sequence[VectorDocumentRecord],
        vectors: Sequence[Sequence[float]],
        *,
        collection_name: Optional[str] = None,
        ensure_ready: bool = True,
        batch_size: int = DEFAULT_UPSERT_BATCH_SIZE,
        request_id: Optional[str] = None,
    ) -> QdrantUpsertResult:
        """Validate tenant isolation + vector dimensions and upsert points idempotently."""
        tid = _validate_positive_tenant_id(tenant_id, field_name="tenant_id")
        if len(records) != len(vectors):
            raise AIInvalidRequestError(
                f"Records count ({len(records)}) must match vectors count ({len(vectors)}).",
                provider="qdrant",
            )
        if not records:
            raise AIInvalidRequestError("At least one vector record is required for upsert.", provider="qdrant")
        if batch_size < 1 or batch_size > 256:
            raise AIInvalidRequestError("batch_size must be between 1 and 256.", provider="qdrant")

        target_dim = self._settings.gemini_embedding_dimensions
        target_col = (collection_name or self._settings.effective_collection_name).strip()
        req_id = request_id or str(uuid4())
        started = time.perf_counter()

        points: List[models.PointStruct] = []
        point_ids: List[str] = []
        for record, raw_vec in zip(records, vectors):
            if record.tenant_id != tid:
                raise TenantIsolationError(
                    f"Record tenant_id={record.tenant_id} does not match request tenant_id={tid}.",
                    provider="qdrant",
                )
            payload = record.to_payload()
            vec = validate_and_normalize_vector(
                raw_vec,
                expected_dimensions=target_dim,
                normalize=self._settings.gemini_embedding_normalize,
            )
            point_id = compute_deterministic_point_id(
                tenant_id=tid,
                document_id=str(payload["document_id"]),
                document_version=str(payload["document_version"]),
                chunk_id=str(payload["chunk_id"]),
            )
            point_ids.append(point_id)
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vec,
                    payload=payload,
                )
            )

        if ensure_ready:
            target_col = self.ensure_collection(
                collection_name=target_col,
                vector_size=target_dim,
                request_id=req_id,
            )

        client = self.get_client()
        total_retries = 0
        for start in range(0, len(points), batch_size):
            batch = points[start : start + batch_size]
            _, retries = self._run_with_retry(
                "upsert",
                lambda b=batch: client.upsert(
                    collection_name=target_col,
                    points=b,
                    wait=True,
                ),
                req_id=req_id,
                tenant_id=tid,
            )
            total_retries += retries

        latency_ms = (time.perf_counter() - started) * 1000.0
        log_ai_event(
            self._logger,
            logging.INFO,
            provider="qdrant",
            operation="upsert_documents",
            status="ok",
            request_id=req_id,
            tenant_id=tid,
            latency_ms=latency_ms,
            retries=total_retries,
            collection_name=target_col,
            upserted_count=len(points),
            extra_secrets=(self._settings.qdrant_api_key,),
        )
        return QdrantUpsertResult(
            collection_name=target_col,
            tenant_id=tid,
            upserted_count=len(points),
            point_ids=point_ids,
            latency_ms=latency_ms,
            retries=total_retries,
            request_id=req_id,
        )

    def _build_tenant_filter(
        self,
        tenant_id: int,
        *,
        workspace_id: Optional[int] = None,
        source_types: Optional[Sequence[str]] = None,
        document_ids: Optional[Sequence[str]] = None,
        document_version: Optional[str] = None,
        languages: Optional[Sequence[str]] = None,
        embedding_version: Optional[str] = None,
    ) -> models.Filter:
        tid = _validate_positive_tenant_id(tenant_id, field_name="tenant_id")
        must: List[models.Condition] = [
            models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tid))
        ]
        if workspace_id is not None:
            wid = _validate_positive_tenant_id(workspace_id, field_name="workspace_id")
            must.append(models.FieldCondition(key="workspace_id", match=models.MatchValue(value=wid)))
        if source_types:
            vals = [s.strip() for s in source_types if s and s.strip()]
            if vals:
                must.append(models.FieldCondition(key="source_type", match=models.MatchAny(any=vals)))
        if document_ids:
            vals = [d.strip() for d in document_ids if d and d.strip()]
            if vals:
                must.append(models.FieldCondition(key="document_id", match=models.MatchAny(any=vals)))
        if document_version and document_version.strip():
            must.append(
                models.FieldCondition(
                    key="document_version",
                    match=models.MatchValue(value=document_version.strip()),
                )
            )
        if languages:
            vals = [lang.strip() for lang in languages if lang and lang.strip()]
            if vals:
                must.append(models.FieldCondition(key="language", match=models.MatchAny(any=vals)))
        if embedding_version and embedding_version.strip():
            must.append(
                models.FieldCondition(
                    key="embedding_version",
                    match=models.MatchValue(value=embedding_version.strip()),
                )
            )
        return models.Filter(must=must)

    def search(
        self,
        tenant_id: int,
        query_vector: Sequence[float],
        *,
        limit: int = 5,
        score_threshold: Optional[float] = None,
        workspace_id: Optional[int] = None,
        source_types: Optional[Sequence[str]] = None,
        document_ids: Optional[Sequence[str]] = None,
        languages: Optional[Sequence[str]] = None,
        embedding_version: Optional[str] = None,
        collection_name: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> QdrantSearchResult:
        """Execute similarity search strictly constrained to `tenant_id`."""
        tid = _validate_positive_tenant_id(tenant_id, field_name="tenant_id")
        if limit < 1 or limit > 100:
            raise AIInvalidRequestError("limit must be between 1 and 100.", provider="qdrant")

        normalized_vec = validate_and_normalize_vector(
            query_vector,
            expected_dimensions=self._settings.gemini_embedding_dimensions,
            normalize=self._settings.gemini_embedding_normalize,
        )
        tenant_filter = self._build_tenant_filter(
            tid,
            workspace_id=workspace_id,
            source_types=source_types,
            document_ids=document_ids,
            languages=languages,
            embedding_version=embedding_version,
        )
        target_col = (collection_name or self._settings.effective_collection_name).strip()
        req_id = request_id or str(uuid4())
        client = self.get_client()
        started = time.perf_counter()

        response, retries = self._run_with_retry(
            "query_points",
            lambda: client.query_points(
                collection_name=target_col,
                query=normalized_vec,
                query_filter=tenant_filter,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False,
            ),
            req_id=req_id,
            tenant_id=tid,
        )

        raw_points = getattr(response, "points", None) or []
        hits: List[VectorSearchHit] = []
        for pt in raw_points:
            payload = dict(getattr(pt, "payload", None) or {})
            payload_tenant = payload.get("tenant_id")
            if payload_tenant != tid:
                raise TenantIsolationError(
                    f"Cross-tenant vector returned from Qdrant (expected {tid}, got {payload_tenant!r}).",
                    provider="qdrant",
                )
            hits.append(
                VectorSearchHit(
                    point_id=str(pt.id),
                    score=float(getattr(pt, "score", 0.0) or 0.0),
                    tenant_id=tid,
                    workspace_id=int(payload.get("workspace_id", tid)),
                    document_id=str(payload.get("document_id", "")),
                    source_id=str(payload.get("source_id", "")),
                    source_type=str(payload.get("source_type", "")),
                    chunk_id=str(payload.get("chunk_id", "")),
                    document_version=str(payload.get("document_version", "v1")),
                    embedding_model=str(payload.get("embedding_model", "")),
                    embedding_version=str(payload.get("embedding_version", "")),
                    content_type=str(payload.get("content_type", "text/plain")),
                    language=str(payload.get("language", "en")),
                    text=str(payload.get("text", "")),
                    created_at=str(payload.get("created_at", "")),
                    metadata=dict(payload.get("metadata") or {}),
                )
            )

        latency_ms = (time.perf_counter() - started) * 1000.0
        log_ai_event(
            self._logger,
            logging.INFO,
            provider="qdrant",
            operation="search",
            status="ok",
            request_id=req_id,
            tenant_id=tid,
            latency_ms=latency_ms,
            retries=retries,
            collection_name=target_col,
            hit_count=len(hits),
            extra_secrets=(self._settings.qdrant_api_key,),
        )
        return QdrantSearchResult(
            collection_name=target_col,
            tenant_id=tid,
            hits=hits,
            latency_ms=latency_ms,
            retries=retries,
            request_id=req_id,
        )

    def count_tenant_vectors(
        self,
        tenant_id: int,
        *,
        collection_name: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> int:
        tid = _validate_positive_tenant_id(tenant_id, field_name="tenant_id")
        target_col = (collection_name or self._settings.effective_collection_name).strip()
        req_id = request_id or str(uuid4())
        client = self.get_client()
        tenant_filter = self._build_tenant_filter(tid)
        result, _ = self._run_with_retry(
            "count",
            lambda: client.count(
                collection_name=target_col,
                count_filter=tenant_filter,
                exact=True,
            ),
            req_id=req_id,
            tenant_id=tid,
        )
        return int(getattr(result, "count", 0) or 0)

    def delete_document(
        self,
        tenant_id: int,
        document_id: str,
        *,
        document_version: Optional[str] = None,
        collection_name: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        tid = _validate_positive_tenant_id(tenant_id, field_name="tenant_id")
        doc_id = _require_non_empty_str(document_id, field_name="document_id")
        target_col = (collection_name or self._settings.effective_collection_name).strip()
        req_id = request_id or str(uuid4())
        client = self.get_client()
        tenant_filter = self._build_tenant_filter(
            tid,
            document_ids=[doc_id],
            document_version=document_version,
        )
        self._run_with_retry(
            "delete_document",
            lambda: client.delete(
                collection_name=target_col,
                points_selector=models.FilterSelector(filter=tenant_filter),
                wait=True,
            ),
            req_id=req_id,
            tenant_id=tid,
        )

    def delete_tenant_vectors(
        self,
        tenant_id: int,
        *,
        collection_name: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        tid = _validate_positive_tenant_id(tenant_id, field_name="tenant_id")
        target_col = (collection_name or self._settings.effective_collection_name).strip()
        req_id = request_id or str(uuid4())
        client = self.get_client()
        tenant_filter = self._build_tenant_filter(tid)
        self._run_with_retry(
            "delete_tenant_vectors",
            lambda: client.delete(
                collection_name=target_col,
                points_selector=models.FilterSelector(filter=tenant_filter),
                wait=True,
            ),
            req_id=req_id,
            tenant_id=tid,
        )
