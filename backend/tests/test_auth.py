"""Accounts, sessions, CSRF and the portable database layer (spec 004)."""

from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.config import settings
from app.main import app
from app.ratelimit import reset_limiters
from conftest import register_employer, register_member

ADMIN = {"X-API-Key": "dev-admin-key"}
CORPUS = b"Employees receive 20 days of paid annual leave per year."


@pytest.fixture()
def client():
    """A cookie-free client so one test cannot inherit another test's session."""
    instance = TestClient(app)
    instance.cookies.clear()
    return instance


@pytest.fixture(scope="module", autouse=True)
def admin_bootstrap():
    """The operator's admin account, created the same way production does it."""
    old_email = settings.admin_email
    old_password = settings.admin_password
    object.__setattr__(settings, "admin_email", "bootstrap-admin@example.com")
    object.__setattr__(settings, "admin_password", "bootstrap-password")
    try:
        auth.bootstrap_admin()
        yield
    finally:
        object.__setattr__(settings, "admin_email", old_email)
        object.__setattr__(settings, "admin_password", old_password)


def setting(name: str, value: object):
    """Temporarily override a frozen Settings field (same helper as test_byok)."""
    previous = getattr(settings, name)
    object.__setattr__(settings, name, value)
    return previous


def restore(name: str, previous: object) -> None:
    object.__setattr__(settings, name, previous)


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}+{uuid.uuid4().hex[:12]}@example.com"


def csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("eais_csrf")
    return {"X-CSRF-Token": token} if token else {}


def register(
    client: TestClient,
    email: str | None = None,
    password: str = "correct-horse-9",
    expected_status: int = 200,
):
    """Sign ``client`` in as an ordinary member of a brand-new workspace."""
    owner = TestClient(app)
    owner.cookies.clear()
    workspace = register_employer(owner).json()["workspace"]
    return register_member(
        client,
        workspace["invite_code"],
        email=email,
        password=password,
        expected_status=expected_status,
    )


# --------------------------------------------------------------------------- #
# Workspace registration (no demo guests)
# --------------------------------------------------------------------------- #
def test_register_employer_returns_workspace_and_admin_session(client):
    response = register_employer(client, workspace_name="HR Team")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["role"] == "admin"
    assert body["user"]["is_guest"] is False
    assert body["workspace"]["name"] == "HR Team"
    assert body["workspace"]["id"]
    assert body["workspace"]["invite_code"]
    assert body["csrf_token"]
    assert body["csrf_token"] == client.cookies.get("eais_csrf")

    raw = client.cookies.get("eais_session")
    assert raw
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(item for item in cookies if item.startswith("eais_session="))
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie or "SameSite=Lax" in session_cookie

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["id"] == body["user"]["id"]
    assert "password_hash" not in me.text


def test_register_member_joins_the_employers_workspace(client):
    owner = TestClient(app)
    owner.cookies.clear()
    workspace = register_employer(owner).json()["workspace"]

    response = register_member(client, workspace["invite_code"])
    body = response.json()
    assert body["user"]["role"] == "user"
    assert body["user"]["is_guest"] is False
    assert body["workspace"]["id"] == workspace["id"]
    assert body["workspace"]["invite_code"] == workspace["invite_code"]
    assert client.get("/api/v1/auth/me").json()["user"]["id"] == body["user"]["id"]

    invalid = client.post(
        "/api/v1/auth/register",
        json={
            "email": unique_email("badinvite"),
            "password": "correct-horse-9",
            "kind": "member",
            "invite_code": "not-the-code",
        },
    )
    assert invalid.status_code == 403
    assert invalid.json()["detail"] == "Invalid invite code"


def test_demo_flag_does_not_enable_an_endpoint(client):
    previous = setting("demo_login_enabled", True)
    try:
        response = client.post("/api/v1/auth/demo")
    finally:
        restore("demo_login_enabled", previous)
    assert response.status_code == 404


def test_me_without_credentials_is_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


