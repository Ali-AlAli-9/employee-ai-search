from __future__ import annotations

import io

from fastapi.testclient import TestClient

from app.api import CHAT_FAILURE_DETAIL, HEALTH_FAILURE_DETAIL, READINESS_FAILURE_DETAIL
from app.ingestion import INGESTION_FAILURE_DETAIL
from app.main import app

client = TestClient(app)

ADMIN = {"X-API-Key": "dev-admin-key"}
USER = {"X-API-Key": "dev-user-key"}
VIEWER = {"X-API-Key": "dev-viewer-key"}

POLICY = (
    b"Employees receive 20 days of annual leave per year. "
    b"Part-time employees accrue leave pro rata. "
    b"Remote work is allowed two days per week with manager approval. "
    b"Sick leave is separate and requires a medical certificate after three days."
)


def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"healthy", "degraded"}
    assert "checks" in body


def test_readiness_endpoint():
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_health_alias_answers_uptime_probes():
    # Render and most uptime monitors probe /health, often with HEAD.
    assert client.get("/health").json()["ready"] is True
    assert client.get("/healthz").status_code == 200
    assert client.head("/health").status_code == 200
    assert client.head("/").status_code == 200


def test_requires_api_key():
    assert client.get("/api/v1/documents").status_code == 401
    assert client.post("/api/v1/search", json={"query": "leave"}).status_code == 401


def test_ingest_search_and_chat_pipeline():
    response = client.post(
        "/api/v1/documents/upload",
        headers=ADMIN,
        files={"file": ("policy.txt", io.BytesIO(POLICY), "text/plain")},
    )
    assert response.status_code == 202, response.text
    document_id = response.json()["document_id"]

    document = client.get(f"/api/v1/documents/{document_id}", headers=ADMIN).json()
    assert document["status"] == "completed", document
    assert document["chunks_count"] >= 1

    response = client.post(
        "/api/v1/search",
        headers=VIEWER,
        json={"query": "annual leave days", "top_k": 5},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results
    assert any("leave" in item["text"].lower() for item in results)

    response = client.post(
        "/api/v1/chat",
        headers=USER,
        json={
            "message": "How many annual leave days do employees get?",
            "stream": False,
            "language": "en",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"]
    assert body["citations"]
    assert body["confidence"] >= 0.0
    assert body["llm_source"] in {"none", "server", "user"}


def test_any_signed_in_role_can_upload_but_only_admin_can_delete():
    response = client.post(
        "/api/v1/documents/upload",
        headers=VIEWER,
        files={"file": ("x.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 202, response.text
    document_id = response.json()["document_id"]

    denied = client.delete(f"/api/v1/documents/{document_id}", headers=VIEWER)
    assert denied.status_code == 403

    deleted = client.delete(f"/api/v1/documents/{document_id}", headers=ADMIN)
    assert deleted.status_code == 204


def test_replace_is_limited_to_the_uploader_or_an_admin():
    content = b"replace policy that belongs to one test only"
    created = client.post(
        "/api/v1/documents/upload",
        headers=VIEWER,
        files={"file": ("own.txt", content, "text/plain")},
    )
    assert created.status_code == 202, created.text
    document_id = created.json()["document_id"]

    # Replacing removes the old chunks, so it is a delete: another non-admin
    # must not be able to replace someone else's document.
    denied = client.post(
        "/api/v1/documents/upload?replace=true",
        headers=USER,
        files={"file": ("other.txt", content, "text/plain")},
    )
    assert denied.status_code == 403, denied.text

    # The uploader may replace its own document.
    again = client.post(
        "/api/v1/documents/upload?replace=true",
        headers=VIEWER,
        files={"file": ("own-2.txt", content, "text/plain")},
    )
    assert again.status_code == 202, again.text
    replaced_id = again.json()["document_id"]
    assert replaced_id != document_id

    assert (
        client.delete(f"/api/v1/documents/{replaced_id}", headers=ADMIN).status_code
        == 204
    )


def test_rejects_unsupported_extension():
    response = client.post(
        "/api/v1/documents/upload",
        headers=ADMIN,
        files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 400


def test_streaming_chat_emits_events():
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers=USER,
        json={"message": "remote work policy", "stream": True, "language": "en"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "event: token" in body
    assert "event: done" in body
    assert '"llm_source"' in body


def test_chat_history_is_paginated():
    response = client.get("/api/v1/chat/history", headers=USER)
    assert response.status_code == 200
    body = response.json()
    assert "items" in body and "total" in body


def test_document_listing_and_deletion():
    listing = client.get("/api/v1/documents?page_size=5", headers=ADMIN)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert items
    document_id = items[0]["id"]
    assert client.delete(f"/api/v1/documents/{document_id}", headers=ADMIN).status_code == 204
    assert client.get(f"/api/v1/documents/{document_id}", headers=ADMIN).status_code == 404


# --------------------------------------------------------------------------- #
# Error messages stay in the logs, never in the response
# --------------------------------------------------------------------------- #
def test_health_failure_is_logged_but_not_returned(monkeypatch, caplog):
    secret = "postgres://user:secret@db-host/app"

    def boom():
        raise RuntimeError(secret)

    monkeypatch.setattr("app.api.db.get_conn", boom)
    with caplog.at_level("WARNING", logger="app.api"):
        response = client.get("/api/v1/health")

    body = response.json()
    assert body["checks"]["database"]["detail"] == HEALTH_FAILURE_DETAIL
    assert secret not in response.text
    assert secret in caplog.text  # operators still get the full diagnostic


def test_readiness_failure_is_generic(monkeypatch):
    secret = "qdrant://internal-host:6333?api-key=secret"

    def boom():
        raise RuntimeError(secret)

    monkeypatch.setattr("app.api.db.get_conn", boom)
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == READINESS_FAILURE_DETAIL
    assert secret not in response.text


def test_streaming_chat_hides_pipeline_exception(monkeypatch):
    secret = "provider-request-id-SECRET-should-not-leak"

    def boom(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr("app.api.orchestrator.run", boom)
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers=USER,
        json={"message": "remote work policy", "stream": True, "language": "en"},
    ) as response:
        body = "".join(response.iter_text())

    assert secret not in body
    assert CHAT_FAILURE_DETAIL in body


def test_ingestion_failure_stores_a_generic_message(monkeypatch):
    secret = "FileNotFoundError: /srv/secrets/credentials.json"

    def boom(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr("app.ingestion.extract_pages", boom)
    created = client.post(
        "/api/v1/documents/upload",
        headers=ADMIN,
        files={"file": ("broken.txt", b"content", "text/plain")},
    )
    assert created.status_code == 202, created.text
    document_id = created.json()["document_id"]

    document = client.get(f"/api/v1/documents/{document_id}", headers=ADMIN).json()
    assert document["status"] == "failed"
    assert document["error_message"] == INGESTION_FAILURE_DETAIL
    assert secret not in str(document)

