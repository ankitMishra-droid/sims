"""Per-process thread-safe circuit breaker & concurrency guard for AI providers.

Note on deployment scope: State is maintained in memory per worker process. In multi-worker
Render/Gunicorn deployments, each worker maintains independent circuit state; this prevents
individual worker overload while keeping core inventory workflows free of external brokers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
import time
from typing import Callable, Dict, Optional

from ...core.ai_exceptions import (
    AICircuitOpenError,
    AIErrorCode,
    AIQuotaExhaustedError,
    AIServiceError,
    AITransientError,
)

_PROVIDER_OUTAGE_CODES = {
    AIErrorCode.TRANSIENT_ERROR,
    AIErrorCode.TIMEOUT_ERROR,
    AIErrorCode.RATE_LIMIT_RETRYABLE,
    AIErrorCode.QUOTA_EXHAUSTED,
}


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _CircuitBucket:
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: Optional[float] = None
    cooldown_seconds: float = 0.0
    half_open_in_flight: int = 0
    last_error_code: Optional[str] = None


class ProviderCircuitBreaker:
    """Tracks provider/model transient failures cleanly without tripping on bad user inputs."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        failure_threshold: int = 4,
        recovery_seconds: float = 30.0,
        quota_cooldown_seconds: float = 300.0,
        half_open_max_calls: int = 1,
        max_concurrent_requests: int = 8,
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._enabled = enabled
        self._failure_threshold = max(1, failure_threshold)
        self._recovery_seconds = max(1.0, recovery_seconds)
        self._quota_cooldown_seconds = max(0.0, quota_cooldown_seconds)
        self._half_open_max_calls = max(1, half_open_max_calls)
        self._clock = clock_fn
        self._lock = threading.RLock()
        self._buckets: Dict[str, _CircuitBucket] = {}
        self._semaphore = threading.BoundedSemaphore(max(1, max_concurrent_requests))

    def acquire_slot(self, *, key: str, provider: str, wait_timeout: float = 2.0) -> bool:
        """Check circuit state and acquire a bounded concurrency slot cleanly."""
        if self._enabled:
            with self._lock:
                bucket = self._buckets.setdefault(key, _CircuitBucket())
                now = self._clock()
                if bucket.state == CircuitState.OPEN:
                    cooldown = bucket.cooldown_seconds if bucket.cooldown_seconds > 0 else self._recovery_seconds
                    elapsed = now - (bucket.opened_at or now)
                    if elapsed < cooldown:
                        remaining = round(max(1.0, cooldown - elapsed), 1)
                        if bucket.last_error_code == AIErrorCode.QUOTA_EXHAUSTED.value:
                            raise AIQuotaExhaustedError(
                                f"Gemini quota cooldown active for {key} ({remaining}s remaining).",
                                provider=provider,
                                retry_after_seconds=remaining,
                            )
                        raise AICircuitOpenError(
                            f"Circuit breaker OPEN for {key} ({remaining}s remaining).",
                            provider=provider,
                            retry_after_seconds=remaining,
                        )
                    bucket.state = CircuitState.HALF_OPEN
                    bucket.half_open_in_flight = 0

                if bucket.state == CircuitState.HALF_OPEN:
                    if bucket.half_open_in_flight >= self._half_open_max_calls:
                        raise AICircuitOpenError(
                            f"Circuit breaker HALF_OPEN probe limit reached for {key}.",
                            provider=provider,
                            retry_after_seconds=2.0,
                        )
                    bucket.half_open_in_flight += 1

        acquired = self._semaphore.acquire(timeout=max(0.05, wait_timeout))
        if not acquired:
            if self._enabled:
                self._release_half_open_on_abort(key)
            raise AITransientError(
                f"Concurrent {provider} request limit reached; try again shortly.",
                provider=provider,
                error_code=AIErrorCode.RATE_LIMIT_RETRYABLE,
                retry_after_seconds=2.0,
            )
        return True

    def _release_half_open_on_abort(self, key: str) -> None:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket and bucket.state == CircuitState.HALF_OPEN and bucket.half_open_in_flight > 0:
                bucket.half_open_in_flight -= 1

    def release_slot(self) -> None:
        try:
            self._semaphore.release()
        except ValueError:
            pass

    def record_success(self, key: str) -> None:
        with self._lock:
            bucket = self._buckets.setdefault(key, _CircuitBucket())
            bucket.state = CircuitState.CLOSED
            bucket.consecutive_failures = 0
            bucket.opened_at = None
            bucket.cooldown_seconds = 0.0
            bucket.half_open_in_flight = 0
            bucket.last_error_code = None

    def record_failure(self, key: str, error: AIServiceError) -> None:
        if not self._enabled:
            return
        with self._lock:
            bucket = self._buckets.setdefault(key, _CircuitBucket())
            if bucket.state == CircuitState.HALF_OPEN and bucket.half_open_in_flight > 0:
                bucket.half_open_in_flight -= 1

            # Auth, config, invalid models, and invalid user inputs NEVER trip outage breakers
            if error.error_code not in _PROVIDER_OUTAGE_CODES:
                return

            bucket.last_error_code = error.error_code.value
            bucket.consecutive_failures += 1
            if error.error_code == AIErrorCode.QUOTA_EXHAUSTED and self._quota_cooldown_seconds > 0:
                bucket.state = CircuitState.OPEN
                bucket.opened_at = self._clock()
                bucket.cooldown_seconds = max(
                    self._quota_cooldown_seconds,
                    float(error.retry_after_seconds or 0.0),
                )
            elif bucket.state == CircuitState.HALF_OPEN or bucket.consecutive_failures >= self._failure_threshold:
                bucket.state = CircuitState.OPEN
                bucket.opened_at = self._clock()
                bucket.cooldown_seconds = max(
                    self._recovery_seconds,
                    float(error.retry_after_seconds or 0.0),
                )

    def get_snapshot(self, key: str) -> dict[str, object]:
        with self._lock:
            bucket = self._buckets.get(key)
            if not bucket:
                return {
                    "state": CircuitState.CLOSED.value,
                    "consecutive_failures": 0,
                    "last_error_code": None,
                    "retry_after_seconds": 0.0,
                    "quota_cooldown_active": False,
                }
            state = bucket.state
            cooldown = bucket.cooldown_seconds if bucket.cooldown_seconds > 0 else self._recovery_seconds
            retry_after = 0.0
            if state == CircuitState.OPEN and bucket.opened_at is not None:
                elapsed = self._clock() - bucket.opened_at
                if elapsed >= cooldown:
                    state = CircuitState.HALF_OPEN
                else:
                    retry_after = round(max(0.0, cooldown - elapsed), 1)
            return {
                "state": state.value,
                "consecutive_failures": bucket.consecutive_failures,
                "last_error_code": bucket.last_error_code,
                "retry_after_seconds": retry_after,
                "quota_cooldown_active": (
                    bucket.last_error_code == AIErrorCode.QUOTA_EXHAUSTED.value
                    and state == CircuitState.OPEN
                ),
            }

    def reset_key(self, key: str) -> None:
        """Clear cooldown/open breaker state for a single provider bucket (e.g. manual admin recovery)."""
        with self._lock:
            self._buckets.pop(key, None)

    def snapshot_all(self) -> Dict[str, dict[str, object]]:
        with self._lock:
            return {k: self.get_snapshot(k) for k in list(self._buckets.keys())}
