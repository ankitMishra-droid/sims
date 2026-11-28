"""Safe structured telemetry logging with automatic secret/PII redaction."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Optional

_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_-]{16,}"),
    re.compile(r"AQ\.[0-9A-Za-z._-]{16,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"((?:api[-_]?key|token|secret|password)\s*[=:]\s*)[^\s,;\"']+", re.IGNORECASE),
    re.compile(r"(https?://[^:@/\s]+:)([^@/\s]+)(@)", re.IGNORECASE),
)


def get_ai_logger(component: str) -> logging.Logger:
    """Return namespaced logger under `sims.ai`."""
    logger = logging.getLogger(f"sims.ai.{component}")
    logger.disabled = False
    return logger


def redact_sensitive_text(
    text: str,
    *,
    extra_secrets: Iterable[Optional[str]] = (),
) -> str:
    """Mask API keys, bearer tokens, URL credentials, and explicit secrets in logs."""
    cleaned = text
    for secret in extra_secrets:
        if secret and len(secret) >= 4:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    cleaned = _SECRET_PATTERNS[0].sub("[REDACTED_KEY]", cleaned)
    cleaned = _SECRET_PATTERNS[1].sub("[REDACTED_KEY]", cleaned)
    cleaned = _SECRET_PATTERNS[2].sub(r"\1[REDACTED]", cleaned)
    cleaned = _SECRET_PATTERNS[3].sub(r"\1[REDACTED]", cleaned)
    cleaned = _SECRET_PATTERNS[4].sub(r"\1[REDACTED]\3", cleaned)
    return cleaned


def log_ai_event(
    logger: logging.Logger,
    level: int,
    *,
    provider: str,
    operation: str,
    status: str,
    request_id: Optional[str] = None,
    tenant_id: Optional[int] = None,
    conversation_id: Optional[int] = None,
    model: Optional[str] = None,
    latency_ms: Optional[float] = None,
    retries: int = 0,
    error_code: Optional[str] = None,
    http_status: Optional[int] = None,
    provider_status: Optional[str] = None,
    exception_type: Optional[str] = None,
    extra_secrets: Iterable[Optional[str]] = (),
    **metadata: Any,
) -> None:
    """Emit structured metadata log without raw prompt contents or secrets."""
    payload: dict[str, Any] = {
        "provider": provider,
        "operation": operation,
        "status": status,
        "retries": retries,
    }
    if request_id:
        payload["request_id"] = request_id
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    if model:
        payload["model"] = model
    if latency_ms is not None:
        payload["latency_ms"] = round(latency_ms, 2)
    if error_code:
        payload["error_code"] = error_code
    if http_status is not None:
        payload["http_status"] = http_status
    if provider_status:
        payload["provider_status"] = provider_status
    if exception_type:
        payload["exception_type"] = exception_type

    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, str):
            payload[key] = redact_sensitive_text(value, extra_secrets=extra_secrets)
        else:
            payload[key] = value

    logger.log(level, "ai_event %s", json.dumps(payload, sort_keys=True, default=str))
