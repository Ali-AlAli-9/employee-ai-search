"""Binary vector store guarantees: round-trip, migration, ranking, deletion."""

from __future__ import annotations

import json
import time

import numpy as np
import pytest

from app.store import LocalVectorStore


def _point(
    point_id: str,
    vector: list[float],
    document_id: str = "doc-a",
    chunk_index: int = 0,
) -> dict:
    return {
        "id": point_id,
        "vector": vector,
        "payload": {
            "document_id": document_id,
            "chunk_index": chunk_index,
            "text": f"text of {point_id}",
            "metadata": {"page_number": None},
            "filename": "doc.txt",
        },
    }


def test_binary_round_trip_preserves_points(tmp_path):
    path = tmp_path / "vectors.npz"
    store = LocalVectorStore(path)
    store.upsert(
        [
            _point("a", [1.0, 0.0, 0.0]),
            _point("b", [0.0, 1.0, 0.0]),
            _point("c", [0.0, 0.0, 1.0]),
        ]
    )
    assert path.exists()
    assert not (tmp_path / "vectors.json").exists()

    reloaded = LocalVectorStore(path)
    assert reloaded.count() == 3
    hits = reloaded.search([1.0, 0.0, 0.0], top_k=3)
    assert [hit[0] for hit in hits] == ["a", "b", "c"]
    assert hits[0][1] == pytest.approx(1.0)
    assert hits[0][2]["document_id"] == "doc-a"
    assert hits[0][2]["metadata"]["page_number"] is None


def test_legacy_json_is_migrated_in_place(tmp_path):
    legacy = tmp_path / "vectors.json"
    legacy.write_text(
        json.dumps(
            {
                "points": [
                    _point("a", [1.0, 0.0]),
                    _point("b", [0.0, 1.0], document_id="doc-b"),
                ]
            }
        ),
        encoding="utf-8",
    )
    store = LocalVectorStore(tmp_path / "vectors.npz", legacy)

    assert store.count() == 2
    assert (tmp_path / "vectors.npz").exists()
    # The JSON file is left in place so a rollback still works.
    assert legacy.exists()
    hits = store.search([0.0, 1.0], top_k=1)
    assert hits[0][0] == "b"
    assert hits[0][2]["document_id"] == "doc-b"


def test_search_orders_by_similarity_and_filters_documents(tmp_path):
    store = LocalVectorStore(tmp_path / "v.npz")
    store.upsert(
        [
            _point("a", [1.0, 0.0, 0.0], document_id="doc-a"),
            _point("b", [0.8, 0.6, 0.0], document_id="doc-b"),
            _point("c", [0.0, 1.0, 0.0], document_id="doc-a"),
        ]
    )

    hits = store.search([1.0, 0.0, 0.0], top_k=5)
    assert [hit[0] for hit in hits] == ["a", "b", "c"]
    assert hits[0][1] > hits[1][1] > hits[2][1]

    filtered = store.search([1.0, 0.0, 0.0], top_k=5, document_ids=["doc-a"])
    assert [hit[0] for hit in filtered] == ["a", "c"]


def test_upsert_replaces_id_and_delete_document_is_scoped(tmp_path):
    store = LocalVectorStore(tmp_path / "v.npz")
    store.upsert([_point("a", [1.0, 0.0], "doc-a"), _point("b", [0.0, 1.0], "doc-b")])
    store.upsert([_point("a", [0.0, 1.0], "doc-a")])
    assert store.count() == 2

    store.delete_document("doc-a")
    assert store.count() == 1
    hits = store.search([1.0, 0.0], top_k=5)
    assert [hit[0] for hit in hits] == ["b"]
    assert hits[0][2]["document_id"] == "doc-b"

    # The deletion survives a reload.
    assert LocalVectorStore(tmp_path / "v.npz").count() == 1


def test_dimension_change_is_rejected(tmp_path):
    store = LocalVectorStore(tmp_path / "v.npz")
    store.upsert([_point("a", [1.0, 0.0])])
    with pytest.raises(ValueError, match="dimension"):
        store.upsert([_point("b", [1.0, 0.0, 0.0])])
    assert store.count() == 1


def test_mixed_batch_is_rejected_without_mutating_the_store(tmp_path):
    store = LocalVectorStore(tmp_path / "v.npz")
    with pytest.raises(ValueError, match="dimension"):
        store.upsert([_point("a", [1.0, 0.0]), _point("b", [1.0, 0.0, 0.0])])
    assert store.count() == 0
    # The rejected batch must not have pinned the dimension either.
    store.upsert([_point("c", [1.0, 0.0])])
    assert store.count() == 1
    assert store.search([1.0, 0.0], top_k=1)[0][0] == "c"


def test_five_thousand_vectors_load_and_rank_quickly(tmp_path):
    rng = np.random.default_rng(7)
    matrix = rng.normal(size=(5000, 384)).astype(np.float32)
    path = tmp_path / "v.npz"
    store = LocalVectorStore(path)
    store.upsert(
        [
            _point(f"c{index}", matrix[index].tolist(), document_id="doc-a")
            for index in range(matrix.shape[0])
        ]
    )

    started = time.perf_counter()
    reloaded = LocalVectorStore(path)
    load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    hits = reloaded.search(matrix[123], top_k=10)
    search_seconds = time.perf_counter() - started
    print(f"5000 vectors: load={load_seconds:.3f}s search={search_seconds:.4f}s")

    assert hits[0][0] == "c123"
    # Generous ceilings: they catch an accidental fall back to JSON/looping,
    # not normal machine-to-machine variation.
    assert load_seconds < 10.0
    assert search_seconds < 2.0