# --------------------------------------------------------------------------- #
# Registration and login
# --------------------------------------------------------------------------- #
def test_plain_registration_is_rejected_without_an_invite(client):
    previous = setting("invite_code", "")
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": unique_email("open"), "password": "correct-horse-9"},
        )
    finally:
        restore("invite_code", previous)
    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid invite code"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_register_requires_the_code_when_the_deployment_sets_one(client):
    previous = setting("invite_code", "invite-123")
    try:
        missing = client.post(
            "/api/v1/auth/register",
            json={"email": unique_email(), "password": "correct-horse-9"},
        )
        empty = client.post(
            "/api/v1/auth/register",
            json={"email": unique_email(), "password": "correct-horse-9", "invite_code": ""},
        )
    finally:
        restore("invite_code", previous)
    assert missing.status_code == 403
    assert empty.status_code == 403


def test_register_rejects_a_wrong_invite_code(client):
    previous = setting("invite_code", "invite-123")
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": unique_email(),
                "password": "correct-horse-9",
                "invite_code": "not-the-code",
            },
        )
    finally:
        restore("invite_code", previous)
    assert response.status_code == 403


def test_register_login_me_logout(client):
    email = unique_email("roundtrip")
    registered = register(client, email=email)
    assert registered.status_code == 200, registered.text
    assert registered.json()["user"]["email"] == email.lower()
    assert registered.json()["user"]["role"] == "user"

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    user_id = me.json()["user"]["id"]

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.cookies.get("eais_session") is None
    assert client.get("/api/v1/auth/me").status_code == 401

    logged_in = client.post(
        "/api/v1/auth/login", json={"email": email.upper(), "password": "correct-horse-9"}
    )
    assert logged_in.status_code == 200, logged_in.text
    assert logged_in.json()["user"]["id"] == user_id
    assert client.get("/api/v1/auth/me").status_code == 200


def test_logout_without_a_session_is_idempotent(client):
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_duplicate_email_is_409_without_disclosure(client):
    email = unique_email("dupe")
    assert register(client, email=email).status_code == 200
    second = register(client, email=email, expected_status=409)
    assert second.status_code == 409
    assert "password" not in second.text.lower()


def test_short_password_or_bad_email_is_400(client):
    previous = setting("invite_code", "invite-123")
    try:
        short = client.post(
            "/api/v1/auth/register",
            json={"email": unique_email(), "password": "short", "invite_code": "invite-123"},
        )
        bad_email = client.post(
            "/api/v1/auth/register",
            json={
                "email": "not-an-email",
                "password": "correct-horse-9",
                "invite_code": "invite-123",
            },
        )
    finally:
        restore("invite_code", previous)
    assert short.status_code == 400
    assert bad_email.status_code == 400


