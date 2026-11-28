from collections import defaultdict, deque
import ipaddress
import os
import threading
import time
from typing import Callable, Deque, Dict, Optional

from fastapi import HTTPException, Request, status

_LOCK = threading.Lock()
_BUCKETS: Dict[str, Deque[float]] = defaultdict(deque)
_MAX_TRACKED_BUCKETS = 10_000


def reset_rate_limits() -> None:
    """Clear in-memory rate limit buckets (primarily for isolated tests)."""
    with _LOCK:
        _BUCKETS.clear()


def _prune_stale_buckets_locked(now: float, max_window_seconds: int) -> None:
    cutoff = now - max(max_window_seconds, 60)
    stale = [k for k, q in _BUCKETS.items() if not q or q[-1] <= cutoff]
    for k in stale:
        del _BUCKETS[k]
    if len(_BUCKETS) > _MAX_TRACKED_BUCKETS:
        # Evict oldest least-recently-used keys to bound memory growth under IP floods
        excess = len(_BUCKETS) - (_MAX_TRACKED_BUCKETS // 2)
        ordered = sorted(_BUCKETS.items(), key=lambda item: item[1][-1] if item[1] else 0.0)
        for k, _ in ordered[:excess]:
            del _BUCKETS[k]


def extract_client_ip(request: Request) -> str:
    """Resolve real client IP behind Render/Vercel proxies with validation."""
    if os.getenv("TRUST_PROXY_HEADERS", "true").lower() != "false":
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            candidate = forwarded.split(",")[0].strip()
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            candidate = real_ip.strip()
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass
    return (request.client.host if request.client else "testclient")[:64]


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> None:
    """Enforce a thread-safe sliding window limit for sensitive endpoints."""
    if os.getenv("SIMS_RATE_LIMIT_ENABLED", "true").lower() == "false":
        return

    now = time.monotonic()
    cutoff = now - window_seconds
    with _LOCK:
        if len(_BUCKETS) > 1000:
            _prune_stale_buckets_locked(now, window_seconds)
        bucket = _BUCKETS[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please wait a moment and try again.",
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
        client_host = extract_client_ip(request)
        key = f"{scope}:{client_host}"
        check_rate_limit(key, max_requests=max_req, window_seconds=window_seconds)

    return dependency
