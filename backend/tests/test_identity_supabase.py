"""Supabase identity tests. No network: a stubbed GoTrue over MockTransport."""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app import db, identity
from app.config import settings
from app.identity import supabase
from app.main import app
from conftest import register_employer, register_member, unique_email

SUPABASE_URL = "https://test-project.supabase.co"
ANON_KEY = "anon-key-for-tests"
SERVICE_KEY = "service-role-key-for-tests"
JWT_SECRET = "jwt-secret-for-tests-0123456789abcdef"
ISSUER = f"{SUPABASE_URL}/auth/v1"


# --------------------------------------------------------------------------- #
# Stub GoTrue
# --------------------------------------------------------------------------- #
class FakeGoTrue:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.passwords: dict[str, str] = {}
        self.refresh_tokens: dict[str, str] = {}
        self.banned: set[str] = set()
        self.anonymous_enabled = True
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.recoveries: list[dict[str, Any]] = []

    # -- helpers ---------------------------------------------------------- #
    def add_user(
        self,
        email: str,
        password: str,
        *,
        role: str = "user",
        display_name: str | None = None,
        guest: bool = False,
    ) -> str:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id,
            "aud": "authenticated",
            "email": None if guest else email,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_sign_in_at": None,
            "app_metadata": {"provider": "email", "role": role},
            "user_metadata": {"display_name": display_name} if display_name else {},
            "is_anonymous": guest,
        }
        self.passwords[user_id] = password
        return user_id

    def token(self, user_id: str, *, expires_in: int = 3600, secret: str | None = None) -> str:
        user = self.users[user_id]
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "aud": "authenticated",
            "iss": ISSUER,
            "exp": now + timedelta(seconds=expires_in),
            "iat": now,
            "email": user.get("email"),
            "app_metadata": user.get("app_metadata") or {},
            "user_metadata": user.get("user_metadata") or {},
            "is_anonymous": bool(user.get("is_anonymous")),
        }
        return jwt.encode(payload, secret or JWT_SECRET, algorithm="HS256")

    def session_body(self, user_id: str) -> dict[str, Any]:
        refresh = secrets.token_urlsafe(24)
        self.refresh_tokens[refresh] = user_id
        self.users[user_id]["last_sign_in_at"] = datetime.now(timezone.utc).isoformat()
        return {
            "access_token": self.token(user_id),
            "token_type": "bearer",
            "expires_in": 3600,
            "refresh_token": refresh,
            "user": self.users[user_id],
        }

    def _user_by_email(self, email: str) -> str | None:
        target = (email or "").lower()
        for user_id, user in self.users.items():
            if (user.get("email") or "").lower() == target:
                return user_id
        return None

    def _admin_ok(self, request: httpx.Request) -> bool:
        return (
            request.headers.get("apikey") == SERVICE_KEY
            and request.headers.get("authorization") == f"Bearer {SERVICE_KEY}"
        )

    # -- transport -------------------------------------------------------- #
    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(
            (request.method, request.url.path, dict(request.headers))
        )
        path = request.url.path
        body: Any = {}
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = {}

        if path.startswith("/auth/v1/admin/"):
            if not self._admin_ok(request):
                return httpx.Response(401, json={"msg": "Invalid API key"})
            return self._admin(request, body)

        if path == "/auth/v1/token":
            grant = request.url.params.get("grant_type")
            if grant == "password":
                user_id = self._user_by_email(body.get("email", ""))
                if user_id is None or self.passwords.get(user_id) != body.get("password"):
                    return httpx.Response(400, json={"msg": "Invalid login credentials"})
                return httpx.Response(200, json=self.session_body(user_id))
            if grant == "refresh_token":
                fresh = body.get("refresh_token", "")
                user_id = self.refresh_tokens.pop(fresh, None)
                if user_id is None:
                    return httpx.Response(400, json={"msg": "Invalid Refresh Token"})
                return httpx.Response(200, json=self.session_body(user_id))
            return httpx.Response(400, json={"msg": "unsupported grant"})

        if path == "/auth/v1/signup":
            if not self.anonymous_enabled:
                return httpx.Response(
                    422, json={"msg": "Anonymous sign-ins are disabled"}
                )
            user_id = self.add_user("", "", role="viewer", guest=True)
            return httpx.Response(200, json=self.session_body(user_id))

        if path == "/auth/v1/logout":
            return httpx.Response(204)

        if path == "/auth/v1/recover":
            self.recoveries.append(dict(body))
            return httpx.Response(200, json={})

        if path == "/auth/v1/user" and request.method == "PUT":
            header = request.headers.get("authorization", "")
            if not header.startswith("Bearer "):
                return httpx.Response(401, json={"msg": "missing token"})
            try:
                claims = jwt.decode(
                    header[len("Bearer ") :], JWT_SECRET, algorithms=["HS256"], audience="authenticated"
                )
            except jwt.InvalidTokenError:
                return httpx.Response(401, json={"msg": "invalid token"})
            user_id = claims.get("sub")
            if user_id not in self.users:
                return httpx.Response(404, json={"msg": "User not found"})
            if "password" in body:
                password = str(body["password"])
                if len(password) < 8:
                    return httpx.Response(422, json={"msg": "Password should be at least 8 characters"})
                self.passwords[user_id] = password
            return httpx.Response(200, json=self.users[user_id])

        return httpx.Response(404, json={"msg": "not found"})

    def _admin(self, request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        path = request.url.path
        if path == "/auth/v1/admin/users" and request.method == "GET":
            page = int(request.url.params.get("page", "1"))
            per_page = int(request.url.params.get("per_page", "1000"))
            users = list(self.users.values())
            start = (page - 1) * per_page
            return httpx.Response(200, json={"users": users[start : start + per_page]})

        if path == "/auth/v1/admin/users" and request.method == "POST":
            email = (body.get("email") or "").lower()
            if self._user_by_email(email):
                return httpx.Response(422, json={"msg": "User already registered"})
            role = (body.get("app_metadata") or {}).get("role", "viewer")
            display = (body.get("user_metadata") or {}).get("display_name")
            user_id = self.add_user(email, body.get("password", ""), role=role, display_name=display)
            return httpx.Response(201, json=self.users[user_id])

        prefix = "/auth/v1/admin/users/"
        if path.startswith(prefix):
            user_id = path[len(prefix) :]
            user = self.users.get(user_id)
            if user is None:
                return httpx.Response(404, json={"msg": "User not found"})
            if request.method == "GET":
                return httpx.Response(200, json=user)
            if request.method == "DELETE":
                del self.users[user_id]
                self.passwords.pop(user_id, None)
                return httpx.Response(204)
            if request.method == "PUT":
                if "app_metadata" in body:
                    user["app_metadata"] = body["app_metadata"]
                if "password" in body:
                    self.passwords[user_id] = body["password"]
                if "ban_duration" in body:
                    if body["ban_duration"] == "none":
                        self.banned.discard(user_id)
                    else:
                        self.banned.add(user_id)
                if "user_metadata" in body:
                    user["user_metadata"] = body["user_metadata"]
                return httpx.Response(200, json=user)
        return httpx.Response(404, json={"msg": "not found"})


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def fake():
    instance = FakeGoTrue()
    supabase.set_transport(httpx.MockTransport(instance))
    yield instance
    supabase.set_transport(None)


@pytest.fixture()
def supabase_settings(fake: FakeGoTrue):
    previous = {
        "auth_provider": settings.auth_provider,
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
        "supabase_service_role_key": settings.supabase_service_role_key,
        "supabase_jwt_secret": settings.supabase_jwt_secret,
        "supabase_jwks_url": settings.supabase_jwks_url,
        "invite_code": settings.invite_code,
        "demo_login_enabled": settings.demo_login_enabled,
        "rate_limit_auth_per_minute": settings.rate_limit_auth_per_minute,
    }
    object.__setattr__(settings, "auth_provider", "supabase")
    object.__setattr__(settings, "supabase_url", SUPABASE_URL)
    object.__setattr__(settings, "supabase_anon_key", ANON_KEY)
    object.__setattr__(settings, "supabase_service_role_key", SERVICE_KEY)
    object.__setattr__(settings, "supabase_jwt_secret", JWT_SECRET)
    object.__setattr__(settings, "supabase_jwks_url", "")
    object.__setattr__(settings, "rate_limit_auth_per_minute", 100000)
    try:
        yield fake
    finally:
        for name, value in previous.items():
            object.__setattr__(settings, name, value)


@pytest.fixture()
def client():
    instance = TestClient(app)
    instance.cookies.clear()
    return instance


def csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("eais_csrf")
    return {"X-CSRF-Token": token} if token else {}


# --------------------------------------------------------------------------- #
# Client contract
# --------------------------------------------------------------------------- #
def test_password_grant_maps_role_and_never_uses_the_service_key(supabase_settings):
    fake = supabase_settings
    user_id = fake.add_user("Ali@Example.com", "correct-horse-9", role="admin", display_name="Ali")

    result = supabase.login("Ali@Example.com", "correct-horse-9")

    assert result.user["id"] == user_id
    assert result.user["role"] == "admin"
    assert result.user["display_name"] == "Ali"
    assert result.tokens.access_token
    assert result.tokens.refresh_token
    assert result.tokens.csrf_token
    login_calls = [c for c in fake.calls if c[1] == "/auth/v1/token"]
    assert login_calls
    headers = login_calls[0][2]
    assert headers["apikey"] == ANON_KEY
    assert SERVICE_KEY not in json.dumps(headers)


def test_wrong_password_is_generic(supabase_settings):
    supabase_settings.add_user("person@example.com", "right-password-9")
    with pytest.raises(identity.InvalidCredentials) as excinfo:
        supabase.login("person@example.com", "wrong-password-9")
    assert excinfo.value.detail == "Invalid email or password"


def test_refresh_rotates_tokens_without_rotating_csrf(supabase_settings):
    user_id = supabase_settings.add_user("refresh@example.com", "correct-horse-9")
    first = supabase.login("refresh@example.com", "correct-horse-9")
    rotated = supabase.refresh(first.tokens.refresh_token or "")

    assert rotated.tokens.refresh_token != first.tokens.refresh_token
    assert rotated.tokens.csrf_token is None
    assert supabase.verify_access_token(rotated.tokens.access_token)["sub"] == user_id

    # The old refresh token cannot be replayed after rotation.
    with pytest.raises(identity.InvalidToken):
        supabase.refresh(first.tokens.refresh_token or "")


def test_register_employer_creates_a_workspace_admin_without_anonymous_signup(
    supabase_settings, client
):
    fake = supabase_settings
    response = register_employer(client, workspace_name="Supabase Workspace")
    body = response.json()
    user, workspace = body["user"], body["workspace"]

    assert user["role"] == "admin"
    assert user["is_guest"] is False
    assert workspace["name"] == "Supabase Workspace"
    assert workspace["invite_code"]
    assert response.json()["csrf_token"] == client.cookies.get("eais_csrf")

    profile = db.get_profile(user["id"])
    assert profile["role"] == "admin"
    assert profile["workspace_id"] == workspace["id"]
    # Registration goes through the GoTrue admin API, never public /signup.
    assert not any(call[1] == "/auth/v1/signup" for call in fake.calls)


def test_register_member_via_invite_is_scoped_to_the_workspace(supabase_settings, client):
    fake = supabase_settings
    owner = TestClient(app)
    owner.cookies.clear()
    workspace = register_employer(owner).json()["workspace"]

    response = register_member(
        client, workspace["invite_code"], display_name="Invited Person"
    )
    body = response.json()
    assert body["user"]["role"] == "user"
    assert body["user"]["display_name"] == "Invited Person"
    assert body["workspace"]["id"] == workspace["id"]
    assert db.get_profile(body["user"]["id"])["workspace_id"] == workspace["id"]

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
    assert not any(call[1] == "/auth/v1/signup" for call in fake.calls)


# --------------------------------------------------------------------------- #
# JWT verification
# --------------------------------------------------------------------------- #
def _claims(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": now + timedelta(hours=1),
        "app_metadata": {"role": "user"},
        "user_metadata": {},
        "is_anonymous": False,
    }
    payload.update(overrides)
    return payload


def test_hs256_verification_accepts_valid_claims(supabase_settings):
    claims = _claims()
    token = jwt.encode(claims, JWT_SECRET, algorithm="HS256")
    verified = supabase.verify_access_token(token)
    assert verified["sub"] == claims["sub"]


def test_verification_rejects_wrong_signature(supabase_settings):
    token = jwt.encode(_claims(), "another-secret-that-is-long-enough", algorithm="HS256")
    with pytest.raises(identity.InvalidToken):
        supabase.verify_access_token(token)


def test_verification_rejects_expired_tokens(supabase_settings):
    expired = datetime.now(timezone.utc) - timedelta(minutes=5)
    token = jwt.encode(_claims(exp=expired), JWT_SECRET, algorithm="HS256")
    with pytest.raises(identity.TokenExpired):
        supabase.verify_access_token(token)


def test_verification_rejects_wrong_audience(supabase_settings):
    token = jwt.encode(_claims(aud="service_role"), JWT_SECRET, algorithm="HS256")
    with pytest.raises(identity.InvalidToken):
        supabase.verify_access_token(token)


def test_verification_rejects_missing_subject(supabase_settings):
    claims = _claims()
    claims.pop("sub")
    token = jwt.encode(claims, JWT_SECRET, algorithm="HS256")
    with pytest.raises(identity.InvalidToken):
        supabase.verify_access_token(token)


def test_es256_tokens_use_jwks_even_when_a_legacy_secret_is_configured(
    supabase_settings, monkeypatch
):
    """Supabase signs new projects with ES256; the legacy secret cannot verify it.

    This is the regression behind "signed in, then every request says the
    session expired": the secret was always tried first, so a correct ES256
    session failed signature verification and the cookies were cleared.
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(_claims(), private_key, algorithm="ES256")
    seen: list[str] = []

    class _SigningKey:
        algorithm_name = "ES256"
        key = private_key.public_key()

    class _Client:
        def get_signing_key_from_jwt(self, presented: str) -> _SigningKey:
            assert presented == token
            return _SigningKey()

    def _client(url: str) -> _Client:
        seen.append(url)
        return _Client()

    monkeypatch.setattr(supabase, "_jwk_client", _client)

    verified = supabase.verify_access_token(token)

    assert verified["sub"]
    assert seen == [f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"]


def test_hs256_tokens_never_consult_jwks(supabase_settings, monkeypatch):
    def _unexpected(url: str):
        raise AssertionError(f"JWKS must not be used for HS256: {url}")

    monkeypatch.setattr(supabase, "_jwk_client", _unexpected)
    token = jwt.encode(_claims(), JWT_SECRET, algorithm="HS256")
    assert supabase.verify_access_token(token)["sub"]


def test_missing_verification_keys_are_not_a_token_rejection(supabase_settings):
    object.__setattr__(settings, "supabase_jwt_secret", "")
    object.__setattr__(settings, "supabase_jwks_url", "")
    object.__setattr__(settings, "supabase_url", "")
    token = jwt.encode(_claims(), JWT_SECRET, algorithm="HS256")
    with pytest.raises(identity.NotConfigured):
        supabase.verify_access_token(token)


def test_health_names_the_available_verification_keys(supabase_settings):
    auth = identity.health()
    assert auth["jwt"] == "hs256+jwks"
    assert JWT_SECRET not in json.dumps(auth)


def test_unknown_role_and_anonymous_claim_mapping(supabase_settings):
    assert supabase.claims_profile(_claims())["role"] == "user"
    assert (
        supabase.claims_profile(
            _claims(app_metadata={"role": "superuser"}, is_anonymous=True)
        )["role"]
        == "viewer"
    )
    assert supabase.claims_profile(_claims(is_anonymous=True))["is_guest"] is True


# --------------------------------------------------------------------------- #
# Admin API
# --------------------------------------------------------------------------- #
def test_admin_create_update_ban_and_delete(supabase_settings):
    created = supabase.admin_create_user(
        email="made@example.com",
        password="correct-horse-9",
        role="user",
        display_name="Made Person",
    )
    assert created["role"] == "user"
    assert created["display_name"] == "Made Person"

    promoted = supabase.admin_update_user(created["id"], role="admin", is_active=True)
    assert promoted is not None and promoted["role"] == "admin"
    assert created["id"] not in supabase_settings.banned

    disabled = supabase.admin_update_user(created["id"], is_active=False)
    assert disabled is not None
    assert created["id"] in supabase_settings.banned

    enabled = supabase.admin_update_user(created["id"], is_active=True)
    assert enabled is not None
    assert created["id"] not in supabase_settings.banned

    assert supabase.admin_delete_user(created["id"]) is True
    assert supabase.admin_delete_user(created["id"]) is False


def test_admin_calls_always_carry_the_service_key_and_never_leak_it(supabase_settings, caplog):
    supabase.admin_list_users()
    created = supabase.admin_create_user(
        email="hidden@example.com", password="correct-horse-9", role="viewer"
    )
    supabase.admin_update_user(created["id"], role="user")
    supabase.admin_delete_user(created["id"])

    admin_calls = [c for c in supabase_settings.calls if "/admin/" in c[1]]
    assert admin_calls
    for _, _, headers in admin_calls:
        assert headers["apikey"] == SERVICE_KEY
        assert headers["authorization"] == f"Bearer {SERVICE_KEY}"
    assert SERVICE_KEY not in caplog.text
    assert SERVICE_KEY not in json.dumps(created)


def test_sync_upserts_profiles_and_hides_guests_from_the_default_list(supabase_settings):
    supabase_settings.add_user("real@example.com", "correct-horse-9", role="user")
    supabase_settings.add_user("", "", role="viewer", guest=True)

    synced = supabase.sync_profiles()
    assert synced >= 2

    items, total = supabase.admin_list()
    emails = {item["email"] for item in items}
    assert "real@example.com" in emails
    assert None not in emails
    assert total >= 1

    guests, guest_total = supabase.admin_list(include_guests=True)
    assert guest_total > total
    assert any(item["is_guest"] for item in guests)


def test_bootstrap_admin_creates_then_repairs(supabase_settings):
    previous_email = settings.admin_email
    previous_password = settings.admin_password
    object.__setattr__(settings, "admin_email", "operator@example.com")
    object.__setattr__(settings, "admin_password", "operator-password-9")
    try:
        assert supabase.bootstrap_admin() is True
        assert supabase.bootstrap_admin() is True
        user_id = supabase_settings._user_by_email("operator@example.com")
        assert user_id is not None
        assert supabase_settings.users[user_id]["app_metadata"]["role"] == "admin"
        assert supabase_settings.passwords[user_id] == "operator-password-9"
        profile = db.get_profile(user_id)
        assert profile is not None and profile["role"] == "admin"
        assert profile["is_active"] == 1
    finally:
        object.__setattr__(settings, "admin_email", previous_email)
        object.__setattr__(settings, "admin_password", previous_password)


# --------------------------------------------------------------------------- #
# HTTP surface: cookies, refresh, CSRF, admin routes
# --------------------------------------------------------------------------- #
def test_http_login_me_refresh_and_logout(supabase_settings, client):
    supabase_settings.add_user(
        "session@example.com", "correct-horse-9", role="user", display_name="Session Person"
    )

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "session@example.com", "password": "correct-horse-9"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["user"]["role"] == "user"
    assert login.json()["csrf_token"] == client.cookies.get("eais_csrf")
    assert client.cookies.get("eais_access")
    assert client.cookies.get("eais_refresh")

    cookies = login.headers.get_list("set-cookie")
    access_cookie = next(item for item in cookies if item.startswith("eais_access="))
    assert "HttpOnly" in access_cookie

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "session@example.com"
    assert "access_token" not in me.text

    # Force the access token out of the cookie jar: the refresh token alone must
    # be enough, and the response must hand back a new access token.
    old_refresh = client.cookies.get("eais_refresh")
    client.cookies.delete("eais_access")
    refreshed = client.get("/api/v1/auth/me")
    assert refreshed.status_code == 200, refreshed.text
    assert client.cookies.get("eais_access")
    assert client.cookies.get("eais_refresh") != old_refresh

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.cookies.get("eais_access") is None
    assert client.cookies.get("eais_refresh") is None
    assert client.get("/api/v1/auth/me").status_code == 401


def test_http_admin_list_update_guards_csrf_and_guest_delete(supabase_settings, client):
    admin_id = supabase_settings.add_user("boss@example.com", "correct-horse-9", role="admin")
    target_id = supabase_settings.add_user("target@example.com", "correct-horse-9", role="user")
    guest_id = supabase_settings.add_user("", "", role="viewer", guest=True)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "boss@example.com", "password": "correct-horse-9"},
    )
    assert login.status_code == 200

    # Profiles do not exist for users that never signed in; sync repairs them.
    sync = client.post("/api/v1/auth/users/sync", headers=csrf(client))
    assert sync.status_code == 200, sync.text
    assert sync.json()["synced"] >= 3

    listed = client.get("/api/v1/auth/users", headers=csrf(client))
    assert listed.status_code == 200
    emails = {item["email"] for item in listed.json()["items"]}
    assert "target@example.com" in emails
    assert None not in emails  # guests hidden by default
    guest_list = client.get("/api/v1/auth/users?include_guests=true")
    assert any(item["is_guest"] for item in guest_list.json()["items"])

    without_csrf = client.patch(
        f"/api/v1/auth/users/{target_id}", json={"role": "viewer"}
    )
    assert without_csrf.status_code == 403

    promoted = client.patch(
        f"/api/v1/auth/users/{target_id}",
        json={"role": "admin", "is_active": True},
        headers=csrf(client),
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["user"]["role"] == "admin"
    assert supabase_settings.users[target_id]["app_metadata"]["role"] == "admin"
    assert db.get_profile(target_id)["role"] == "admin"

    self_demote = client.patch(
        f"/api/v1/auth/users/{admin_id}",
        json={"role": "user"},
        headers=csrf(client),
    )
    assert self_demote.status_code == 409

    deleted_failure = client.delete(
        f"/api/v1/auth/users/{target_id}", headers=csrf(client)
    )
    assert deleted_failure.status_code == 409  # not a guest

    deleted_guest = client.delete(
        f"/api/v1/auth/users/{guest_id}", headers=csrf(client)
    )
    assert deleted_guest.status_code == 204
    assert db.get_profile(guest_id) is None


def test_http_disabled_account_loses_its_session_and_cannot_sign_in(supabase_settings, client):
    user_id = supabase_settings.add_user("disabled@example.com", "correct-horse-9", role="user")
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "disabled@example.com", "password": "correct-horse-9"},
    )
    assert login.status_code == 200

    db.update_profile(user_id, is_active=0)
    assert client.get("/api/v1/auth/me").status_code == 401

    client.cookies.clear()
    blocked = client.post(
        "/api/v1/auth/login",
        json={"email": "disabled@example.com", "password": "correct-horse-9"},
    )
    assert blocked.status_code == 401

    # The flag survives a successful password grant, which is why sign-in fails.
    assert db.get_profile(user_id)["is_active"] == 0
    db.update_profile(user_id, is_active=1)


def test_http_non_admin_cannot_use_the_administration_api(supabase_settings, client):
    supabase_settings.add_user("normal@example.com", "correct-horse-9", role="user")
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "normal@example.com", "password": "correct-horse-9"},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/users").status_code == 403
    assert client.post("/api/v1/auth/users/sync", headers=csrf(client)).status_code == 403


# --------------------------------------------------------------------------- #
# Password recovery
# --------------------------------------------------------------------------- #
def test_recovery_uses_the_configured_redirect(supabase_settings):
    fake = supabase_settings
    user_id = fake.add_user("recover@example.com", "correct-horse-9")
    supabase.login("recover@example.com", "correct-horse-9")
    # admin_reset reads the profile index for the address; populate it as login
    # and sync would in a real deployment.
    db.upsert_profile(profile_id=user_id, email="recover@example.com", role="user")
    previous = settings.password_reset_redirect_to
    object.__setattr__(
        settings, "password_reset_redirect_to", "https://web.example/auth/reset"
    )
    try:
        supabase.admin_reset(user_id)
    finally:
        object.__setattr__(settings, "password_reset_redirect_to", previous)
    assert fake.recoveries[-1] == {
        "email": "recover@example.com",
        "redirect_to": "https://web.example/auth/reset",
    }


def test_recovery_link_sets_a_new_password(supabase_settings):
    fake = supabase_settings
    user_id = fake.add_user("reset@example.com", "old-password-9")
    token = fake.token(user_id)

    supabase.set_password(token, "new-password-9")

    assert fake.passwords[user_id] == "new-password-9"
    assert supabase.login("reset@example.com", "new-password-9").user["id"] == user_id


def test_recovery_link_rejects_an_expired_token(supabase_settings):
    fake = supabase_settings
    user_id = fake.add_user("expired@example.com", "old-password-9")
    token = fake.token(user_id, expires_in=-60)

    with pytest.raises(identity.IdentityError) as exc:
        supabase.set_password(token, "new-password-9")

    assert exc.value.status_code == 400
    assert "expired" in exc.value.detail.lower()
    assert fake.passwords[user_id] == "old-password-9"


def test_http_password_reset_completes_the_recovery_flow(supabase_settings, client):
    fake = supabase_settings
    user_id = fake.add_user("flow@example.com", "old-password-9", role="user")
    supabase.login("flow@example.com", "old-password-9")
    token = fake.token(user_id)

    response = client.post(
        "/api/v1/auth/password-reset",
        json={"access_token": token, "password": "new-password-9"},
    )

    assert response.status_code == 204, response.text
    signed_in = client.post(
        "/api/v1/auth/login",
        json={"email": "flow@example.com", "password": "new-password-9"},
    )
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["user"]["id"] == user_id


def test_http_password_reset_rejects_a_weak_password(supabase_settings, client):
    fake = supabase_settings
    user_id = fake.add_user("weak@example.com", "old-password-9")
    token = fake.token(user_id)

    response = client.post(
        "/api/v1/auth/password-reset",
        json={"access_token": token, "password": "short"},
    )

    assert response.status_code == 400, response.text
    assert fake.passwords[user_id] == "old-password-9"
