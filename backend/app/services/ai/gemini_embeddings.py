"""Enterprise Gemini embedding generation, batching, validation, and L2 normalization."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import time
from typing import Any, Callable, List, Optional, Sequence
from uuid import uuid4

from google.genai import types

from ...core.ai_config import AIProviderSettings
from ...core.ai_exceptions import (
    AIErrorCode,
    AIInvalidRequestError,
    classify_gemini_error,
)
from ...core.ai_logging import get_ai_logger, log_ai_event
from .circuit_breaker import ProviderCircuitBreaker
from .gemini_client import GeminiClientManager
from .retry import execute_with_retry


@dataclass(frozen=True)
class EmbeddingBatchResult:
    vectors: List[List[float]]
    model: str
    dimensions: int
    normalized: bool
    latency_ms: float
    retries: int
    request_id: str
    prompt_tokens: Optional[int] = None


def validate_and_normalize_vector(
    values: Sequence[float],
    *,
    expected_dimensions: int,
    normalize: bool,
) -> List[float]:
    """Verify exact embedding dimensions and finiteness, optionally normalizing to unit L2."""
    if len(values) != expected_dimensions:
        raise AIInvalidRequestError(
            f"Embedding vector length mismatch: expected {expected_dimensions}, got {len(values)}.",
            provider="gemini",
            error_code=AIErrorCode.INVALID_EMBEDDING,
        )

    floats: List[float] = []
    sq_sum = 0.0
    for item in values:
        f = float(item)
        if not math.isfinite(f):
            raise AIInvalidRequestError(
                "Embedding vector contains non-finite (NaN/Inf) value.",
                provider="gemini",
                error_code=AIErrorCode.INVALID_EMBEDDING,
            )
        floats.append(f)
        sq_sum += f * f

    norm = math.sqrt(sq_sum)
    if norm <= 1e-12:
        raise AIInvalidRequestError(
            "Embedding vector has zero L2 norm.",
            provider="gemini",
            error_code=AIErrorCode.INVALID_EMBEDDING,
        )

    if not normalize:
        return floats
    if abs(norm - 1.0) <= 1e-6:
        return floats
    return [v / norm for v in floats]


class GeminiEmbeddingService:
    """Dedicated embedding service supporting RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY workflows."""

    DEFAULT_BATCH_SIZE = 32

    def __init__(
        self,
        client_manager: GeminiClientManager,
        *,
        circuit_breaker: Optional[ProviderCircuitBreaker] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        jitter_fn: Optional[Callable[[float, float], float]] = None,
    ) -> None:
        self._client_manager = client_manager
        self._settings: AIProviderSettings = client_manager.settings
        self._circuit_breaker = circuit_breaker
        self._sleep_fn = sleep_fn
        self._jitter_fn = jitter_fn
        self._logger = get_ai_logger("gemini.embeddings")

    def _supports_task_type(self, model_name: str) -> bool:
        return not model_name.strip().lower().startswith("gemini-embedding-2")

    def _build_embed_config(
        self,
        *,
        model_name: str,
        task_type: str,
        dimensions: int,
        title: Optional[str] = None,
    ) -> types.EmbedContentConfig:
        kwargs: dict[str, Any] = {
            "output_dimensionality": dimensions,
        }
        if self._supports_task_type(model_name):
            kwargs["task_type"] = task_type
            if title and task_type == "RETRIEVAL_DOCUMENT":
                kwargs["title"] = title
        return types.EmbedContentConfig(**kwargs)

    def _prepare_texts(self, model_name: str, texts: Sequence[str], task_type: str) -> List[str]:
        if not texts:
            raise AIInvalidRequestError("At least one text is required for embeddings.", provider="gemini")
        cleaned: List[str] = []
        prefix = ""
        if not self._supports_task_type(model_name):
            if task_type == "RETRIEVAL_QUERY":
                prefix = "task: search result | query: "
            elif task_type == "RETRIEVAL_DOCUMENT":
                prefix = "task: search result | document: "
        for idx, raw in enumerate(texts):
            if not isinstance(raw, str) or not raw.strip():
                raise AIInvalidRequestError(
                    f"Embedding input at index {idx} must be a non-empty string.",
                    provider="gemini",
                )
            text = raw.strip()
            cleaned.append(f"{prefix}{text}" if prefix else text)
        return cleaned

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        task_type: str = "RETRIEVAL_DOCUMENT",
        batch_size: int = DEFAULT_BATCH_SIZE,
        title: Optional[str] = None,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        tenant_id: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> EmbeddingBatchResult:
        """Embed a sequence of non-empty strings using deterministic batching and validation."""
        if batch_size < 1 or batch_size > 100:
            raise AIInvalidRequestError("batch_size must be between 1 and 100.", provider="gemini")

        target_model = (model or self._settings.gemini_embedding_model).strip()
        target_dims = dimensions or self._settings.gemini_embedding_dimensions
        if target_dims < 128 or target_dims > 3072:
            raise AIInvalidRequestError(
                "Embedding dimensions must be between 128 and 3072.",
                provider="gemini",
            )

        prepared = self._prepare_texts(target_model, texts, task_type)
        config = self._build_embed_config(
            model_name=target_model,
            task_type=task_type,
            dimensions=target_dims,
            title=title,
        )
        client = self._client_manager.get_client()
        req_id = request_id or str(uuid4())
        started = time.perf_counter()
        vectors: List[List[float]] = []
        total_retries = 0
        total_prompt_tokens = 0
        saw_token_usage = False
        breaker_key = f"gemini-embed:{target_model}"

        for start in range(0, len(prepared), batch_size):
            batch = prepared[start : start + batch_size]

            def _invoke_batch() -> Any:
                if self._circuit_breaker is not None:
                    self._circuit_breaker.acquire_slot(
                        key=breaker_key,
                        provider="gemini",
                        wait_timeout=2.0,
                    )
                try:
                    return client.models.embed_content(
                        model=target_model,
                        contents=batch,  # type: ignore[arg-type]
                        config=config,
                    )
                except Exception as raw_exc:
                    classified = classify_gemini_error(raw_exc)
                    if self._circuit_breaker is not None:
                        self._circuit_breaker.record_failure(breaker_key, classified)
                    raise classified from raw_exc
                finally:
                    if self._circuit_breaker is not None:
                        self._circuit_breaker.release_slot()

            def _on_retry(attempt_num: int, err: Any, delay: float) -> None:
                log_ai_event(
                    self._logger,
                    logging.WARNING,
                    provider="gemini",
                    operation="embed_batch_retry",
                    status="retrying",
                    request_id=req_id,
                    tenant_id=tenant_id,
                    model=target_model,
                    retries=attempt_num,
                    error_code=err.error_code.value,
                    backoff_seconds=round(delay, 3),
                    extra_secrets=(self._settings.gemini_api_key,),
                )

            response, retries = execute_with_retry(
                _invoke_batch,
                classifier=classify_gemini_error,
                max_retries=self._settings.gemini_max_retries,
                base_seconds=self._settings.gemini_retry_base_seconds,
                max_seconds=self._settings.gemini_retry_max_seconds,
                cancel_event=self._client_manager.shutdown_event,
                sleep_fn=self._sleep_fn,
                jitter_fn=self._jitter_fn,
                on_retry=_on_retry,
            )
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_success(breaker_key)
            total_retries += retries

            usage_meta = getattr(response, "usage_metadata", None)
            meta_prompt = getattr(usage_meta, "prompt_token_count", None) if usage_meta is not None else None
            if isinstance(meta_prompt, (int, float)) and meta_prompt > 0:
                total_prompt_tokens += int(meta_prompt)
                saw_token_usage = True

            raw_embeddings = getattr(response, "embeddings", None) or []
            if len(raw_embeddings) != len(batch):
                raise AIInvalidRequestError(
                    f"Gemini returned {len(raw_embeddings)} embeddings for batch size {len(batch)}.",
                    provider="gemini",
                    error_code=AIErrorCode.INVALID_EMBEDDING,
                )

            batch_item_tokens = 0
            saw_item_tokens = False
            for item in raw_embeddings:
                vals = getattr(item, "values", None)
                if vals is None:
                    raise AIInvalidRequestError(
                        "Gemini returned an embedding without numeric values.",
                        provider="gemini",
                        error_code=AIErrorCode.INVALID_EMBEDDING,
                    )
                stats = getattr(item, "statistics", None)
                item_tok = getattr(stats, "token_count", None) if stats is not None else None
                if isinstance(item_tok, (int, float)) and item_tok > 0:
                    batch_item_tokens += int(item_tok)
                    saw_item_tokens = True
                vectors.append(
                    validate_and_normalize_vector(
                        vals,
                        expected_dimensions=target_dims,
                        normalize=self._settings.gemini_embedding_normalize,
                    )
                )
            if not (isinstance(meta_prompt, (int, float)) and meta_prompt > 0) and saw_item_tokens:
                total_prompt_tokens += batch_item_tokens
                saw_token_usage = True

        latency_ms = (time.perf_counter() - started) * 1000.0
        log_ai_event(
            self._logger,
            logging.INFO,
            provider="gemini",
            operation="embed_texts",
            status="ok",
            request_id=req_id,
            tenant_id=tenant_id,
            model=target_model,
            latency_ms=latency_ms,
            retries=total_retries,
            task_type=task_type,
            count=len(vectors),
            dimensions=target_dims,
            prompt_tokens=total_prompt_tokens if saw_token_usage else None,
            extra_secrets=(self._settings.gemini_api_key,),
        )
        return EmbeddingBatchResult(
            vectors=vectors,
            model=target_model,
            dimensions=target_dims,
            normalized=self._settings.gemini_embedding_normalize,
            latency_ms=latency_ms,
            retries=total_retries,
            request_id=req_id,
            prompt_tokens=total_prompt_tokens if saw_token_usage else None,
        )

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        title: Optional[str] = None,
        tenant_id: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> EmbeddingBatchResult:
        return self.embed_texts(
            texts,
            task_type="RETRIEVAL_DOCUMENT",
            batch_size=batch_size,
            title=title,
            tenant_id=tenant_id,
            request_id=request_id,
        )

    def embed_document(
        self,
        text: str,
        *,
        title: Optional[str] = None,
        tenant_id: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> List[float]:
        result = self.embed_documents(
            [text],
            title=title,
            tenant_id=tenant_id,
            request_id=request_id,
        )
        return result.vectors[0]

    def embed_query(
        self,
        query: str,
        *,
        tenant_id: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> List[float]:
        result = self.embed_texts(
            [query],
            task_type="RETRIEVAL_QUERY",
            tenant_id=tenant_id,
            request_id=request_id,
        )
        return result.vectors[0]
