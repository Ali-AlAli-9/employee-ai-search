"""Bring-your-own-key LLM: override, validation, verification and secrecy."""

from __future__ import annotations

import io
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import Settings, settings
from app.main import app

client = TestClient(app)
ADMIN = {"X-API-Key": "dev-admin-key"}
USER = {"X-API-Key": "dev-user-key"}
USER_KEY = "sk-user-1234567890"

CORPUS = (
    "Employees receive 20 days of paid annual leave per year. "
    "Leave is accrued monthly and at most five days may roll over."
)


@pytest.fixture(scope="module", autouse=True)
def indexed_corpus():
    response = client.post(
        "/api/v1/documents/upload",
        headers=ADMIN,
        files={"file": ("byok-leave.txt", io.BytesIO(CORPUS.encode()), "text/plain")},
    )
    assert response.status_code == 202, response.text
    document_id = response.json()["document_id"]
    yield
    client.delete(f"/api/v1/documents/{document_id}", headers=ADMIN)


def setting(name: str, value: object):
    """Temporarily override a frozen Settings field."""
    original = getattr(settings, name)

    class _Ctx:
        def __enter__(self):
            object.__setattr__(settings, name, value)
            return value

        def __exit__(self, *exc):
            object.__setattr__(settings, name, original)
            return False

    return _Ctx()


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_provider(calls: list[dict]):
    """Pretend to be an OpenAI-compatible provider and record every call."""

    def post(url: str, *, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": dict(headers or {}), "json": json or {}})
        system = ""
        messages = (json or {}).get("messages") or []
        if messages:
            system = str(messages[0].get("content", ""))
        if "Research Agent" in system:
            return _FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"sub_queries": ["annual leave days"], '
                                    '"search_strategy": "hybrid", "confidence": 0.9}'
                                )
                            }
                        }
                    ]
                },
            )
        return _FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"answer": "MODEL ANSWER: 20 days.", '
                                '"citation_indices": [1], "confidence": 0.88}'
                            )
                        }
                    }
                ]
            },
        )

    return post


def _chat(**kwargs):
    body = {"message": "How many annual leave days do employees get?", "stream": False}
    body.update(kwargs)
    return client.post("/api/v1/chat", headers={**ADMIN}, json=body)


