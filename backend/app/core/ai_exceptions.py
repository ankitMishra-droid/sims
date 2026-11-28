"""Normalized AI service exception hierarchy and provider error classifiers."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
import re
from typing import Any, Optional

from google.genai import errors as genai_errors
from qdrant_client.http import exceptions as qdrant_exceptions


class AIErrorCode(str, Enum):
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    PROVIDER_UNCONFIGURED = "PROVIDER_UNCONFIGURED"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INVALID_MODEL = "INVALID_MODEL"
    RATE_LIMIT_RETRYABLE = "RATE_LIMIT_RETRYABLE"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    CONTEXT_LENGTH_EXCEEDED = "CONTEXT_LENGTH_EXCEEDED"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    INVALID_REQUEST = "INVALID_REQUEST"
    RESPONSE_EMPTY = "RESPONSE_EMPTY"
    RESPONSE_BLOCKED = "RESPONSE_BLOCKED"
    INVALID_EMBEDDING = "INVALID_EMBEDDING"
    COLLECTION_MISMATCH = "COLLECTION_MISMATCH"
    TENANT_ISOLATION_VIOLATION = "TENANT_ISOLATION_VIOLATION"
    VECTOR_STORE_ERROR = "VECTOR_STORE_ERROR"
    PROVIDER_UNKNOWN_ERROR = "PROVIDER_UNKNOWN_ERROR"
    INSUFFICIENT_AI_CREDITS = "INSUFFICIENT_AI_CREDITS"
    TENANT_QUOTA_EXCEEDED = "TENANT_QUOTA_EXCEEDED"
    DUPLICATE_INFLIGHT_REQUEST = "DUPLICATE_INFLIGHT_REQUEST"
    AI_ACCOUNT_SUSPENDED = "AI_ACCOUNT_SUSPENDED"


class AIServiceError(Exception):
    """Base normalized exception raised across all SIMS AI integrations."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        error_code: AIErrorCode,
        http_status: int = 502,
        retryable: bool = False,
        retry_after_seconds: Optional[float] = None,
        safe_detail: Optional[str] = None,
        provider_status: Optional[str] = None,
        provider_error_code: Optional[int] = None,
        exception_type: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.error_code = error_code
        self.http_status = http_status
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.safe_detail = safe_detail or message
        self.provider_status = provider_status
        self.provider_error_code = provider_error_code
        self.exception_type = exception_type


class AIConfigurationError(AIServiceError):
    def __init__(
        self,
        message: str,
        *,
        provider: str = "config",
        error_code: AIErrorCode = AIErrorCode.CONFIGURATION_ERROR,
        safe_detail: Optional[str] = None,
        provider_status: Optional[str] = None,
        provider_error_code: Optional[int] = None,
        exception_type: Optional[str] = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            error_code=error_code,
            http_status=503,
            retryable=False,
            safe_detail=safe_detail
            or "AI assistant provider configuration needs attention. Your core inventory operations are unaffected.",
            provider_status=provider_status,
            provider_error_code=provider_error_code,
            exception_type=exception_type,
        )


class AIAuthenticationError(AIServiceError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        error_code: AIErrorCode = AIErrorCode.AUTHENTICATION_ERROR,
        provider_status: Optional[str] = None,
        provider_error_code: Optional[int] = None,
        exception_type: Optional[str] = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            error_code=error_code,
            http_status=503,
            retryable=False,
            safe_detail="AI provider authentication or access permission failed. Your inventory operations are still available.",
            provider_status=provider_status,
            provider_error_code=provider_error_code,
            exception_type=exception_type,
        )


class AIRateLimitError(AIServiceError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        retryable: bool,
        retry_after_seconds: Optional[float] = None,
        error_code: Optional[AIErrorCode] = None,
        provider_status: Optional[str] = None,
        provider_error_code: Optional[int] = 429,
        exception_type: Optional[str] = None,
    ) -> None:
        resolved_code = error_code or (
            AIErrorCode.RATE_LIMIT_RETRYABLE if retryable else AIErrorCode.QUOTA_EXHAUSTED
        )
        safe_msg = (
            "The AI assistant is temporarily unavailable due to provider quota restrictions. Your inventory operations are still available."
            if resolved_code == AIErrorCode.QUOTA_EXHAUSTED
            else "The AI assistant is temporarily busy due to provider rate limits. Your inventory operations are still available. Please try again shortly."
        )
        super().__init__(
            message,
            provider=provider,
            error_code=resolved_code,
            http_status=429,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
            safe_detail=safe_msg,
            provider_status=provider_status,
            provider_error_code=provider_error_code,
            exception_type=exception_type,
        )


