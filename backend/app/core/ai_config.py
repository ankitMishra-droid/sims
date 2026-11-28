"""Centralized configuration for Gemini AI and Qdrant vector infrastructure."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import os
import re
from typing import Mapping, Optional, Tuple
from urllib.parse import urlparse

from .ai_exceptions import AIConfigurationError, AIErrorCode

_PLACEHOLDER_PREFIXES = (
    "your_",
    "your-",
    "replace_",
    "replace-",
    "changeme",
    "example",
    "<your",
    "placeholder",
)
_COLLECTION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,127}$")
DEFAULT_GEMINI_LLM_MODEL = "gemini-3.5-flash-lite"
DEFAULT_GEMINI_LLM_FALLBACKS: Tuple[str, ...] = ("gemini-3.1-flash-lite", "gemini-3.8-flash")


def _parse_bool(raw: Optional[str], default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    normalized = raw.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise AIConfigurationError(
        f"Invalid boolean configuration value: {raw!r}",
        provider="config",
    )


def _parse_int(raw: Optional[str], default: int, *, name: str, min_val: int, max_val: int) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        val = int(raw.strip())
    except ValueError as exc:
        raise AIConfigurationError(
            f"Configuration {name} must be an integer.",
            provider="config",
        ) from exc
    if val < min_val or val > max_val:
        raise AIConfigurationError(
            f"Configuration {name} must be between {min_val} and {max_val}.",
            provider="config",
        )
    return val


def _parse_float(raw: Optional[str], default: float, *, name: str, min_val: float, max_val: float) -> float:
    if raw is None or raw.strip() == "":
        return default
    try:
        val = float(raw.strip())
    except ValueError as exc:
        raise AIConfigurationError(
            f"Configuration {name} must be a number.",
            provider="config",
        ) from exc
    if val < min_val or val > max_val:
        raise AIConfigurationError(
            f"Configuration {name} must be between {min_val} and {max_val}.",
            provider="config",
        )
    return val


def _clean_secret(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    val = raw.strip()
    if not val:
        return None
    lowered = val.lower()
    if any(lowered.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
        return None
    return val


def _parse_csv(raw: Optional[str]) -> Tuple[str, ...]:
    if not raw or not raw.strip():
        return ()
    items = [part.strip() for part in raw.split(",") if part.strip()]
    return tuple(dict.fromkeys(items))


def _sanitize_slug(raw: str, default: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", (raw or "").strip().lower()).strip("_")
    return cleaned or default


@dataclass(frozen=True)
class AIProviderSettings:
    """Validated settings for Gemini LLM, Embeddings, Qdrant, Circuit Breaker & RAG."""

    app_env: str = "development"
    gemini_api_key: Optional[str] = field(default=None, repr=False)
    gemini_llm_model: str = DEFAULT_GEMINI_LLM_MODEL
    gemini_llm_fallback_models: Tuple[str, ...] = DEFAULT_GEMINI_LLM_FALLBACKS
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dimensions: int = 1536
    gemini_embedding_normalize: bool = True
    gemini_embedding_version: str = "v1"
    gemini_timeout_seconds: float = 20.0
    gemini_overall_deadline_seconds: float = 25.0
    gemini_max_retries: int = 2
    gemini_retry_base_seconds: float = 1.0
    gemini_retry_max_seconds: float = 12.0
    gemini_default_temperature: float = 0.2
    gemini_default_max_output_tokens: int = 1024
    gemini_default_thinking_level: Optional[str] = None

    gemini_circuit_breaker_enabled: bool = True
    gemini_circuit_failure_threshold: int = 4
    gemini_circuit_recovery_seconds: float = 30.0
    gemini_circuit_half_open_max_calls: int = 1
    gemini_max_concurrent_requests: int = 8

    qdrant_url: Optional[str] = None
    qdrant_api_key: Optional[str] = field(default=None, repr=False)
    qdrant_require_api_key: Optional[bool] = None
    qdrant_collection_prefix: str = "sims_kb"
    qdrant_collection_version: str = "v1"
    qdrant_collection_name: Optional[str] = None
    qdrant_timeout_seconds: float = 15.0
    qdrant_max_retries: int = 3
    qdrant_prefer_grpc: bool = False
    ai_strict_startup: bool = False

    # Phase 8: Document Ingestion & Retrieval Configuration
    ai_upload_dir: str = "./ai_uploads"
    ai_max_document_mb: int = 15
    ai_max_pdf_pages: int = 150
    ai_chunk_size_chars: int = 900
    ai_chunk_overlap_chars: int = 120
    ai_retrieval_top_k: int = 5
    ai_retrieval_min_score: float = 0.12
    ai_max_conversation_turns: int = 8

    # Phase 9: Credits, Metering & Tenant Quotas (configurable, non-invented defaults)
    gemini_quota_cooldown_seconds: float = 300.0
    ai_credits_enforced: bool = True
    ai_initial_grant_credits: Decimal = Decimal("3000.000")
    ai_initial_grant_approved: bool = True
    ai_default_plan_tier: str = "standard"
    ai_default_rpm_limit: int = 20
    ai_default_daily_request_limit: int = 500
    ai_default_daily_token_limit: int = 250000
    ai_default_max_credits_per_operation: Decimal = Decimal("50.000")
    ai_default_max_concurrent_requests: int = 5

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "AIProviderSettings":
        """Load and validate AI provider settings from environment variables."""
        source: Mapping[str, str] = os.environ if env is None else env

        app_env = _sanitize_slug(source.get("APP_ENV", "development"), "development")
        gemini_api_key = _clean_secret(source.get("GEMINI_API_KEY"))
        gemini_llm_model = (source.get("GEMINI_LLM_MODEL") or DEFAULT_GEMINI_LLM_MODEL).strip()

        raw_fallbacks = source.get("GEMINI_LLM_FALLBACK_MODELS")
        if raw_fallbacks is None:
            gemini_llm_fallback_models = DEFAULT_GEMINI_LLM_FALLBACKS
        elif raw_fallbacks.strip() == "":
            # Empty override intentionally keeps no explicit override OR uses safe fallback unless disabled via "none"
            gemini_llm_fallback_models = ()
        elif raw_fallbacks.strip().lower() == "none":
            gemini_llm_fallback_models = ()
        else:
            gemini_llm_fallback_models = _parse_csv(raw_fallbacks)

        gemini_embedding_model = (source.get("GEMINI_EMBEDDING_MODEL") or "gemini-embedding-001").strip()
        gemini_embedding_dimensions = _parse_int(
            source.get("GEMINI_EMBEDDING_DIMENSIONS"),
            1536,
            name="GEMINI_EMBEDDING_DIMENSIONS",
            min_val=128,
            max_val=3072,
        )
        gemini_embedding_normalize = _parse_bool(source.get("GEMINI_EMBEDDING_NORMALIZE"), True)
        gemini_embedding_version = _sanitize_slug(
            source.get("GEMINI_EMBEDDING_VERSION", "v1"), "v1"
        )
        gemini_timeout_seconds = _parse_float(
            source.get("GEMINI_REQUEST_TIMEOUT_SECONDS") or source.get("GEMINI_TIMEOUT_SECONDS"),
            20.0,
            name="GEMINI_TIMEOUT_SECONDS",
            min_val=1.0,
            max_val=300.0,
        )
        gemini_overall_deadline_seconds = _parse_float(
            source.get("GEMINI_OVERALL_DEADLINE_SECONDS"),
            max(gemini_timeout_seconds, 25.0),
            name="GEMINI_OVERALL_DEADLINE_SECONDS",
            min_val=1.0,
            max_val=300.0,
        )
        gemini_max_retries = _parse_int(
            source.get("GEMINI_MAX_RETRIES"),
            2,
            name="GEMINI_MAX_RETRIES",
            min_val=0,
            max_val=10,
        )
        gemini_retry_base_seconds = _parse_float(
            source.get("GEMINI_INITIAL_BACKOFF_SECONDS") or source.get("GEMINI_RETRY_BASE_SECONDS"),
            1.0,
            name="GEMINI_RETRY_BASE_SECONDS",
            min_val=0.01,
            max_val=30.0,
        )
        gemini_retry_max_seconds = _parse_float(
            source.get("GEMINI_MAX_BACKOFF_SECONDS") or source.get("GEMINI_RETRY_MAX_SECONDS"),
            12.0,
            name="GEMINI_RETRY_MAX_SECONDS",
            min_val=0.1,
            max_val=120.0,
        )
        if gemini_retry_max_seconds < gemini_retry_base_seconds:
            raise AIConfigurationError(
                "GEMINI_RETRY_MAX_SECONDS must be >= GEMINI_RETRY_BASE_SECONDS.",
                provider="config",
            )

        gemini_default_temperature = _parse_float(
            source.get("GEMINI_DEFAULT_TEMPERATURE"),
            0.2,
            name="GEMINI_DEFAULT_TEMPERATURE",
            min_val=0.0,
            max_val=2.0,
        )
        gemini_default_max_output_tokens = _parse_int(
            source.get("GEMINI_DEFAULT_MAX_OUTPUT_TOKENS"),
            1024,
            name="GEMINI_DEFAULT_MAX_OUTPUT_TOKENS",
            min_val=16,
            max_val=65536,
        )
        raw_thinking = (source.get("GEMINI_DEFAULT_THINKING_LEVEL") or "").strip().upper()
        thinking_level = raw_thinking or None
        if thinking_level is not None and thinking_level not in ("MINIMAL", "LOW", "MEDIUM", "HIGH", "XHIGH"):
            raise AIConfigurationError(
                "GEMINI_DEFAULT_THINKING_LEVEL must be one of MINIMAL, LOW, MEDIUM, HIGH, XHIGH.",
                provider="config",
            )

        gemini_circuit_breaker_enabled = _parse_bool(
            source.get("GEMINI_CIRCUIT_BREAKER_ENABLED"), True
        )
        gemini_circuit_failure_threshold = _parse_int(
            source.get("GEMINI_CIRCUIT_FAILURE_THRESHOLD"),
            4,
            name="GEMINI_CIRCUIT_FAILURE_THRESHOLD",
            min_val=1,
            max_val=50,
        )
        gemini_circuit_recovery_seconds = _parse_float(
            source.get("GEMINI_CIRCUIT_RECOVERY_SECONDS"),
            30.0,
            name="GEMINI_CIRCUIT_RECOVERY_SECONDS",
            min_val=1.0,
            max_val=600.0,
        )
        gemini_circuit_half_open_max_calls = _parse_int(
            source.get("GEMINI_CIRCUIT_HALF_OPEN_MAX_CALLS"),
            1,
            name="GEMINI_CIRCUIT_HALF_OPEN_MAX_CALLS",
            min_val=1,
            max_val=10,
        )
        gemini_max_concurrent_requests = _parse_int(
            source.get("GEMINI_MAX_CONCURRENT_REQUESTS"),
            8,
            name="GEMINI_MAX_CONCURRENT_REQUESTS",
            min_val=1,
            max_val=100,
        )

        raw_qdrant_url = (source.get("QDRANT_URL") or "").strip()
        qdrant_url = raw_qdrant_url.rstrip("/") if raw_qdrant_url else None
        if qdrant_url == ":memory":
            qdrant_url = ":memory:"
        if qdrant_url is not None and qdrant_url != ":memory:":
            parsed = urlparse(qdrant_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise AIConfigurationError(
                    "QDRANT_URL must be a valid http:// or https:// URL.",
                    provider="config",
                )

        qdrant_api_key = _clean_secret(source.get("QDRANT_API_KEY"))
        raw_req_key = source.get("QDRANT_REQUIRE_API_KEY")
        qdrant_require_api_key: Optional[bool] = (
            _parse_bool(raw_req_key, True) if raw_req_key is not None and raw_req_key.strip() != "" else None
        )
        qdrant_collection_prefix = _sanitize_slug(
            source.get("QDRANT_COLLECTION_PREFIX", "sims_kb"),
            "sims_kb",
        )
        qdrant_collection_version = _sanitize_slug(
            source.get("QDRANT_COLLECTION_VERSION", "v1"),
            "v1",
        )
        explicit_col = (source.get("QDRANT_COLLECTION_NAME") or "").strip() or None
        if explicit_col is not None and not _COLLECTION_NAME_RE.match(explicit_col):
            raise AIConfigurationError(
                "QDRANT_COLLECTION_NAME contains unsupported characters.",
                provider="config",
            )

        qdrant_timeout_seconds = _parse_float(
            source.get("QDRANT_TIMEOUT_SECONDS"),
            15.0,
            name="QDRANT_TIMEOUT_SECONDS",
            min_val=1.0,
            max_val=120.0,
        )
        qdrant_max_retries = _parse_int(
            source.get("QDRANT_MAX_RETRIES"),
            3,
            name="QDRANT_MAX_RETRIES",
            min_val=0,
            max_val=10,
        )
        qdrant_prefer_grpc = _parse_bool(source.get("QDRANT_PREFER_GRPC"), False)
        ai_strict_startup = _parse_bool(source.get("AI_STRICT_STARTUP"), False)
        ai_upload_dir = (source.get("AI_UPLOAD_DIR") or "./ai_uploads").strip()
        ai_max_document_mb = _parse_int(
            source.get("AI_MAX_DOCUMENT_MB"), 15, name="AI_MAX_DOCUMENT_MB", min_val=1, max_val=100
        )
        ai_max_pdf_pages = _parse_int(
            source.get("AI_MAX_PDF_PAGES"), 150, name="AI_MAX_PDF_PAGES", min_val=1, max_val=1000
        )
        ai_chunk_size_chars = _parse_int(
            source.get("AI_CHUNK_SIZE_CHARS"), 900, name="AI_CHUNK_SIZE_CHARS", min_val=200, max_val=4000
        )
        ai_chunk_overlap_chars = _parse_int(
            source.get("AI_CHUNK_OVERLAP_CHARS"), 120, name="AI_CHUNK_OVERLAP_CHARS", min_val=0, max_val=800
        )
        ai_retrieval_top_k = _parse_int(
            source.get("AI_RETRIEVAL_TOP_K"), 5, name="AI_RETRIEVAL_TOP_K", min_val=1, max_val=20
        )
        ai_retrieval_min_score = _parse_float(
            source.get("AI_RETRIEVAL_MIN_SCORE"), 0.12, name="AI_RETRIEVAL_MIN_SCORE", min_val=0.0, max_val=1.0
        )
        ai_max_conversation_turns = _parse_int(
            source.get("AI_MAX_CONVERSATION_TURNS"), 8, name="AI_MAX_CONVERSATION_TURNS", min_val=2, max_val=30
        )

        gemini_quota_cooldown_seconds = _parse_float(
            source.get("GEMINI_QUOTA_COOLDOWN_SECONDS"),
            300.0,
            name="GEMINI_QUOTA_COOLDOWN_SECONDS",
            min_val=5.0,
            max_val=86400.0,
        )
        ai_credits_enforced = _parse_bool(source.get("AI_CREDITS_ENFORCED"), True)
        raw_grant = source.get("AI_INITIAL_GRANT_CREDITS")
        if raw_grant is not None and raw_grant.strip() != "":
            try:
                ai_initial_grant_credits = max(Decimal("0"), Decimal(raw_grant.strip()))
            except Exception as exc:
                raise AIConfigurationError(
                    "Configuration AI_INITIAL_GRANT_CREDITS must be a non-negative decimal.",
                    provider="config",
                ) from exc
        else:
            ai_initial_grant_credits = Decimal("3000.000")
        ai_initial_grant_approved = _parse_bool(source.get("AI_INITIAL_GRANT_APPROVED"), True)
        ai_default_plan_tier = _sanitize_slug(source.get("AI_DEFAULT_PLAN_TIER", "standard"), "standard")
        ai_default_rpm_limit = _parse_int(
            source.get("AI_DEFAULT_RPM_LIMIT"), 20, name="AI_DEFAULT_RPM_LIMIT", min_val=1, max_val=5000
        )
        ai_default_daily_request_limit = _parse_int(
            source.get("AI_DEFAULT_DAILY_REQUEST_LIMIT"),
            500,
            name="AI_DEFAULT_DAILY_REQUEST_LIMIT",
            min_val=1,
            max_val=1000000,
        )
        ai_default_daily_token_limit = _parse_int(
            source.get("AI_DEFAULT_DAILY_TOKEN_LIMIT"),
            250000,
            name="AI_DEFAULT_DAILY_TOKEN_LIMIT",
            min_val=100,
            max_val=100000000,
        )
        raw_max_op = source.get("AI_DEFAULT_MAX_CREDITS_PER_OP")
        if raw_max_op is not None and raw_max_op.strip() != "":
            try:
                ai_default_max_credits_per_operation = max(Decimal("0.1"), Decimal(raw_max_op.strip()))
            except Exception as exc:
                raise AIConfigurationError(
                    "Configuration AI_DEFAULT_MAX_CREDITS_PER_OP must be numeric.",
                    provider="config",
                ) from exc
        else:
            ai_default_max_credits_per_operation = Decimal("50.000")
        ai_default_max_concurrent_requests = _parse_int(
            source.get("AI_DEFAULT_MAX_CONCURRENT_REQUESTS"),
            5,
            name="AI_DEFAULT_MAX_CONCURRENT_REQUESTS",
            min_val=1,
            max_val=100,
        )

        return cls(
            app_env=app_env,
            gemini_api_key=gemini_api_key,
            gemini_llm_model=gemini_llm_model,
            gemini_llm_fallback_models=gemini_llm_fallback_models,
            gemini_embedding_model=gemini_embedding_model,
            gemini_embedding_dimensions=gemini_embedding_dimensions,
            gemini_embedding_normalize=gemini_embedding_normalize,
            gemini_embedding_version=gemini_embedding_version,
            gemini_timeout_seconds=gemini_timeout_seconds,
            gemini_overall_deadline_seconds=gemini_overall_deadline_seconds,
            gemini_max_retries=gemini_max_retries,
            gemini_retry_base_seconds=gemini_retry_base_seconds,
            gemini_retry_max_seconds=gemini_retry_max_seconds,
            gemini_default_temperature=gemini_default_temperature,
            gemini_default_max_output_tokens=gemini_default_max_output_tokens,
            gemini_default_thinking_level=thinking_level,
            gemini_circuit_breaker_enabled=gemini_circuit_breaker_enabled,
            gemini_circuit_failure_threshold=gemini_circuit_failure_threshold,
            gemini_circuit_recovery_seconds=gemini_circuit_recovery_seconds,
            gemini_circuit_half_open_max_calls=gemini_circuit_half_open_max_calls,
            gemini_max_concurrent_requests=gemini_max_concurrent_requests,
            qdrant_url=qdrant_url,
            qdrant_api_key=qdrant_api_key,
            qdrant_require_api_key=qdrant_require_api_key,
            qdrant_collection_prefix=qdrant_collection_prefix,
            qdrant_collection_version=qdrant_collection_version,
            qdrant_collection_name=explicit_col,
            qdrant_timeout_seconds=qdrant_timeout_seconds,
            qdrant_max_retries=qdrant_max_retries,
            qdrant_prefer_grpc=qdrant_prefer_grpc,
            ai_strict_startup=ai_strict_startup,
            ai_upload_dir=ai_upload_dir,
            ai_max_document_mb=ai_max_document_mb,
            ai_max_pdf_pages=ai_max_pdf_pages,
            ai_chunk_size_chars=ai_chunk_size_chars,
            ai_chunk_overlap_chars=ai_chunk_overlap_chars,
            ai_retrieval_top_k=ai_retrieval_top_k,
            ai_retrieval_min_score=ai_retrieval_min_score,
            ai_max_conversation_turns=ai_max_conversation_turns,
            gemini_quota_cooldown_seconds=gemini_quota_cooldown_seconds,
            ai_credits_enforced=ai_credits_enforced,
            ai_initial_grant_credits=ai_initial_grant_credits,
            ai_initial_grant_approved=ai_initial_grant_approved,
            ai_default_plan_tier=ai_default_plan_tier,
            ai_default_rpm_limit=ai_default_rpm_limit,
            ai_default_daily_request_limit=ai_default_daily_request_limit,
            ai_default_daily_token_limit=ai_default_daily_token_limit,
            ai_default_max_credits_per_operation=ai_default_max_credits_per_operation,
            ai_default_max_concurrent_requests=ai_default_max_concurrent_requests,
        )

    @property
    def is_gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def is_qdrant_configured(self) -> bool:
        return bool(self.qdrant_url)

    @property
    def qdrant_endpoint_host(self) -> Optional[str]:
        if not self.qdrant_url:
            return None
        if self.qdrant_url == ":memory:":
            return "memory"
        parsed = urlparse(self.qdrant_url)
        return parsed.hostname

    @property
    def is_qdrant_cloud(self) -> bool:
        host = (self.qdrant_endpoint_host or "").lower()
        return "qdrant.io" in host or "qdrant.tech" in host

    @property
    def effective_collection_name(self) -> str:
        """Return explicit or versioned collection name aligned with embedding settings."""
        if self.qdrant_collection_name:
            return self.qdrant_collection_name
        model_slug = _sanitize_slug(self.gemini_embedding_model, "emb")
        return (
            f"{self.qdrant_collection_prefix}_{self.app_env}_"
            f"{self.qdrant_collection_version}_{model_slug}_{self.gemini_embedding_dimensions}d"
        )

    def validate_gemini_ready(self) -> None:
        if not self.gemini_api_key:
            raise AIConfigurationError(
                "Gemini API key is not configured.",
                provider="gemini",
                error_code=AIErrorCode.PROVIDER_UNCONFIGURED,
            )
        if not self.gemini_llm_model:
            raise AIConfigurationError(
                "GEMINI_LLM_MODEL must not be empty.",
                provider="gemini",
            )
        if not self.gemini_embedding_model:
            raise AIConfigurationError(
                "GEMINI_EMBEDDING_MODEL must not be empty.",
                provider="gemini",
            )

    def validate_qdrant_ready(self) -> None:
        if not self.qdrant_url:
            raise AIConfigurationError(
                "Qdrant URL is not configured.",
                provider="qdrant",
                error_code=AIErrorCode.PROVIDER_UNCONFIGURED,
            )
        require_key = (
            self.qdrant_require_api_key
            if self.qdrant_require_api_key is not None
            else (self.is_qdrant_cloud or self.qdrant_url.startswith("https://"))
        )
        if require_key and not self.qdrant_api_key:
            raise AIConfigurationError(
                "QDRANT_API_KEY is required for secure/cloud Qdrant endpoints.",
                provider="qdrant",
            )