def test_user_key_wins_over_the_server_key(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(httpx, "post", _fake_provider(calls))

    with setting("llm_api_key", "server-key-must-not-be-used"):
        response = client.post(
            "/api/v1/chat",
            headers={
                "X-API-Key": "dev-admin-key",
                "X-LLM-API-Key": USER_KEY,
                "X-LLM-Model": "gpt-4o-mini",
            },
            json={"message": "How many annual leave days do employees get?", "stream": False},
        )

    assert response.status_code == 200, response.text
    assert "MODEL ANSWER" in response.json()["answer"]
    assert calls, "the provider was never called"
    assert all(call["headers"]["Authorization"] == f"Bearer {USER_KEY}" for call in calls)
    assert all("server-key-must-not-be-used" not in str(call) for call in calls)
    assert all(call["json"]["max_tokens"] == settings.llm_max_tokens for call in calls)


def test_no_key_keeps_the_heuristic_path(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(httpx, "post", _fake_provider(calls))

    with setting("llm_api_key", ""):
        response = _chat()

    assert response.status_code == 200, response.text
    assert calls == [], "no outbound call may happen without a key"
    assert "Based on the indexed documents" in response.json()["answer"]


def test_disallowed_base_url_is_rejected_before_any_call(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(httpx, "post", _fake_provider(calls))

    response = client.post(
        "/api/v1/chat",
        headers={
            "X-API-Key": "dev-admin-key",
            "X-LLM-API-Key": USER_KEY,
            "X-LLM-Base-URL": "https://evil.example/v1",
        },
        json={"message": "hello", "stream": False},
    )

    assert response.status_code == 400
    assert "Base URL not allowed" in response.json()["detail"]
    assert calls == []


@pytest.mark.parametrize(
    "key",
    [
        "sk-with space",          # internal whitespace
        "x" * 201,                # over the limit
        "sk-bad\x01control",      # control character
    ],
)
def test_malformed_keys_are_rejected(key):
    response = client.post(
        "/api/v1/chat",
        headers={"X-API-Key": "dev-admin-key", "X-LLM-API-Key": key},
        json={"message": "hello", "stream": False},
    )
    assert response.status_code == 400
    assert key not in response.text


def test_key_is_never_logged_or_persisted(monkeypatch, caplog):
    calls: list[dict] = []
    monkeypatch.setattr(httpx, "post", _fake_provider(calls))
    caplog.set_level(logging.DEBUG)

    response = client.post(
        "/api/v1/chat",
        headers={"X-API-Key": "dev-admin-key", "X-LLM-API-Key": USER_KEY},
        json={"message": "How many annual leave days do employees get?", "stream": False},
    )

    assert response.status_code == 200, response.text
    assert USER_KEY not in response.text
    assert USER_KEY not in caplog.text
    with db.get_conn() as conn:
        traces = [row["data_json"] for row in conn.execute("SELECT data_json FROM traces")]
    assert traces
    assert all(USER_KEY not in row for row in traces)
    assert any('"llm_source": "user"' in row for row in traces)


def test_verify_reports_the_models_route(monkeypatch):
    def get(url: str, *, headers=None, timeout=None):
        assert headers["Authorization"] == f"Bearer {USER_KEY}"
        return _FakeResponse(200, {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}]})

    monkeypatch.setattr(httpx, "get", get)

    response = client.post(
        "/api/v1/llm/verify",
        headers={"X-API-Key": "dev-admin-key", "X-LLM-API-Key": USER_KEY},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["checked"] == "models"
    assert body["models"] == ["gpt-4o-mini", "gpt-4o"]
    assert USER_KEY not in response.text


@pytest.mark.parametrize(
    ("status_code", "expected", "needle"),
    [
        (401, 400, "rejected"),
        (403, 400, "rejected"),
        (429, 429, "quota"),
        (500, 400, "HTTP 500"),
    ],
)
def test_verify_maps_provider_errors(monkeypatch, status_code, expected, needle):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(status_code, {}))

    response = client.post(
        "/api/v1/llm/verify",
        headers={"X-API-Key": "dev-admin-key", "X-LLM-API-Key": USER_KEY},
    )

    assert response.status_code == expected
    assert needle in response.json()["detail"]
    assert USER_KEY not in response.text


def test_verify_without_a_key_is_a_clear_400(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(200, {}))
    response = client.post("/api/v1/llm/verify", headers=ADMIN)
    assert response.status_code == 400
    assert "X-LLM-API-Key" in response.json()["detail"]


def test_verify_requires_authentication():
    response = client.post("/api/v1/llm/verify", headers={"X-LLM-API-Key": USER_KEY})
    assert response.status_code == 401


def test_verify_reports_an_unreachable_provider(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "get", boom)
    response = client.post(
        "/api/v1/llm/verify",
        headers={"X-API-Key": "dev-admin-key", "X-LLM-API-Key": USER_KEY},
    )
    assert response.status_code == 502
    assert USER_KEY not in response.text


def test_byok_can_be_disabled(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("must not call"))

    with setting("llm_byok_enabled", False):
        response = client.post(
            "/api/v1/chat",
            headers={"X-API-Key": "dev-admin-key", "X-LLM-API-Key": USER_KEY},
            json={"message": "hello", "stream": False},
        )
        health = client.get("/api/v1/health").json()

    assert response.status_code == 403
    assert health["checks"]["llm_api"]["byok"] is False
    assert health["checks"]["llm_api"]["server_key_admin_only"] is True


def test_server_key_is_admin_only(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(httpx, "post", _fake_provider(calls))

    with setting("llm_api_key", "server-key"):
        response = client.post(
            "/api/v1/chat",
            headers=USER,
            json={"message": "hello", "stream": False},
        )

    assert response.status_code == 402
    assert "reserved for administrators" in response.json()["detail"]
    assert response.headers.get("X-LLM-Key-Required") == "1"
    assert calls == []


def test_a_non_admin_borrowing_the_server_key_is_refused(monkeypatch):
    # The header alone cannot upgrade a visitor to an admin: the role comes
    # from the principal, never from the request body or a provider header.
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("must not call"))

    with setting("llm_api_key", "server-key"):
        response = client.post(
            "/api/v1/chat",
            headers={**USER, "X-LLM-Model": "gpt-4o-mini"},
            json={"message": "hello", "stream": False},
        )

    assert response.status_code == 402


def test_a_non_admin_with_their_own_key_is_allowed(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(httpx, "post", _fake_provider(calls))

    with setting("llm_api_key", "server-key-must-not-be-used"):
        response = client.post(
            "/api/v1/chat",
            headers={
                **USER,
                "X-LLM-API-Key": USER_KEY,
                "X-LLM-Model": "gpt-4o-mini",
            },
            json={"message": "How many annual leave days do employees get?", "stream": False},
        )

    assert response.status_code == 200, response.text
    assert calls
    assert all(call["headers"]["Authorization"] == f"Bearer {USER_KEY}" for call in calls)


def test_non_admin_falls_back_to_heuristics_when_byok_is_disabled(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("must not call"))

    with setting("llm_api_key", "server-key"), setting("llm_byok_enabled", False):
        response = client.post(
            "/api/v1/chat",
            headers=USER,
            json={"message": "How many annual leave days do employees get?", "stream": False},
        )

    assert response.status_code == 200, response.text
    assert response.json()["answer"]
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT data_json FROM traces ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert '"llm_source": "none"' in row["data_json"]


def test_server_key_is_used_without_a_user_header(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(httpx, "post", _fake_provider(calls))

    with setting("llm_api_key", "server-key"):
        response = _chat()

    assert response.status_code == 200, response.text
    assert calls
    assert all(call["headers"]["Authorization"] == "Bearer server-key" for call in calls)
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT data_json FROM traces ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert '"llm_source": "server"' in row["data_json"]


# Exact backend half of the frontend's LLM_KEY_REQUIRED_DETAIL contract.
EXPECTED_KEY_DETAIL = (
    "The server API key is reserved for administrators. "
    "Add your own provider key to continue."
)


def test_require_chat_byok_defaults_to_false(monkeypatch):
    monkeypatch.delenv("REQUIRE_CHAT_BYOK", raising=False)
    assert Settings().require_chat_byok is False

    monkeypatch.setenv("REQUIRE_CHAT_BYOK", "1")
    assert Settings().require_chat_byok is True

    monkeypatch.setenv("REQUIRE_CHAT_BYOK", "off")
    assert Settings().require_chat_byok is False


def test_strict_mode_refuses_keyless_non_admin_chat(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(httpx, "post", _fake_provider(calls))

    with setting("llm_api_key", ""), setting("require_chat_byok", True):
        response = client.post(
            "/api/v1/chat",
            headers=USER,
            json={"message": "hello", "stream": False},
        )

    assert response.status_code == 402
    assert response.json()["detail"] == EXPECTED_KEY_DETAIL
    assert response.headers.get("X-LLM-Key-Required") == "1"
    assert calls == []


def test_default_mode_keeps_free_offline_chat(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(httpx, "post", _fake_provider(calls))

    with setting("llm_api_key", ""), setting("require_chat_byok", False):
        response = client.post(
            "/api/v1/chat",
            headers=USER,
            json={"message": "hello", "stream": False},
        )

    assert response.status_code == 200, response.text
    assert response.json()["llm_source"] == "none"
    assert calls == []


def test_strict_mode_allows_admin_without_a_key(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("must not call"))

    with setting("llm_api_key", ""), setting("require_chat_byok", True):
        response = _chat()

    assert response.status_code == 200, response.text
    assert response.json()["llm_source"] == "none"


def test_strict_mode_allows_a_non_admin_with_their_own_key(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(httpx, "post", _fake_provider(calls))

    with setting("llm_api_key", ""), setting("require_chat_byok", True):
        response = client.post(
            "/api/v1/chat",
            headers={
                **USER,
                "X-LLM-API-Key": USER_KEY,
                "X-LLM-Model": "gpt-4o-mini",
            },
            json={"message": "How many annual leave days do employees get?", "stream": False},
        )

    assert response.status_code == 200, response.text
    assert response.json()["llm_source"] == "user"
    assert calls
    assert all(call["headers"]["Authorization"] == f"Bearer {USER_KEY}" for call in calls)


def test_health_reports_require_chat_byok():
    with setting("require_chat_byok", True):
        strict = client.get("/api/v1/health").json()
    with setting("require_chat_byok", False):
        relaxed = client.get("/api/v1/health").json()

    assert strict["checks"]["llm_api"]["require_chat_byok"] is True
    assert relaxed["checks"]["llm_api"]["require_chat_byok"] is False
