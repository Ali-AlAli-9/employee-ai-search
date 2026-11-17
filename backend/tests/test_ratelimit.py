"""Token bucket behaviour and the HTTP 429 path."""

from __future__ import annotations

import io

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app import ratelimit
from app.config import settings
from app.main import app
from app.ratelimit import RateLimiter, TokenBucket

client = TestClient(app)
ADMIN = {"X-API-Key": "dev-admin-key"}


def test_bucket_allows_capacity_then_asks_to_wait():
    bucket = TokenBucket(capacity=2, refill_per_second=1.0, tokens=2.0, updated=0.0)
    assert bucket.consume(now=0.0)[0] is True
    assert bucket.consume(now=0.0)[0] is True
    allowed, retry_after = bucket.consume(now=0.0)
    assert allowed is False
    assert retry_after == pytest.approx(1.0)
    # One second later exactly one token has refilled.
    assert bucket.consume(now=1.0)[0] is True


def test_limiter_keeps_clients_separate():
    limiter = RateLimiter(limit=2, window_seconds=60)
    assert limiter.consume("1.1.1.1", now=0.0)[0]
    assert limiter.consume("1.1.1.1", now=0.0)[0]
    assert limiter.consume("1.1.1.1", now=0.0)[0] is False
    assert limiter.consume("2.2.2.2", now=0.0)[0] is True


def test_zero_limit_disables_the_limiter():
    limiter = RateLimiter(limit=0)
    assert all(limiter.consume("any", now=0.0)[0] for _ in range(5))


def test_stale_buckets_are_pruned():
    limiter = RateLimiter(limit=1, window_seconds=1)
    for index in range(ratelimit._PRUNE_THRESHOLD):
        limiter.consume(f"ip-{index}", now=0.0)
    limiter.consume("fresh", now=10.0)  # crossing the threshold triggers a prune
    assert len(limiter._buckets) == 1


def test_client_ip_uses_the_trusted_last_hop_only_when_enabled():
    request = Request(
        {
            "type": "http",
            "client": ("10.0.0.1", 51234),
            "headers": [(b"x-forwarded-for", b"203.0.113.9, 198.51.100.10")],
        }
    )
    previous = settings.trust_proxy_headers
    try:
        object.__setattr__(settings, "trust_proxy_headers", True)
        assert ratelimit.client_ip(request) == "198.51.100.10"
        object.__setattr__(settings, "trust_proxy_headers", False)
        assert ratelimit.client_ip(request) == "10.0.0.1"
    finally:
        object.__setattr__(settings, "trust_proxy_headers", previous)


def test_upload_endpoint_returns_429_with_retry_after(monkeypatch):
    monkeypatch.setattr(
        ratelimit, "_limiters", {"upload": RateLimiter(limit=2, name="upload")}
    )
    headers = {**ADMIN, "X-Forwarded-For": "203.0.113.9"}
    created: list[str] = []
    for index in range(2):
        response = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={
                "file": (
                    f"limited-{index}.txt",
                    io.BytesIO(f"rate limit payload {index}".encode()),
                    "text/plain",
                )
            },
        )
        assert response.status_code == 202, response.text
        created.append(response.json()["document_id"])

    blocked = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("blocked.txt", io.BytesIO(b"blocked payload"), "text/plain")},
    )
    assert blocked.status_code == 429, blocked.text
    assert float(blocked.headers["Retry-After"]) >= 1

    for document_id in created:
        client.delete(f"/api/v1/documents/{document_id}", headers=ADMIN)
