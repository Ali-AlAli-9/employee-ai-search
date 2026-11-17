"""Duplicate upload detection and replacement."""

from __future__ import annotations

import hashlib
import io

from fastapi.testclient import TestClient

from app import api, db, ingestion
from app.main import app
from app.store import get_store

client = TestClient(app)
ADMIN = {"X-API-Key": "dev-admin-key"}

POLICY = b"Employees receive 20 days of annual leave per year. Remote work is allowed."


def _documents_with_hash(content: bytes) -> list[dict]:
    digest = hashlib.sha256(content).hexdigest()
    return [
        item
        for item in db.list_documents(page_size=100)[0]
        if item["content_hash"] == digest
    ]


def _upload(content: bytes, filename: str = "policy.txt", *, replace: bool = False):
    suffix = "?replace=true" if replace else ""
    return client.post(
        f"/api/v1/documents/upload{suffix}",
        headers=ADMIN,
        files={"file": (filename, io.BytesIO(content), "text/plain")},
    )


def test_duplicate_upload_returns_conflict_with_existing_id():
    first = _upload(POLICY)
    assert first.status_code == 202, first.text
    document_id = first.json()["document_id"]
    try:
        second = _upload(POLICY, "renamed-copy.txt")
        assert second.status_code == 409, second.text
        detail = second.json()["detail"]
        assert detail["document_id"] == document_id
        assert detail["status"] == "completed"
        assert len(_documents_with_hash(POLICY)) == 1
    finally:
        client.delete(f"/api/v1/documents/{document_id}", headers=ADMIN)


def test_replace_true_replaces_the_previous_copy():
    first = _upload(POLICY)
    assert first.status_code == 202, first.text
    old_id = first.json()["document_id"]

    replaced = _upload(POLICY, "policy-v2.txt", replace=True)
    assert replaced.status_code == 202, replaced.text
    new_id = replaced.json()["document_id"]
    assert new_id != old_id
    try:
        assert client.get(f"/api/v1/documents/{old_id}", headers=ADMIN).status_code == 404
        document = client.get(f"/api/v1/documents/{new_id}", headers=ADMIN).json()
        assert document["status"] == "completed"
        assert document["filename"] == "policy-v2.txt"
        matching = [
            item
            for item in db.list_documents(page_size=100)[0]
            if item["content_hash"] == document["content_hash"]
        ]
        assert len(matching) == 1
    finally:
        client.delete(f"/api/v1/documents/{new_id}", headers=ADMIN)


def test_different_bytes_are_both_accepted():
    first = _upload(b"alpha policy text about leave")
    second = _upload(b"beta policy text about travel")
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    for response in (first, second):
        client.delete(f"/api/v1/documents/{response.json()['document_id']}", headers=ADMIN)


def test_failed_document_can_be_uploaded_again(monkeypatch):
    def fail_ingestion(document_id: str, filename: str, content: bytes) -> None:
        db.update_document(document_id, status="failed", error_message="synthetic failure")

    monkeypatch.setattr(api, "ingest_document", fail_ingestion)
    content = b"unique content for the retry path"

    first = _upload(content)
    assert first.status_code == 202, first.text
    failed_id = first.json()["document_id"]
    assert client.get(f"/api/v1/documents/{failed_id}", headers=ADMIN).json()["status"] == "failed"

    second = _upload(content)
    assert second.status_code == 202, second.text
    try:
        assert second.json()["document_id"] != failed_id
    finally:
        client.delete(f"/api/v1/documents/{second.json()['document_id']}", headers=ADMIN)
        client.delete(f"/api/v1/documents/{failed_id}", headers=ADMIN)


def test_ingestion_of_a_deleted_document_is_skipped():
    baseline = get_store().count()
    response = _upload(b"orphan guard: this document is deleted before ingestion starts")
    document_id = response.json()["document_id"]
    client.delete(f"/api/v1/documents/{document_id}", headers=ADMIN)

    ingestion.ingest_document(
        document_id, "ghost.txt", b"ghost content that must never be indexed"
    )

    assert db.get_document(document_id) is None
    assert get_store().count() == baseline
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document_id,)
        ).fetchone()[0]
    assert rows == 0


def test_document_deleted_during_indexing_leaves_no_orphans(monkeypatch):
    baseline = get_store().count()
    content = b"racing ingestion payload: unique marker zebra-42"
    response = _upload(content)
    document_id = response.json()["document_id"]

    original_insert = db.insert_chunks

    def delete_then_insert(records):
        # Simulate a DELETE or replace landing after the pre-write existence
        # check but before the ingestion task finishes.
        client.delete(f"/api/v1/documents/{document_id}", headers=ADMIN)
        original_insert(records)

    monkeypatch.setattr(ingestion.db, "insert_chunks", delete_then_insert)
    ingestion.ingest_document(document_id, "raced.txt", content)

    assert db.get_document(document_id) is None
    assert get_store().count() == baseline
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document_id,)
        ).fetchone()[0]
    assert rows == 0
