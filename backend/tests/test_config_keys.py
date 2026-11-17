"""Development API keys must never authenticate a production deployment."""

from __future__ import annotations

import pytest

from app import config

DEFAULTS = {
    "ADMIN_API_KEY": "dev-admin-key",
    "USER_API_KEY": "dev-user-key",
    "VIEWER_API_KEY": "dev-viewer-key",
}
ROLES = {
    "ADMIN_API_KEY": "admin",
    "USER_API_KEY": "user",
    "VIEWER_API_KEY": "viewer",
}


def expected_defaults() -> dict[str, str]:
    return {value: ROLES[name] for name, value in DEFAULTS.items()}


@pytest.mark.parametrize("environment", ["development", "", "staging", "prod"])
def test_defaults_are_available_outside_production(monkeypatch, environment: str) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    for name in DEFAULTS:
        monkeypatch.delenv(name, raising=False)

    assert config._api_keys() == expected_defaults()


@pytest.mark.parametrize("environment", ["production", "Production", "PRODUCTION"])
def test_production_rejects_missing_and_default_keys(monkeypatch, environment: str) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    for name in DEFAULTS:
        monkeypatch.delenv(name, raising=False)
    assert config._api_keys() == {}

    # Explicitly exporting the old default must not re-enable it.
    for name, value in DEFAULTS.items():
        monkeypatch.setenv(name, value)
    assert config._api_keys() == {}


def test_production_accepts_explicitly_chosen_keys(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_API_KEY", "prod-admin-abc")
    monkeypatch.setenv("USER_API_KEY", "prod-user-abc")
    monkeypatch.setenv("VIEWER_API_KEY", "prod-viewer-abc")

    assert config._api_keys() == {
        "prod-admin-abc": "admin",
        "prod-user-abc": "user",
        "prod-viewer-abc": "viewer",
    }


def test_chunk_limit_allows_large_documents_without_an_onnx_worker(monkeypatch) -> None:
    monkeypatch.delenv("MAX_CHUNKS_PER_DOCUMENT", raising=False)

    assert config.Settings().max_chunks_per_document == 20000

    monkeypatch.setenv("MAX_CHUNKS_PER_DOCUMENT", "30000")
    assert config.Settings().max_chunks_per_document == 30000
