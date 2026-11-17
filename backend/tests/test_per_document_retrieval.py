"""Per-document retrieval: fair merge, one embedding, caller scoping."""

from __future__ import annotations

from typing import Any

import pytest

from app import agents, db, search
from app.store import get_store


@pytest.fixture()
def two_documents():
    db.init_db()
    ids: list[str] = []
    for name, text in (("alpha.txt", "alpha unique evidence"), ("beta.txt", "beta unique evidence")):
        document_id = db.create_document(
            filename=name,
            stored_filename=name,
            content_type="text/plain",
            size_bytes=len(text),
            uploaded_by="test",
            content_hash=f"per-doc-{name}",
        )
        db.update_document(document_id, status="completed", chunks_count=1)
        db.insert_chunks(
            [
                {
                    "id": f"chunk-{document_id}",
                    "document_id": document_id,
                    "chunk_index": 0,
                    "text": text,
                    "token_count": 3,
                    "metadata": {},
                }
            ]
        )
        ids.append(document_id)
    search.clear_cache()
    yield ids
    for document_id in ids:
        db.delete_chunks_by_document(document_id)
        db.delete_document(document_id)
        get_store().delete_document(document_id)
    search.clear_cache()


def _hit(document_id: str, score: float, suffix: str = "0") -> dict[str, Any]:
    return {
        "chunk_id": f"chunk-{document_id}-{suffix}",
        "document_id": document_id,
        "document_filename": document_id,
        "chunk_index": 0,
        "text": f"evidence from {document_id}",
        "score": score,
        "original_score": score,
        "coverage": 1.0,
        "metadata": {},
    }


def test_per_document_search_calls_each_document_once_and_embeds_once(
    monkeypatch: pytest.MonkeyPatch, two_documents: list[str]
) -> None:
    alpha, beta = two_documents
    calls: list[list[str] | None] = []
    embedded: list[str] = []

    def fake_uncached(
        query: str,
        *,
        top_k: int,
        search_type: str,
        document_ids: list[str] | None,
        rerank: bool,
        query_vector: Any = None,
    ) -> list[dict[str, Any]]:
        calls.append(document_ids)
        assert query_vector is not None
        document_id = (document_ids or [""])[0]
        return [_hit(document_id, 0.9 if document_id == alpha else 0.4)]

    class FakeEmbedder:
        def embed_one(self, text: str) -> Any:
            embedded.append(text)
            return [0.1, 0.2]

    monkeypatch.setattr(search, "_hybrid_search_uncached", fake_uncached)
    monkeypatch.setattr(search, "get_embedder", lambda: FakeEmbedder())

    results = search.per_document_search("alpha beta", top_k=5, per_document_top_k=1)

    assert calls == [[alpha], [beta]]
    assert embedded == ["alpha beta"]
    assert [hit["document_id"] for hit in results] == [alpha, beta]
    assert [hit["score"] for hit in results] == [0.9, 0.4]


def test_per_document_search_honours_explicit_document_ids(
    monkeypatch: pytest.MonkeyPatch, two_documents: list[str]
) -> None:
    alpha, beta = two_documents
    calls: list[list[str] | None] = []

    def fake_uncached(
        query: str,
        *,
        top_k: int,
        search_type: str,
        document_ids: list[str] | None,
        rerank: bool,
        query_vector: Any = None,
    ) -> list[dict[str, Any]]:
        calls.append(document_ids)
        return [_hit((document_ids or [""])[0], 0.7)]

    monkeypatch.setattr(search, "_hybrid_search_uncached", fake_uncached)
    monkeypatch.setattr(search, "get_embedder", lambda: _DummyEmbedder())

    search.per_document_search(
        "alpha", top_k=5, per_document_top_k=1, document_ids=[beta]
    )
    assert calls == [[beta]]


def test_per_document_search_merges_duplicate_chunks_by_best_score(
    monkeypatch: pytest.MonkeyPatch, two_documents: list[str]
) -> None:
    alpha, beta = two_documents
    shared = _hit(alpha, 0.2, "shared")
    shared_better = _hit(alpha, 0.95, "shared")
    shared_better["document_id"] = alpha

    def fake_uncached(
        query: str,
        *,
        top_k: int,
        search_type: str,
        document_ids: list[str] | None,
        rerank: bool,
        query_vector: Any = None,
    ) -> list[dict[str, Any]]:
        document_id = (document_ids or [""])[0]
        return [shared if document_id == beta else shared_better]

    monkeypatch.setattr(search, "_hybrid_search_uncached", fake_uncached)
    monkeypatch.setattr(search, "get_embedder", lambda: _DummyEmbedder())

    results = search.per_document_search("alpha", top_k=5, per_document_top_k=1)
    assert len(results) == 1
    assert results[0]["score"] == 0.95


def test_retriever_uses_per_document_search(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_per_document(
        query: str,
        *,
        top_k: int,
        search_type: str,
        document_ids: list[str] | None,
        rerank: bool,
    ) -> list[dict[str, Any]]:
        seen.update(query=query, top_k=top_k, document_ids=document_ids)
        return [_hit("doc-1", 0.8)]

    monkeypatch.setattr(agents, "per_document_search", fake_per_document)
    chunks, elapsed = agents.retrieve(
        {"sub_queries": ["hello"], "search_strategy": "hybrid"},
        top_k=3,
        document_ids=["doc-1"],
    )
    assert seen == {"query": "hello", "top_k": 3, "document_ids": ["doc-1"]}
    assert [chunk["chunk_id"] for chunk in chunks] == ["chunk-doc-1-0"]
    assert elapsed >= 0


class _DummyEmbedder:
    def embed_one(self, text: str) -> Any:
        return [0.1, 0.2]
