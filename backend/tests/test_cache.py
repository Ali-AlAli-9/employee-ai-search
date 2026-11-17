"""Query cache: hits, corpus-version invalidation and copy isolation."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.search import cache_stats, clear_cache, hybrid_search

client = TestClient(app)
ADMIN = {"X-API-Key": "dev-admin-key"}

CORPUS = (
    "Employees receive 20 days of annual leave per year. "
    "Part-time employees accrue leave pro rata. "
    "Remote work is allowed two days per week with manager approval."
)


@pytest.fixture(scope="module")
def corpus():
    response = client.post(
        "/api/v1/documents/upload",
        headers=ADMIN,
        files={"file": ("cache.txt", io.BytesIO(CORPUS.encode()), "text/plain")},
    )
    assert response.status_code == 202, response.text
    document_id = response.json()["document_id"]
    yield document_id
    client.delete(f"/api/v1/documents/{document_id}", headers=ADMIN)


@pytest.fixture(autouse=True)
def clean_cache():
    clear_cache()
    yield
    clear_cache()


def test_second_identical_search_is_a_cache_hit(corpus):
    first = hybrid_search("annual leave days", top_k=5)
    assert first
    stats = cache_stats()
    assert stats["misses"] == 1 and stats["hits"] == 0

    second = hybrid_search("annual leave days", top_k=5)
    assert second == first
    stats = cache_stats()
    assert stats["hits"] == 1
    assert stats["size"] == 1


def test_upload_invalidates_cached_results(corpus):
    assert hybrid_search("annual leave days", top_k=5)

    content = b"Reimbursement for travel is 0.75 SAR per kilometre for field visits."
    response = client.post(
        "/api/v1/documents/upload",
        headers=ADMIN,
        files={"file": ("travel.txt", io.BytesIO(content), "text/plain")},
    )
    assert response.status_code == 202, response.text
    document_id = response.json()["document_id"]
    try:
        after = hybrid_search("travel reimbursement per kilometre", top_k=5)
        assert any("0.75" in item["text"] for item in after)
        assert cache_stats()["misses"] == 2

        hybrid_search("travel reimbursement per kilometre", top_k=5)
        assert cache_stats()["hits"] == 1
    finally:
        client.delete(f"/api/v1/documents/{document_id}", headers=ADMIN)


def test_cache_key_covers_search_options(corpus):
    hybrid_search("annual leave", top_k=5)
    hybrid_search("annual leave", top_k=6)
    stats = cache_stats()
    assert stats["misses"] == 2 and stats["hits"] == 0

    hybrid_search("annual leave", top_k=5)
    assert cache_stats()["hits"] == 1


def test_cached_results_are_isolated_from_callers(corpus):
    first = hybrid_search("annual leave days", top_k=5)
    assert first
    snipped = first[0]["text"]
    first[0]["metadata"]["page_number"] = 99
    first.clear()

    second = hybrid_search("annual leave days", top_k=5)
    assert second
    assert second[0]["text"] == snipped
    assert second[0]["metadata"].get("page_number") != 99
