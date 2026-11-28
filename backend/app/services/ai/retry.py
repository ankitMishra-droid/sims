"""Bounded exponential backoff + jitter + overall deadline retry policy."""

from __future__ import annotations

import random
import threading
import time
from typing import Callable, Optional, Tuple, TypeVar

from ...core.ai_exceptions import AIErrorCode, AIServiceError, AITransientError

T = TypeVar("T")


def compute_backoff_delay(
    *,
    attempt: int,
    base_seconds: float,
    max_seconds: float,
    retry_after_seconds: Optional[float] = None,
    jitter_fn: Optional[Callable[[float, float], float]] = None,
) -> float:
    """Compute bounded exponential backoff with jitter, respecting Retry-After guidance."""
    rng = jitter_fn or random.uniform
    exp_delay = base_seconds * (2 ** max(0, attempt - 1))
    jittered = exp_delay * rng(0.8, 1.2)
    delay = max(jittered, retry_after_seconds or 0.0)
    return max(0.0, min(max_seconds, delay))


def execute_with_retry(
    fn: Callable[[], T],
    *,
    classifier: Callable[[Exception], AIServiceError],
    max_retries: int,
    base_seconds: float,
    max_seconds: float,
    deadline_monotonic: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    jitter_fn: Optional[Callable[[float, float], float]] = None,
    clock_fn: Callable[[], float] = time.monotonic,
    on_retry: Optional[Callable[[int, AIServiceError, float], None]] = None,
) -> Tuple[T, int]:
    """Execute `fn` with bounded retries, overall deadline cutoff, and cancellation support.

    Returns `(result, retries_used)`.
    """
    max_attempts = max(1, 1 + max_retries)
    retries_used = 0

    for attempt in range(1, max_attempts + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise AITransientError(
                "AI request aborted due to service shutdown/cancellation.",
                provider="gemini",
                error_code=AIErrorCode.TIMEOUT_ERROR,
                retryable=False,
            )

        if deadline_monotonic is not None and attempt > 1:
            remaining = deadline_monotonic - clock_fn()
            if remaining <= 0.2:
                raise AITransientError(
                    "Overall AI request deadline expired before retry.",
                    provider="gemini",
                    error_code=AIErrorCode.TIMEOUT_ERROR,
                )

        try:
            return fn(), retries_used
        except Exception as exc:
            classified = classifier(exc)
            if not classified.retryable or attempt >= max_attempts:
                raise classified from exc

            delay = compute_backoff_delay(
                attempt=attempt,
                base_seconds=base_seconds,
                max_seconds=max_seconds,
                retry_after_seconds=classified.retry_after_seconds,
                jitter_fn=jitter_fn,
            )

            if deadline_monotonic is not None:
                remaining = deadline_monotonic - clock_fn()
                # Do not sleep if remaining budget would leave < 0.5s for the next attempt
                if remaining <= 0.6 or delay >= (remaining - 0.5):
                    raise classified from exc
                delay = min(delay, max(0.0, remaining - 0.5))

            retries_used += 1
            if on_retry is not None:
                on_retry(retries_used, classified, delay)

            if delay > 0:
                if cancel_event is not None and sleep_fn is time.sleep:
                    if cancel_event.wait(timeout=delay):
                        raise AITransientError(
                            "AI request cancelled during retry backoff.",
                            provider="gemini",
                            error_code=AIErrorCode.TIMEOUT_ERROR,
                            retryable=False,
                        ) from exc
                else:
                    sleep_fn(delay)

    raise AssertionError("Unreachable retry termination")
