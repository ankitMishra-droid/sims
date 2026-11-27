from collections import defaultdict, deque
import os
import threading
import time
from typing import Callable, Deque, Dict, Optional

from fastapi import HTTPException, Request, status

_LOCK = threading.Lock()
_BUCKETS: Dict[str, Deque[float]] = defaultdict(deque)


def reset_rate_limits() -> None:
    """Clear in-memory rate limit buckets (primarily for isolated tests)."""
    with _LOCK:
        _BUCKETS.clear()


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> None:
    """Enforce a thread-safe sliding window limit for sensitive endpoints."""
    if os.getenv("SIMS_RATE_LIMIT_ENABLED", "true").lower() == "false":
        return

    now = time.monotonic()
    cutoff = now - window_seconds
    with _LOCK:
        bucket = _BUCKETS[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many authentication attempts. Please wait a moment and try again.",
                headers={"Retry-After": str(window_seconds)},
            )
        bucket.append(now)


def rate_limit(
    scope: str,
    default_max: int = 30,
    window_seconds: int = 60,
    env_var: Optional[str] = None,
) -> Callable:
    """FastAPI dependency factory for sliding-window endpoint rate limiting."""

    def dependency(request: Request) -> None:
        max_req = default_max
        if env_var:
            raw = os.getenv(env_var)
            if raw and raw.isdigit():
                max_req = int(raw)
        client_host = request.client.host if request.client else "testclient"
        key = f"{scope}:{client_host}"
        check_rate_limit(key, max_requests=max_req, window_seconds=window_seconds)

    return dependency
