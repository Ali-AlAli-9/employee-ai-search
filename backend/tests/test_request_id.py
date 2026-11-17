"""X-Request-ID propagation and log correlation."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_supplied_request_id_is_echoed():
    response = client.get(
        "/api/v1/health/ready", headers={"X-Request-ID": "trace-123"}
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-123"


def test_missing_request_id_is_generated():
    response = client.get("/api/v1/health/ready")
    value = response.headers.get("X-Request-ID")
    assert value is not None
    assert len(value) == 16


def test_malformed_request_id_is_replaced():
    response = client.get(
        "/api/v1/health/ready", headers={"X-Request-ID": "bad id with spaces"}
    )
    assert response.headers["X-Request-ID"] != "bad id with spaces"


def test_log_records_carry_the_request_id(caplog):
    with caplog.at_level(logging.INFO):
        client.get("/api/v1/health/ready", headers={"X-Request-ID": "trace-log"})
    assert any(
        getattr(record, "request_id", None) == "trace-log"
        for record in caplog.records
    )