class AIQuotaExhaustedError(AIRateLimitError):
    """Raised when Gemini API quota is exhausted or active quota cooldown blocks retries."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "gemini",
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            retryable=False,
            retry_after_seconds=retry_after_seconds,
            error_code=AIErrorCode.QUOTA_EXHAUSTED,
            provider_status="RESOURCE_EXHAUSTED",
        )


class AITransientError(AIServiceError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        error_code: AIErrorCode = AIErrorCode.TRANSIENT_ERROR,
        retry_after_seconds: Optional[float] = None,
        retryable: bool = True,
        provider_status: Optional[str] = None,
        provider_error_code: Optional[int] = None,
        exception_type: Optional[str] = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            error_code=error_code,
            http_status=503,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
            safe_detail="The AI assistant is temporarily unavailable. Your inventory operations are still available. Please try again shortly.",
            provider_status=provider_status,
            provider_error_code=provider_error_code,
            exception_type=exception_type,
        )


class AICircuitOpenError(AITransientError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            error_code=AIErrorCode.CIRCUIT_OPEN,
            retry_after_seconds=retry_after_seconds,
            retryable=True,
            provider_status="CIRCUIT_OPEN",
        )


class AIInvalidRequestError(AIServiceError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        error_code: AIErrorCode = AIErrorCode.INVALID_REQUEST,
        provider_status: Optional[str] = None,
        provider_error_code: Optional[int] = None,
        exception_type: Optional[str] = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            error_code=error_code,
            http_status=400,
            retryable=False,
            safe_detail=message,
            provider_status=provider_status,
            provider_error_code=provider_error_code,
            exception_type=exception_type,
        )


class QdrantCollectionMismatchError(AIServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            provider="qdrant",
            error_code=AIErrorCode.COLLECTION_MISMATCH,
            http_status=500,
            retryable=False,
        )


class TenantIsolationError(AIServiceError):
    def __init__(self, message: str, *, provider: str = "qdrant") -> None:
        super().__init__(
            message,
            provider=provider,
            error_code=AIErrorCode.TENANT_ISOLATION_VIOLATION,
            http_status=403,
            retryable=False,
        )


class AICreditError(AIServiceError):
    """Raised cleanly when customer workspace credits or account status prevent execution."""

    def __init__(
        self,
        message: str,
        *,
        error_code: AIErrorCode = AIErrorCode.INSUFFICIENT_AI_CREDITS,
        http_status: int = 402,
        retryable: bool = False,
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        super().__init__(
            message,
            provider="billing",
            error_code=error_code,
            http_status=http_status,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
            safe_detail=message,
        )


class AITenantQuotaError(AIServiceError):
    """Raised cleanly when tenant workspace AI usage limits (RPM, daily requests/tokens, size) are exceeded."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: Optional[float] = 60.0,
        error_code: AIErrorCode = AIErrorCode.TENANT_QUOTA_EXCEEDED,
    ) -> None:
        super().__init__(
            message,
            provider="policy",
            error_code=error_code,
            http_status=429,
            retryable=True,
            retry_after_seconds=retry_after_seconds,
            safe_detail=message,
        )


