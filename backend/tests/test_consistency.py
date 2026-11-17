"""Consistency report and explicit repair behaviour."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app import consistency, db
from app.config import settings
from app.store import get_store

VECTOR = [0.1] + [0.0] * 383


@pytest.fixture()
def workspace():
    db.init_db()
    store = get_store()
    created: dict[str, list[str]] = {"documents": [], "chunks": [], "vectors": []}

    document_id = db.create_document(
        filename="report.txt",
        stored_filename="report.txt",
        content_type="text/plain",
        size_bytes=10,
        uploaded_by="test",
        content_hash=f"consistency-report-{uuid4().hex}",
    )
    db.update_document(document_id, status="completed", chunks_count=2)
    created["documents"].append(document_id)

    good_chunk = f"chunk-{document_id}"
    db.insert_chunks(
        [
            {
                "id": good_chunk,
                "document_id": document_id,
                "chunk_index": 0,
                "text": "evidence",
                "token_count": 1,
                "metadata": {},
            }
        ]
    )
    created["chunks"].append(good_chunk)

    # Inject a row whose owner no longer exists. The production schema has a
    # foreign key, so this simulates a legacy/corrupt database rather than a
    # state the API can create today.
    orphan_chunk = f"chunk-orphan-{uuid4().hex}"
    raw = sqlite3.connect(str(settings.db_path))
    raw.execute("PRAGMA foreign_keys=OFF")
    raw.execute(
        "INSERT INTO chunks (id, document_id, chunk_index, text, token_count, "
        "metadata_json, created_at) VALUES (?, ?, 0, 'evidence', 1, '{}', ?)",
        (orphan_chunk, "missing-document", db.now_iso()),
    )
    raw.commit()
    raw.close()
    created["chunks"].append(orphan_chunk)

    store.upsert(
        [
            {"id": "vector-orphan", "vector": VECTOR, "payload": {"document_id": document_id}},
        ]
    )
    created["vectors"].append("vector-orphan")

    stale = db.create_document(
        filename="stuck.txt",
        stored_filename="stuck.txt",
        content_type="text/plain",
        size_bytes=5,
        uploaded_by="test",
        content_hash=f"consistency-stuck-{uuid4().hex}",
    )
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.update_document(stale, status="processing", updated_at=old)
    created["documents"].append(stale)

    yield created, document_id, good_chunk, orphan_chunk, stale

    for chunk_id in created["chunks"]:
        db.delete_chunks([chunk_id])
    for document_id in created["documents"]:
        db.delete_chunks_by_document(document_id)
        db.delete_document(document_id)
    store.delete_points(created["vectors"])


def test_report_names_every_injected_inconsistency(workspace) -> None:
    _, document_id, good_chunk, orphan_chunk, stale = workspace
    report = consistency.inspect(stale_minutes=30)

    assert any(item["id"] == document_id for item in report.count_mismatches)
    assert orphan_chunk in report.orphan_chunks
    assert "vector-orphan" in report.orphan_vectors
    assert good_chunk in report.missing_vectors
    assert any(item["id"] == stale for item in report.stale_processing)
    assert report.ok is False
    assert report.as_dict()["ok"] is False


def test_dry_run_changes_nothing(workspace) -> None:
    created, _, good_chunk, orphan_chunk, stale = workspace
    before = db.get_document(stale)["status"]

    plan = consistency.reconcile(stale_minutes=30, purge_orphans=True)

    assert plan["stale_to_fail"] == [stale]
    assert orphan_chunk in plan["orphan_chunks"]
    assert "vector-orphan" in plan["orphan_vectors"]
    assert db.get_document(stale)["status"] == before
    refs = db.all_chunk_refs()
    assert good_chunk in refs
    assert orphan_chunk in refs
    assert "vector-orphan" in {item_id for item_id, _ in get_store().all_points()}
    assert created  # fixture identity is stable


def test_apply_repairs_only_requested_items(workspace) -> None:
    _, _, good_chunk, orphan_chunk, stale = workspace

    plan = consistency.reconcile(apply=True, stale_minutes=30, purge_orphans=True)

    assert plan["applied"] is True
    assert db.get_document(stale)["status"] == "failed"
    assert "interrupted" in db.get_document(stale)["error_message"].lower()
    refs = db.all_chunk_refs()
    assert good_chunk in refs
    assert orphan_chunk not in refs
    point_ids = {item_id for item_id, _ in get_store().all_points()}
    assert "vector-orphan" not in point_ids


def test_unreadable_store_is_a_failure_without_raw_exception_text(workspace) -> None:
    class BrokenStore:
        def all_points(self):
            raise RuntimeError("secret path /srv/vectors.npz")

    report = consistency.inspect(store=BrokenStore())

    assert report.ok is False
    assert report.vector_store_error == consistency.VECTOR_STORE_ERROR_DETAIL
    assert "secret path" not in report.as_dict()["vector_store_error"]


def test_apply_without_purge_keeps_orphans(workspace) -> None:
    _, _, _, orphan_chunk, stale = workspace

    consistency.reconcile(apply=True, stale_minutes=30, purge_orphans=False)

    assert db.get_document(stale)["status"] == "failed"
    assert orphan_chunk in db.all_chunk_refs()
    assert "vector-orphan" in {item_id for item_id, _ in get_store().all_points()}
