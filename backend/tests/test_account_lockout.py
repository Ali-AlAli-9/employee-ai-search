"""Account-keyed login lockout, independent of source IP."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.config import settings
from app.main import app
from conftest import register_employer


@pytest.fixture()
def client():
    instance = TestClient(app)
    instance.cookies.clear()
    return instance


@pytest.fixture()
def lock_settings():
    previous = (
        settings.login_lock_max_failures,
        settings.login_lock_minutes,
        settings.invite_code,
    )
    object.__setattr__(settings, "login_lock_max_failures", 3)
    object.__setattr__(settings, "login_lock_minutes", 15)
    object.__setattr__(settings, "invite_code", "")
    db.init_db()
    try:
        yield
    finally:
        for name, value in zip(
            ("login_lock_max_failures", "login_lock_minutes", "invite_code"), previous
        ):
            object.__setattr__(settings, name, value)


def unique_email(prefix: str = "lock") -> str:
    return f"{prefix}+{uuid.uuid4().hex[:12]}@example.com"


def register(client: TestClient, email: str) -> None:
    register_employer(client, email=email)
    assert client.post("/api/v1/auth/logout").status_code == 204


def attempt(client: TestClient, email: str, password: str = "wrong-password-9", ip: str = "203.0.113.1"):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"X-Forwarded-For": ip},
    )


def test_lockout_ignores_ip_rotation_and_does_not_echo_the_email(client, lock_settings) -> None:
    email = unique_email("rotate")
    register(client, email)

    for index in range(2):
        response = attempt(client, email, ip=f"203.0.113.{index + 1}")
        assert response.status_code == 401, response.text

    for index in range(2, 5):
        blocked = attempt(client, email, ip=f"198.51.100.{index + 1}")
        assert blocked.status_code == 429, blocked.text
        assert int(blocked.headers["Retry-After"]) > 0
        assert email not in blocked.text

    # A different account is still allowed to try; the lock is per email.
    other = attempt(client, unique_email("other"), ip="203.0.113.99")
    assert other.status_code == 401, other.text


def test_unknown_emails_are_locked_too(client, lock_settings) -> None:
    ghost = unique_email("ghost")

    for index in range(2):
        assert attempt(client, ghost, ip=f"192.0.2.{index + 1}").status_code == 401
    blocked = attempt(client, ghost, ip="192.0.2.99")
    assert blocked.status_code == 429
    assert ghost not in blocked.text


def test_email_spellings_share_one_counter(client, lock_settings) -> None:
    email = unique_email("case")
    register(client, email)

    assert attempt(client, f"  {email.upper()}  ").status_code == 401
    assert attempt(client, email.title()).status_code == 401
    blocked = attempt(client, email)
    assert blocked.status_code == 429


def test_successful_login_clears_the_failure_counter(client, lock_settings) -> None:
    email = unique_email("cleared")
    register(client, email)

    assert attempt(client, email).status_code == 401
    assert attempt(client, email, password="correct-horse-9").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204

    assert attempt(client, email).status_code == 401
    assert attempt(client, email).status_code == 401
    # The counter restarted at zero, so this is the first failure after a clean
    # sign-in rather than the fourth one overall.
    assert attempt(client, email).status_code == 429


def test_lock_expires_and_resets_the_counter(lock_settings) -> None:
    email = unique_email("expiry")
    moment = datetime.now(timezone.utc)

    for _ in range(2):
        locked, retry_after = db.record_login_failure(email, now=moment)
        assert locked is False

    locked, retry_after = db.record_login_failure(email, now=moment)
    assert locked is True
    assert retry_after == 15 * 60

    later = moment + timedelta(minutes=16)
    locked, retry_after = db.login_lock_status(email, now=later)
    assert locked is False
    assert retry_after == 0

    # A fresh failure starts from one, not from the pre-expiry count.
    locked, _ = db.record_login_failure(email, now=later)
    assert locked is False


def test_default_lockout_settings_are_conservative(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LOGIN_LOCK_MAX_FAILURES", "LOGIN_LOCK_MINUTES", "TRUST_PROXY_HEADERS"):
        monkeypatch.delenv(name, raising=False)

    values = config.Settings()
    assert values.login_lock_max_failures == 5
    assert values.login_lock_minutes == 15
    assert values.trust_proxy_headers is True