def parse_retry_after(value: Any) -> Optional[float]:
    """Parse HTTP Retry-After header (seconds or IMF-fixdate) into non-negative float seconds."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
        return max(0.0, seconds)
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(raw)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        delta = (target - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)
    except (TypeError, ValueError):
        return None


def _extract_retry_after_from_response(response: Any) -> Optional[float]:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        header_val = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    return parse_retry_after(header_val)


def _extract_retry_delay_from_details(text: str) -> Optional[float]:
    match = re.search(
        r"(?:retry\s*(?:in|after)|retrydelay['\":\s]*)\s*([0-9]+(?:\.[0-9]+)?)\s*s?",
        text,
        re.IGNORECASE,
    )
    if match:
        try:
            return max(0.0, float(match.group(1)))
        except ValueError:
            return None
    return None


def _is_timeout_exception(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    if isinstance(exc, TimeoutError) or "timeout" in name:
        return True
    module = type(exc).__module__.lower()
    return ("httpx" in module or "httpcore" in module) and "timeout" in name


def _is_connection_exception(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    if isinstance(exc, ConnectionError):
        return True
    return any(
        token in name
        for token in (
            "connecterror",
            "networkerror",
            "remoteprotocolerror",
            "pooltimeout",
            "sslerror",
            "proxyerror",
        )
    )


def classify_gemini_error(exc: Exception) -> AIServiceError:
    """Map raw google-genai SDK / transport exceptions to normalized AIServiceError."""
    if isinstance(exc, AIServiceError):
        return exc

    exc_type = type(exc).__name__

    if _is_timeout_exception(exc):
        return AITransientError(
            f"Gemini request timed out ({exc_type}).",
            provider="gemini",
            error_code=AIErrorCode.TIMEOUT_ERROR,
            provider_status="TIMEOUT",
            exception_type=exc_type,
        )
    if _is_connection_exception(exc) or isinstance(exc, OSError):
        return AITransientError(
            f"Gemini network connection failed ({exc_type}).",
            provider="gemini",
            error_code=AIErrorCode.TRANSIENT_ERROR,
            provider_status="CONNECTION_ERROR",
            exception_type=exc_type,
        )

    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", 0) or 0
        status_str = (getattr(exc, "status", "") or "").upper() or None
        msg = getattr(exc, "message", "") or str(exc)
        details_text = f"{status_str or ''} {msg} {getattr(exc, 'details', '')}"
        lowered = details_text.lower()
        retry_after = _extract_retry_after_from_response(getattr(exc, "response", None))
        if retry_after is None:
            retry_after = _extract_retry_delay_from_details(details_text)

        if code == 401 or any(
            k in lowered
            for k in (
                "api_key_invalid",
                "api key not valid",
                "invalid api key",
                "unauthenticated",
            )
        ):
            return AIAuthenticationError(
                "Gemini API key authentication failed. Verify GEMINI_API_KEY configuration.",
                provider="gemini",
                error_code=AIErrorCode.AUTHENTICATION_ERROR,
                provider_status=status_str or "UNAUTHENTICATED",
                provider_error_code=code or 401,
                exception_type=exc_type,
            )

        if code == 403 or "permission_denied" in lowered:
            return AIAuthenticationError(
                "Gemini API key lacks permission for this model/project.",
                provider="gemini",
                error_code=AIErrorCode.PERMISSION_DENIED,
                provider_status=status_str or "PERMISSION_DENIED",
                provider_error_code=code or 403,
                exception_type=exc_type,
            )

        if code == 404 or any(
            k in lowered
            for k in (
                "not found for api version",
                "no longer available",
                "is not supported for generatecontent",
                "model not found",
            )
        ):
            return AIConfigurationError(
                f"Configured Gemini model is unavailable or invalid (status={code or 404}): {msg[:160]}",
                provider="gemini",
                error_code=AIErrorCode.INVALID_MODEL,
                safe_detail="Configured Gemini model is unavailable or unsupported for this project.",
                provider_status=status_str or "NOT_FOUND",
                provider_error_code=code or 404,
                exception_type=exc_type,
            )

        if code == 429 or "resource_exhausted" in lowered or "rate limit" in lowered:
            # `limit: 0` or `limit=0` ALWAYS indicates disabled/zero tier quota even if metric mentions per-minute
            zero_limit = "limit: 0" in lowered or "limit=0" in lowered
            daily_or_billing = any(
                marker in lowered
                for marker in (
                    "perday",
                    "per_day",
                    "daily quota",
                    "billing",
                )
            )
            generic_quota_exhausted = (
                "exceeded your current quota" in lowered
                and "perminute" not in lowered
                and "per_minute" not in lowered
                and "rpm" not in lowered
                and "tpm" not in lowered
            )
            if zero_limit or daily_or_billing or generic_quota_exhausted:
                return AIRateLimitError(
                    "Gemini quota exhausted for the active plan/project.",
                    provider="gemini",
                    retryable=False,
                    retry_after_seconds=retry_after,
                    error_code=AIErrorCode.QUOTA_EXHAUSTED,
                    provider_status=status_str or "RESOURCE_EXHAUSTED",
                    provider_error_code=code or 429,
                    exception_type=exc_type,
                )
            if retry_after is not None and retry_after > 120.0:
                return AIRateLimitError(
                    "Gemini rate limit exceeded with long retry window.",
                    provider="gemini",
                    retryable=False,
                    retry_after_seconds=retry_after,
                    error_code=AIErrorCode.QUOTA_EXHAUSTED,
                    provider_status=status_str or "RESOURCE_EXHAUSTED",
                    provider_error_code=code or 429,
                    exception_type=exc_type,
                )
            return AIRateLimitError(
                "Gemini temporary rate limit reached.",
                provider="gemini",
                retryable=True,
                retry_after_seconds=retry_after,
                error_code=AIErrorCode.RATE_LIMIT_RETRYABLE,
                provider_status=status_str or "RESOURCE_EXHAUSTED",
                provider_error_code=code or 429,
                exception_type=exc_type,
            )

        if code in (408, 504) or (status_str == "DEADLINE_EXCEEDED"):
            return AITransientError(
                f"Gemini request exceeded server deadline (status={code or 504}).",
                provider="gemini",
                error_code=AIErrorCode.TIMEOUT_ERROR,
                retry_after_seconds=retry_after,
                provider_status=status_str or "DEADLINE_EXCEEDED",
                provider_error_code=code or 504,
                exception_type=exc_type,
            )

        if code >= 500 or status_str in ("UNAVAILABLE", "INTERNAL", "ABORTED"):
            return AITransientError(
                f"Gemini service temporarily unavailable (status={code or '5xx'} {status_str or ''}).".strip(),
                provider="gemini",
                error_code=AIErrorCode.TRANSIENT_ERROR,
                retry_after_seconds=retry_after,
                provider_status=status_str or "UNAVAILABLE",
                provider_error_code=code or 503,
                exception_type=exc_type,
            )

        if any(
            k in lowered
            for k in (
                "token count exceeds",
                "maximum context",
                "input token limit",
                "exceeds the maximum number of tokens",
                "payload size exceeds",
            )
        ):
            return AIInvalidRequestError(
                "Gemini prompt exceeded model context/token limit.",
                provider="gemini",
                error_code=AIErrorCode.CONTEXT_LENGTH_EXCEEDED,
                provider_status=status_str or "INVALID_ARGUMENT",
                provider_error_code=code or 400,
                exception_type=exc_type,
            )

        if 400 <= code < 500:
            return AIInvalidRequestError(
                f"Gemini rejected request (status={code}): {msg[:200]}",
                provider="gemini",
                provider_status=status_str or "INVALID_ARGUMENT",
                provider_error_code=code,
                exception_type=exc_type,
            )

    # Unknown SDK/internal error: do NOT mask as transient or blindly retry
    return AIServiceError(
        f"Unexpected Gemini provider/client error ({exc_type}).",
        provider="gemini",
        error_code=AIErrorCode.PROVIDER_UNKNOWN_ERROR,
        http_status=502,
        retryable=False,
        safe_detail="The AI assistant encountered an unexpected provider error. Your inventory operations are still available.",
        exception_type=exc_type,
    )


def classify_qdrant_error(exc: Exception) -> AIServiceError:
    """Map raw Qdrant client / transport exceptions to normalized AIServiceError."""
    if isinstance(exc, AIServiceError):
        return exc

    exc_type = type(exc).__name__
    if _is_timeout_exception(exc):
        return AITransientError(
            "Qdrant request timed out.",
            provider="qdrant",
            error_code=AIErrorCode.TIMEOUT_ERROR,
            exception_type=exc_type,
        )
    if _is_connection_exception(exc) or isinstance(exc, OSError):
        return AITransientError(
            "Qdrant network connection failed.",
            provider="qdrant",
            error_code=AIErrorCode.TRANSIENT_ERROR,
            exception_type=exc_type,
        )

    if isinstance(exc, qdrant_exceptions.UnexpectedResponse):
        status_code = getattr(exc, "status_code", 0) or 0
        reason = getattr(exc, "reason_phrase", "") or ""
        retry_after = parse_retry_after(
            (getattr(exc, "headers", None) or {}).get("retry-after")
        )
        if status_code == 401:
            return AIAuthenticationError(
                "Qdrant authentication failed. Verify QDRANT_API_KEY configuration.",
                provider="qdrant",
                error_code=AIErrorCode.AUTHENTICATION_ERROR,
                provider_error_code=401,
                exception_type=exc_type,
            )
        if status_code == 403:
            return AIAuthenticationError(
                "Qdrant access denied. Verify QDRANT_API_KEY permissions.",
                provider="qdrant",
                error_code=AIErrorCode.PERMISSION_DENIED,
                provider_error_code=403,
                exception_type=exc_type,
            )
        if status_code == 429:
            return AIRateLimitError(
                "Qdrant rate limit reached.",
                provider="qdrant",
                retryable=retry_after is None or retry_after <= 60.0,
                retry_after_seconds=retry_after,
                provider_error_code=429,
                exception_type=exc_type,
            )
        if status_code in (400, 404, 409, 422):
            return AIInvalidRequestError(
                f"Qdrant rejected request (status={status_code} {reason}).".strip(),
                provider="qdrant",
                provider_error_code=status_code,
                exception_type=exc_type,
            )
        if status_code >= 500 or status_code == 408:
            return AITransientError(
                f"Qdrant service temporarily unavailable (status={status_code}).",
                provider="qdrant",
                retry_after_seconds=retry_after,
                provider_error_code=status_code,
                exception_type=exc_type,
            )

    if isinstance(exc, qdrant_exceptions.ResponseHandlingException):
        return AITransientError(
            "Qdrant response handling error.",
            provider="qdrant",
            exception_type=exc_type,
        )

    return AIServiceError(
        f"Qdrant operation failed ({exc_type}).",
        provider="qdrant",
        error_code=AIErrorCode.VECTOR_STORE_ERROR,
        http_status=503,
        retryable=False,
        exception_type=exc_type,
    )