def test_wrong_password_and_unknown_email_share_one_message(client):
    email = unique_email("generic")
    assert register(client, email=email).status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204

    wrong = client.post("/api/v1/auth/login", json={"email": email, "password": "nope-nope-9"})
    unknown = client.post(
        "/api/v1/auth/login", json={"email": unique_email("ghost"), "password": "nope-nope-9"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_deactivated_user_cannot_sign_in_or_reuse_a_session(client):
    email = unique_email("inactive")
    assert register(client, email=email).status_code == 200
    user_id = client.get("/api/v1/auth/me").json()["user"]["id"]

    db.update_user(user_id, is_active=0)

    # The cookie is still valid cryptographically; the user row must stop it.
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.clear()
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-9"})
    assert login.status_code == 401

    db.update_user(user_id, is_active=1)


# --------------------------------------------------------------------------- #
# Sessions: expiry and storage
# --------------------------------------------------------------------------- #
def test_expired_session_is_401(client):
    email = unique_email("expired")
    assert register(client, email=email).status_code == 200
    user_id = client.get("/api/v1/auth/me").json()["user"]["id"]
    client.cookies.clear()

    raw = "expired-token-" + uuid.uuid4().hex
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    db.create_session(
        user_id=user_id,
        token_hash=auth.hash_token(raw),
        csrf_hash=auth.hash_token("csrf"),
        expires_at=past,
    )
    client.cookies.set("eais_session", raw)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_session_token_is_stored_only_as_a_hash(client):
    email = unique_email("hashed")
    assert register(client, email=email).status_code == 200
    raw = client.cookies.get("eais_session")
    assert raw

    with db.get_conn() as conn:
        rows = conn.execute("SELECT token_hash, csrf_hash FROM sessions").fetchall()

    hashes = {row["token_hash"] for row in rows}
    assert auth.hash_token(raw) in hashes
    assert raw not in hashes
    assert all(len(value) == 64 for value in hashes)


def test_password_hashing_is_salted_and_verifiable():
    first = auth.hash_password("correct-horse-9")
    second = auth.hash_password("correct-horse-9")
    assert first != second
    assert auth.verify_password("correct-horse-9", first) is True
    assert auth.verify_password("wrong-password", first) is False
    assert first.startswith("scrypt$")


# --------------------------------------------------------------------------- #
# CSRF and role enforcement
# --------------------------------------------------------------------------- #
def test_csrf_required_for_cookie_authenticated_posts(client):
    assert register(client, email=unique_email("csrfsearch")).status_code == 200
    payload = {"query": "annual leave", "top_k": 3}

    missing = client.post("/api/v1/search", json=payload)
    assert missing.status_code == 403
    assert "csrf" in missing.json()["detail"].lower()

    allowed = client.post("/api/v1/search", json=payload, headers=csrf(client))
    assert allowed.status_code == 200


def test_api_keys_skip_csrf_and_keep_working(client):
    payload = {"query": "annual leave", "top_k": 3}
    assert client.post("/api/v1/search", json=payload, headers=ADMIN).status_code == 200
    assert client.get("/api/v1/documents", headers=ADMIN).status_code == 200


def test_any_signed_in_account_can_upload_but_only_admins_delete(client):
    admin = TestClient(app)
    admin.cookies.clear()
    workspace = register_employer(admin).json()["workspace"]
    assert register_member(client, workspace["invite_code"]).status_code == 200
    uploaded = client.post(
        "/api/v1/documents/upload",
        headers=csrf(client),
        files={"file": ("member.txt", io.BytesIO(CORPUS + b" member"), "text/plain")},
    )
    assert uploaded.status_code == 202, uploaded.text
    member_document = uploaded.json()["document_id"]

    denied = client.delete(
        f"/api/v1/documents/{member_document}", headers=csrf(client)
    )
    assert denied.status_code == 403

    own_upload = admin.post(
        "/api/v1/documents/upload",
        headers=csrf(admin),
        files={"file": ("admin-session.txt", io.BytesIO(CORPUS + b" admin"), "text/plain")},
    )
    assert own_upload.status_code == 202, own_upload.text
    document_id = own_upload.json()["document_id"]

    deleted = admin.delete(f"/api/v1/documents/{document_id}", headers=csrf(admin))
    assert deleted.status_code == 204
    member_deleted = admin.delete(
        f"/api/v1/documents/{member_document}", headers=csrf(admin)
    )
    assert member_deleted.status_code == 204


def test_workspace_isolation_for_documents_and_search(client):
    workspace_a = register_employer(client).json()["workspace"]

    admin_b = TestClient(app)
    admin_b.cookies.clear()
    workspace_b = register_employer(admin_b).json()["workspace"]
    member_b = TestClient(app)
    member_b.cookies.clear()
    register_member(member_b, workspace_b["invite_code"])

    uploaded = client.post(
        "/api/v1/documents/upload",
        headers=csrf(client),
        files={"file": ("private.txt", io.BytesIO(CORPUS + b" private"), "text/plain")},
    )
    assert uploaded.status_code == 202, uploaded.text
    document_id = uploaded.json()["document_id"]

    listed = member_b.get("/api/v1/documents")
    assert listed.status_code == 200, listed.text
    assert document_id not in {item["id"] for item in listed.json()["items"]}

    hidden = member_b.get(f"/api/v1/documents/{document_id}")
    assert hidden.status_code == 404

    search = member_b.post(
        "/api/v1/search",
        headers=csrf(member_b),
        json={
            "query": "annual leave",
            "top_k": 3,
            "filters": {"document_ids": [document_id]},
        },
    )
    assert search.status_code == 404

    denied = member_b.delete(
        f"/api/v1/documents/{document_id}", headers=csrf(member_b)
    )
    assert denied.status_code == 403

    cross_admin = admin_b.delete(
        f"/api/v1/documents/{document_id}", headers=csrf(admin_b)
    )
    assert cross_admin.status_code == 404
    assert db.get_document(document_id)["workspace_id"] == workspace_a["id"]

    # Leave no completed document behind for the corpus-wide retrieval tests.
    cleaned = client.delete(
        f"/api/v1/documents/{document_id}", headers=csrf(client)
    )
    assert cleaned.status_code == 204


def test_only_admins_may_create_users(client):
    assert register(client).status_code == 200
    response = client.post(
        "/api/v1/auth/users",
        headers=csrf(client),
        json={"email": unique_email(), "password": "correct-horse-9", "role": "admin"},
    )
    assert response.status_code == 403


def test_auth_attempts_use_their_own_rate_limit_bucket(client):
    previous = setting("rate_limit_auth_per_minute", 2)
    reset_limiters()
    try:
        payload = {"email": unique_email("limited"), "password": "wrong-password-9"}
        assert client.post("/api/v1/auth/login", json=payload).status_code == 401
        assert client.post("/api/v1/auth/login", json=payload).status_code == 401
        blocked = client.post("/api/v1/auth/login", json=payload)
        assert blocked.status_code == 429
        assert blocked.headers.get("retry-after")
    finally:
        reset_limiters()
        restore("rate_limit_auth_per_minute", previous)


# --------------------------------------------------------------------------- #
# Admin bootstrap and storage
# --------------------------------------------------------------------------- #
def test_admin_bootstrap_is_idempotent():
    email = "bootstrap-admin@example.com"
    assert auth.bootstrap_admin() is True
    assert auth.bootstrap_admin() is True

    user = db.get_user_by_email(email)
    assert user is not None
    assert user["role"] == "admin"
    assert user["is_active"] == 1
    assert auth.verify_password("bootstrap-password", user["password_hash"])

    with db.get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE email = ?", (email,)
        ).fetchone()["c"]
    assert count == 1


def test_sqlite_remains_the_zero_setup_default():
    assert db.dialect() in {"sqlite", "postgres"}
    if not settings.database_url:
        assert db.dialect() == "sqlite"
        assert settings.db_path.name == "app.db"


def test_no_guest_accounts_are_created(client):
    registration = register_employer(client).json()
    employer = registration["user"]
    member_client = TestClient(app)
    member_client.cookies.clear()
    member = register_member(
        member_client, registration["workspace"]["invite_code"]
    ).json()["user"]

    for user in (employer, member):
        assert user["is_guest"] is False
        assert not user["email"].endswith("@guest.local")

    with db.get_conn() as conn:
        guests = conn.execute("SELECT id FROM users WHERE is_guest = 1").fetchall()
    assert guests == []


# --------------------------------------------------------------------------- #
# Postgres (opt-in: set TEST_DATABASE_URL)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL to run the Postgres integration test",
)
def test_postgres_roundtrip():
    previous = settings.database_url
    object.__setattr__(settings, "database_url", os.environ["TEST_DATABASE_URL"])
    db.reset_pool()
    email = unique_email("postgres")
    try:
        db.init_db()
        assert db.dialect() == "postgres"
        user = db.create_user(
            email=email, password_hash=auth.hash_password("correct-horse-9"), role="user"
        )
        assert db.get_user(user["id"])["email"] == email
        assert db.get_user_by_email(email)["id"] == user["id"]

        token = auth.hash_token("pg-token-" + uuid.uuid4().hex)
        db.create_session(
            user_id=user["id"],
            token_hash=token,
            csrf_hash=auth.hash_token("csrf"),
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )
        session = db.get_session(token)
        assert session is not None
        assert db.delete_session(token) is True
        assert db.get_session(token) is None

        assert db.delete_user(user["id"]) is True
    finally:
        db.reset_pool()
        object.__setattr__(settings, "database_url", previous)
