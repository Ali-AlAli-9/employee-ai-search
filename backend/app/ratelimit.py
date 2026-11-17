"""In-memory per-client rate limiting for the expensive endpoints.

The free instance runs one process, so a token bucket per (scope, client IP) is
enough: no Redis, no extra service. Each endpoint gets its own bucket, so a
burst of searches cannot lock a user out of chat.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from .config import settings

_PRUNE_THRESHOLD = 1024


@dataclass
class TokenBucket:
    """A bucket that refills continuously at ``refill_per_second``."""

    capacity: float
    refill_per_second: float
    tokens: float | None = None
    updated: float | None = None

    def __post_init__(self) -> None:
        if self.tokens is None:
            self.tokens = self.capacity
        if self.updated is None:
            self.updated = time.monotonic()

    def _refill(self, now: float) -> None:
        previous = self.updated if self.updated is not None else now
        elapsed = max(0.0, now - previous)
        self.tokens = min(
            self.capacity, (self.tokens or 0.0) + elapsed * self.refill_per_second
        )
        self.updated = now

    def consume(self, now: float | None = None, amount: float = 1.0) -> tuple[bool, float]:
        """Return ``(allowed, retry_after_seconds)``."""
        moment = time.monotonic() if now is None else now
        self._refill(moment)
        if (self.tokens or 0.0) >= amount:
            self.tokens = (self.tokens or 0.0) - amount
            return True, 0.0
        missing = amount - (self.tokens or 0.0)
        if self.refill_per_second <= 0:
            return False, 60.0
        return False, missing / self.refill_per_second


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, name: str = "default"):
        self.limit = max(0, int(limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self.name = name
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def consume(
        self, key: str, now: float | None = None, amount: float = 1.0
    ) -> tuple[bool, float]:
        if self.limit <= 0:
            return True, 0.0
        moment = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(
                    capacity=float(self.limit),
                    refill_per_second=self.limit / self.window_seconds,
                )
                self._buckets[key] = bucket
            allowed, retry_after = bucket.consume(moment, amount)
            if len(self._buckets) > _PRUNE_THRESHOLD:
                self._prune(moment)
        return allowed, retry_after

    def _prune(self, now: float) -> None:
        cutoff = now - 2 * self.window_seconds
        stale = [
            key
            for key, bucket in self._buckets.items()
            if (bucket.updated or 0.0) < cutoff
        ]
        for key in stale:
            del self._buckets[key]

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


_limiters: dict[str, RateLimiter] = {}
_limiters_lock = threading.Lock()


def _configured_limit(scope: str) -> int:
    return {
        "search": settings.rate_limit_search_per_minute,
        "chat": settings.rate_limit_chat_per_minute,
        "upload": settings.rate_limit_upload_per_minute,
        "llm_verify": settings.rate_limit_llm_verify_per_minute,
        "auth": settings.rate_limit_auth_per_minute,
        "admin": settings.rate_limit_admin_per_minute,
    }.get(scope, 60)


def get_limiter(scope: str) -> RateLimiter:
    with _limiters_lock:
        limiter = _limiters.get(scope)
        if limiter is None:
            limiter = RateLimiter(_configured_limit(scope), name=scope)
            _limiters[scope] = limiter
        return limiter


def reset_limiters() -> None:
    with _limiters_lock:
        _limiters.clear()


def client_ip(request: Request) -> str:
    """Last trusted ``X-Forwarded-For`` hop, or the socket peer.

    Render appends the visitor as the final hop. Trusting the first hop instead
    would let any caller forge a fresh rate-limit bucket with one header edit.
    Direct deployments should set ``TRUST_PROXY_HEADERS=0`` so the header is
    ignored completely.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str):
    """FastAPI dependency factory for one endpoint scope."""

    def dependency(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        allowed, retry_after = get_limiter(scope).consume(client_ip(request))
        if allowed:
            return
        seconds = max(1, int(math.ceil(retry_after)))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many {scope} requests. Try again in {seconds}s.",
            headers={"Retry-After": str(seconds)},
        )

    return dependency
