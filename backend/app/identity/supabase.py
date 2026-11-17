"""Supabase Auth (GoTrue) provider.

GoTrue owns identities and passwords. The platform keeps only a small
``profiles`` read model (see ``db.py``) because the admin user list cannot
search or filter and because a disabled account must be rejected on its next
request, not after its JWT expires.

Security rules that this module owns:

* the service-role key is used **only** in server-to-server admin headers;
* every access token is verified locally (HS256 secret or JWKS), never trusted;
* error messages never include a token, a password or a Supabase secret.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from .. import auth, db
from ..config import settings
from .base import (
    AuthResult,
    AuthTokens,
    BadRequest,
    Conflict,
    IdentityError,
    InvalidCredentials,
    InvalidToken,
    NotConfigured,
    ProviderUnavailable,
    TokenExpired,
    public_user,
    role_or_viewer,
)

logger = logging.getLogger(__name__)

ACCESS_COOKIE = "eais_access"
REFRESH_COOKIE = "eais_refresh"
CSRF_COOKIE = auth.CSRF_COOKIE
_REFRESH_MAX_AGE = 30 * 24 * 3600

# Tests install an httpx.MockTransport here; production leaves it ``None``.
_transport: httpx.BaseTransport | None = None
_jwk_clients: dict[str, PyJWKClient] = {}


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def configured() -> bool:
    """The project URL is the only hard requirement to select this provider."""
    return bool(settings.supabase_url)


def auth_configured() -> bool:
    return configured() and bool(settings.supabase_anon_key)


def admin_configured() -> bool:
    return auth_configured() and bool(settings.supabase_service_role_key)


def _issuer() -> str | None:
    if not settings.supabase_url:
        return None
    return f"{settings.supabase_url}/auth/v1"


# --------------------------------------------------------------------------- #
# HTTP plumbing
# --------------------------------------------------------------------------- #
def _client() -> httpx.Client:
    if not configured():
        raise NotConfigured("Supabase Auth is not configured (SUPABASE_URL is empty)")
    return httpx.Client(
        base_url=settings.supabase_url,
        timeout=settings.supabase_timeout_seconds,
        transport=_transport,
    )


def _request(
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    admin: bool = False,
    bearer: str | None = None,
) -> tuple[int, Any]:
    """One GoTrue call. Returns ``(status, parsed_body)`` without raising on 4xx.

    Callers decide how a status maps to a product error, which keeps the
    distinction between "wrong password" and "service key rejected" explicit.
    """
    if admin:
        if not admin_configured():
            raise NotConfigured("Supabase admin API is not configured")
        key = settings.supabase_service_role_key
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    else:
        if not auth_configured():
            raise NotConfigured("Supabase Auth is not configured")
        headers = {"apikey": settings.supabase_anon_key}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"

    try:
        with _client() as client:
            response = client.request(
                method, path, json=json, params=params, headers=headers
            )
    except httpx.TimeoutException as exc:
        raise ProviderUnavailable("Supabase Auth timed out") from exc
    except httpx.HTTPError as exc:
        # The exception text may contain the URL but never a credential.
        logger.warning("supabase transport error method=%s path=%s", method, path)
        raise ProviderUnavailable("Supabase Auth is unreachable") from exc

    try:
        body: Any = response.json() if response.content else None
    except ValueError:
        body = None
    return response.status_code, body


def _payload_message(body: Any) -> str:
    if isinstance(body, dict):
        for key in ("msg", "message", "error_description", "error", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _raise_service_error(status: int, body: Any, *, operation: str) -> None:
    """Map an unexpected GoTrue failure without leaking server diagnostics."""
    message = _payload_message(body).lower()
    if status == 429 or "rate limit" in message:
        raise IdentityError("Too many attempts. Try again later.", status_code=429)
    if status in (401, 403):
        logger.error("supabase admin credentials rejected operation=%s", operation)
        raise ProviderUnavailable("Supabase rejected the server credentials")
    if status >= 500:
        raise ProviderUnavailable("Supabase Auth is temporarily unavailable")
    logger.warning(
        "supabase request failed operation=%s status=%s", operation, status
    )
    raise ProviderUnavailable("Supabase Auth request failed")


def _auth_result(data: Any, *, csrf: bool = True) -> AuthResult:
    if not isinstance(data, dict) or not data.get("access_token"):
        raise ProviderUnavailable("Supabase Auth returned an unexpected response")
    access = str(data["access_token"])
    refresh = data.get("refresh_token")
    expires_in = data.get("expires_in")
    user = data.get("user")
    claims: dict[str, Any] = {}
    if not isinstance(user, dict):
        try:
            claims = jwt.decode(access, options={"verify_signature": False})
        except jwt.InvalidTokenError:
            claims = {}
        user = {}
    return AuthResult(
        user=_public_user_from_go(user, claims),
        tokens=AuthTokens(
            access_token=access,
            refresh_token=str(refresh) if refresh else None,
            csrf_token=auth.new_csrf_token() if csrf else None,
            expires_in=int(expires_in) if isinstance(expires_in, int) else None,
        ),
    )


def _public_user_from_go(
    user: dict[str, Any], claims: dict[str, Any] | None = None
) -> dict[str, Any]:
    claims = claims or {}
    app_metadata = user.get("app_metadata") or claims.get("app_metadata") or {}
    user_metadata = user.get("user_metadata") or claims.get("user_metadata") or {}
    is_guest = bool(user.get("is_anonymous") or claims.get("is_anonymous"))
    mapped = public_user(
        {
            "id": user.get("id") or claims.get("sub"),
            "email": user.get("email") or claims.get("email"),
            "role": role_or_viewer(app_metadata.get("role")),
            "display_name": user_metadata.get("display_name"),
            "is_guest": is_guest,
            "created_at": user.get("created_at"),
            "last_login_at": user.get("last_sign_in_at"),
            "last_sign_in_at": user.get("last_sign_in_at"),
        }
    )
    # Carried so profile upserts can scope a Supabase account to its workspace.
    mapped["workspace_id"] = user_metadata.get("workspace_id")
    return mapped


# --------------------------------------------------------------------------- #
# Public auth
# --------------------------------------------------------------------------- #
def login(email: str, password: str, user_agent: str | None = None) -> AuthResult:
    status, body = _request(
        "POST",
        "/auth/v1/token",
        params={"grant_type": "password"},
        json={"email": email, "password": password},
    )
    if status in (400, 401, 422):
        raise InvalidCredentials()
    if status != 200:
        _raise_service_error(status, body, operation="password_grant")
    return _auth_result(body)


def register(
    email: str,
    password: str,
    display_name: str | None = None,
    user_agent: str | None = None,
    *,
    workspace_id: str | None = None,
    role: str = "user",
) -> AuthResult:
    """Create a confirmed account in a workspace and sign in.

    Public ``/signup`` would require an email confirmation round trip when the
    project enables confirmations, so registration uses the admin API and then
    performs a normal password grant. Without a service key the operator gets a
    clear ``503`` instead of a half-working account.
    """
    user_metadata: dict[str, Any] = {}
    if display_name:
        user_metadata["display_name"] = display_name
    if workspace_id is not None:
        user_metadata["workspace_id"] = workspace_id
    status, body = _request(
        "POST",
        "/auth/v1/admin/users",
        json={
            "email": email,
            "password": password,
            "email_confirm": True,
            "app_metadata": {"role": role},
            "user_metadata": user_metadata,
        },
        admin=True,
    )
    if status in (400, 422) and "registered" in _payload_message(body).lower():
        raise Conflict("An account with this email already exists")
    if status not in (200, 201):
        _raise_service_error(status, body, operation="register")
    created = body.get("user") if isinstance(body, dict) else None
    result = login(email, password)
    if isinstance(created, dict):
        metadata = created.get("user_metadata") or {}
        result.user["display_name"] = (
            metadata.get("display_name") or result.user.get("display_name")
        )
        if metadata.get("workspace_id"):
            result.user["workspace_id"] = metadata["workspace_id"]
    if workspace_id is not None:
        result.user["workspace_id"] = workspace_id
    logger.info(
        "account created email=%s role=%s provider=supabase", email, role
    )
    return result


def refresh(refresh_token: str) -> AuthResult:
    status, body = _request(
        "POST",
        "/auth/v1/token",
        params={"grant_type": "refresh_token"},
        json={"refresh_token": refresh_token},
    )
    if status in (400, 401, 403, 422):
        raise InvalidToken("refresh token rejected")
    if status != 200:
        _raise_service_error(status, body, operation="refresh")
    # The CSRF token is intentionally not rotated here: the browser caches it
    # and a transparent refresh must not invalidate an in-flight form.
    return _auth_result(body, csrf=False)


def logout(access_token: str | None) -> None:
    if not access_token:
        return
    try:
        status, body = _request(
            "POST", "/auth/v1/logout", json={}, bearer=access_token
        )
        if status >= 500:
            _raise_service_error(status, body, operation="logout")
    except IdentityError:
        # Logging out is best effort: the cookies are cleared regardless, and a
        # Supabase outage must not trap a user in a session.
        logger.warning("supabase logout did not complete")


def recover(email: str, redirect_to: str | None = None) -> None:
    payload: dict[str, Any] = {"email": email}
    if redirect_to:
        payload["redirect_to"] = redirect_to
    status, body = _request("POST", "/auth/v1/recover", json=payload)
    if status >= 500:
        _raise_service_error(status, body, operation="recover")


def set_password(access_token: str, password: str) -> None:
    """Complete a recovery link: ``PUT /user`` with the emailed access token.

    GoTrue accepts the short-lived token from the email fragment; the platform
    never sees the old password and does not store the new one.
    """
    status, body = _request(
        "PUT",
        "/auth/v1/user",
        json={"password": password},
        bearer=access_token,
    )
    if status in (401, 403):
        raise BadRequest("The reset link is invalid or has expired. Request a new one.")
    if status == 429:
        raise IdentityError("Too many attempts. Try again later.", status_code=429)
    if status >= 400:
        message = _payload_message(body)
        if message:
            raise BadRequest(message)
        _raise_service_error(status, body, operation="set-password")


# --------------------------------------------------------------------------- #
# Token verification
# --------------------------------------------------------------------------- #
def _jwk_client(url: str) -> PyJWKClient:
    client = _jwk_clients.get(url)
    if client is None:
        client = PyJWKClient(url, cache_keys=True)
        _jwk_clients[url] = client
    return client


def _verification_material(token: str) -> tuple[Any, str]:
    """Pick the key that this token's own header calls for.

    Supabase projects created after JWT signing keys were introduced sign
    access tokens with **ES256** (asymmetric). The legacy `JWT secret` still
    exists, but it only verifies **HS256** tokens. Always trying the secret
    would reject every real session with "Signature verification failed", so
    the header decides: `HS*` uses the legacy secret, anything else uses the
    project JWKS (whose URL derives from `SUPABASE_URL`).
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise InvalidToken("malformed token") from exc
    algorithm = str(header.get("alg") or "")
    if not algorithm:
        raise InvalidToken("missing algorithm")
    if algorithm.startswith("HS"):
        if not settings.supabase_jwt_secret:
            raise NotConfigured("No JWT secret is configured for HS256 tokens")
        return settings.supabase_jwt_secret, algorithm
    jwks_url = settings.jwks_url
    if not jwks_url:
        raise NotConfigured("No Supabase JWKS URL is configured")
    try:
        signing_key = _jwk_client(jwks_url).get_signing_key_from_jwt(token)
    except jwt.PyJWKClientError as exc:
        # Network trouble is not a bad session; the caller keeps the cookies.
        raise NotConfigured(f"Supabase JWKS is unavailable: {exc}") from exc
    return signing_key.key, getattr(signing_key, "algorithm_name", None) or algorithm


def jwt_mode() -> str:
    """Which verification keys the deployment has, without revealing them."""
    secret = bool(settings.supabase_jwt_secret)
    jwks = bool(settings.jwks_url)
    if secret and jwks:
        return "hs256+jwks"
    if secret:
        return "hs256"
    if jwks:
        return "jwks"
    return "none"


def verify_access_token(token: str) -> dict[str, Any]:
    """Verify a Supabase JWT locally. A failure is always a rejection."""
    if not token:
        raise InvalidToken("missing token")
    options = {"require": ["exp", "sub"], "verify_aud": True}
    kwargs: dict[str, Any] = {
        "audience": "authenticated",
        "options": options,
        "leeway": 10,
    }
    issuer = _issuer()
    if issuer:
        kwargs["issuer"] = issuer
    try:
        key, algorithm = _verification_material(token)
        claims = jwt.decode(token, key, algorithms=[algorithm], **kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidToken(str(exc)) from exc
    if not claims.get("sub"):
        raise InvalidToken("missing subject")
    return claims


def claims_profile(claims: dict[str, Any]) -> dict[str, Any]:
    """Profile columns implied by verified claims.

    Authorization comes from ``app_metadata`` only; ``user_metadata`` supplies
    display details and the workspace the account belongs to.
    """
    app_metadata = claims.get("app_metadata") or {}
    user_metadata = claims.get("user_metadata") or {}
    return {
        "email": (claims.get("email") or "").lower() or None,
        "role": role_or_viewer(app_metadata.get("role")),
        "display_name": user_metadata.get("display_name"),
        "is_guest": bool(claims.get("is_anonymous")),
        "workspace_id": user_metadata.get("workspace_id") or settings.default_workspace_id,
    }


# --------------------------------------------------------------------------- #
# Cookies
# --------------------------------------------------------------------------- #
def _cookie_common() -> dict[str, Any]:
    return {
        "path": "/",
        "domain": settings.cookie_domain or None,
        "secure": settings.session_secure,
        "samesite": "lax",
    }


def set_session_cookies(response: Any, tokens: AuthTokens) -> None:
    common = _cookie_common()
    access_age = tokens.expires_in or 3600
    response.set_cookie(
        ACCESS_COOKIE, tokens.access_token, httponly=True, max_age=access_age, **common
    )
    if tokens.refresh_token:
        response.set_cookie(
            REFRESH_COOKIE,
            tokens.refresh_token,
            httponly=True,
            max_age=_REFRESH_MAX_AGE,
            **common,
        )
    if tokens.csrf_token:
        response.set_cookie(
            CSRF_COOKIE,
            tokens.csrf_token,
            httponly=False,
            max_age=_REFRESH_MAX_AGE,
            **common,
        )


def clear_session_cookies(response: Any) -> None:
    common = _cookie_common()
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, **common)


# --------------------------------------------------------------------------- #
# Admin API
# --------------------------------------------------------------------------- #
def admin_list_users(page: int = 1, per_page: int = 1000) -> list[dict[str, Any]]:
    status, body = _request(
        "GET",
        "/auth/v1/admin/users",
        params={"page": page, "per_page": per_page},
        admin=True,
    )
    if status != 200:
        _raise_service_error(status, body, operation="list_users")
    users = body.get("users") if isinstance(body, dict) else None
    return [item for item in (users or []) if isinstance(item, dict)]


def find_user_by_email(email: str) -> dict[str, Any] | None:
    target = email.strip().lower()
    for page in range(1, max(1, settings.supabase_sync_max_pages) + 1):
        users = admin_list_users(page=page, per_page=1000)
        for user in users:
            if (user.get("email") or "").lower() == target:
                return user
        if len(users) < 1000:
            break
    return None


def admin_get_user(user_id: str) -> dict[str, Any] | None:
    status, body = _request(
        "GET", f"/auth/v1/admin/users/{user_id}", admin=True
    )
    if status == 404:
        return None
    if status != 200:
        _raise_service_error(status, body, operation="get_user")
    if isinstance(body, dict) and isinstance(body.get("user"), dict):
        return body["user"]
    return body if isinstance(body, dict) else None


def admin_create_user(
    *,
    email: str,
    password: str,
    role: str,
    display_name: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    user_metadata: dict[str, Any] = {}
    if display_name:
        user_metadata["display_name"] = display_name
    if workspace_id is not None:
        user_metadata["workspace_id"] = workspace_id
    status, body = _request(
        "POST",
        "/auth/v1/admin/users",
        json={
            "email": email,
            "password": password,
            "email_confirm": True,
            "app_metadata": {"role": role},
            "user_metadata": user_metadata,
        },
        admin=True,
    )
    if status in (400, 422) and "registered" in _payload_message(body).lower():
        raise Conflict("An account with this email already exists")
    if status not in (200, 201):
        _raise_service_error(status, body, operation="create_user")
    user = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user, dict):
        user = body if isinstance(body, dict) else {}
    logger.info("account created email=%s role=%s provider=supabase", email, role)
    return _public_user_from_go(user)


def admin_update_user(
    user_id: str,
    *,
    role: str | None = None,
    is_active: bool | None = None,
    password: str | None = None,
    email_confirm: bool | None = None,
) -> dict[str, Any] | None:
    current = admin_get_user(user_id)
    if current is None:
        return None
    payload: dict[str, Any] = {}
    if role is not None:
        # GoTrue replaces app_metadata wholesale, so merge instead of dropping
        # provider markers that Supabase itself put there.
        app_metadata = dict(current.get("app_metadata") or {})
        app_metadata["role"] = role
        payload["app_metadata"] = app_metadata
    if password is not None:
        payload["password"] = password
    if email_confirm is not None:
        payload["email_confirm"] = email_confirm
    if is_active is not None:
        payload["ban_duration"] = "none" if is_active else "876000h"
    status, body = _request(
        "PUT", f"/auth/v1/admin/users/{user_id}", json=payload, admin=True
    )
    if status not in (200, 201):
        _raise_service_error(status, body, operation="update_user")
    user = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user, dict):
        user = body if isinstance(body, dict) else {}
    return _public_user_from_go(user)


def admin_delete_user(user_id: str) -> bool:
    status, body = _request(
        "DELETE", f"/auth/v1/admin/users/{user_id}", admin=True
    )
    if status == 404:
        return False
    if status not in (200, 204):
        _raise_service_error(status, body, operation="delete_user")
    return True


def admin_create(
    *,
    email: str,
    password: str,
    role: str,
    display_name: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    return admin_create_user(
        email=email,
        password=password,
        role=role,
        display_name=display_name,
        workspace_id=workspace_id,
    )


def admin_update(
    user_id: str,
    *,
    role: str | None = None,
    is_active: bool | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any] | None:
    return admin_update_user(user_id, role=role, is_active=is_active)


def admin_delete(user_id: str, workspace_id: str | None = None) -> bool:
    return admin_delete_user(user_id)


def sync_profiles() -> int:
    """Pull GoTrue users into ``profiles``; capped so a loop cannot run away."""
    synced = 0
    max_pages = max(1, settings.supabase_sync_max_pages)
    for page in range(1, max_pages + 1):
        users = admin_list_users(page=page, per_page=1000)
        for user in users:
            _upsert_from_go(user)
            synced += 1
        if len(users) < 1000:
            break
    return synced


def _upsert_from_go(user: dict[str, Any]) -> dict[str, Any] | None:
    if not user.get("id"):
        return None
    mapped = _public_user_from_go(user)
    return db.upsert_profile(
        profile_id=mapped["id"],
        email=mapped.get("email"),
        role=mapped["role"],
        display_name=mapped.get("display_name"),
        is_guest=bool(mapped.get("is_guest")),
        is_active=None,
        last_sign_in_at=mapped.get("last_sign_in_at"),
        workspace_id=mapped.get("workspace_id") or settings.default_workspace_id,
    )


def upsert_from_auth_result(result: AuthResult) -> dict[str, Any]:
    """Persist the profile after login or registration."""
    user = result.user
    profile = db.get_profile(user["id"])
    # GoTrue carries the workspace in ``user_metadata``; ``_public_user_from_go``
    # copies it into the AuthResult user so both login and register can scope it.
    # Accept the raw metadata too, for results built directly from a GoTrue user.
    # Accounts created before workspaces existed land in the default one.
    metadata = user.get("user_metadata") or {}
    workspace_id = user.get("workspace_id") or metadata.get("workspace_id")
    if not workspace_id and profile is not None:
        workspace_id = profile.get("workspace_id")
    workspace_id = workspace_id or settings.default_workspace_id
    return db.upsert_profile(
        profile_id=user["id"],
        email=user.get("email"),
        role=role_or_viewer(profile["role"] if profile else user.get("role")),
        display_name=user.get("display_name"),
        is_guest=bool(user.get("is_guest")),
        # Never re-enable a disabled account by signing in.
        is_active=None,
        last_sign_in_at=user.get("last_sign_in_at") or db.now_iso(),
        workspace_id=workspace_id,
    )


def target(user_id: str, workspace_id: str | None = None) -> dict[str, Any] | None:
    return db.get_profile(user_id, workspace_id=workspace_id)


def admin_list(
    *,
    q: str = "",
    include_guests: bool = False,
    page: int = 1,
    page_size: int = 20,
    workspace_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    return db.list_profiles(
        q=q,
        include_guests=include_guests,
        page=page,
        page_size=page_size,
        workspace_id=workspace_id,
    )


def count_active_admins(workspace_id: str | None = None) -> int:
    return db.count_active_admins(workspace_id=workspace_id)


def admin_reset(user_id: str, workspace_id: str | None = None) -> None:
    record = db.get_profile(user_id, workspace_id=workspace_id)
    if record is None or not record.get("email"):
        # Stay silent: the response is always 202.
        return
    recover(record["email"], settings.password_reset_redirect_to or None)


def bootstrap_admin() -> bool:
    """Create or repair the operator in Supabase at startup (idempotent)."""
    email = auth.normalise_email(settings.admin_email)
    password = settings.admin_password or ""
    if not email or not password:
        return False
    if not auth.valid_email(email):
        logger.error("supabase admin bootstrap skipped: ADMIN_EMAIL is not valid")
        return False
    problem = auth.password_error(password)
    if problem:
        logger.error("supabase admin bootstrap skipped: %s", problem)
        return False
    if not admin_configured():
        logger.error(
            "supabase admin bootstrap skipped: SUPABASE_URL, SUPABASE_ANON_KEY "
            "and SUPABASE_SERVICE_ROLE_KEY are required"
        )
        return False

    try:
        existing = find_user_by_email(email)
        if existing is None:
            try:
                created = admin_create_user(
                    email=email,
                    password=password,
                    role="admin",
                    display_name="Administrator",
                )
            except Conflict:
                existing = find_user_by_email(email)
                if existing is None:
                    raise
            else:
                db.upsert_profile(
                    profile_id=created["id"],
                    email=email,
                    role="admin",
                    display_name="Administrator",
                    is_guest=False,
                    is_active=True,
                    workspace_id=settings.default_workspace_id,
                )
                logger.info("admin account ready email=%s role=admin", email)
                return True

        if existing is None:
            return False
        repaired = admin_update_user(
            existing["id"],
            role="admin",
            is_active=True,
            password=password,
            email_confirm=True,
        )
        if repaired is None:
            return False
        db.upsert_profile(
            profile_id=repaired["id"],
            email=email,
            role="admin",
            display_name=repaired.get("display_name") or "Administrator",
            is_guest=bool(repaired.get("is_guest")),
            is_active=True,
            workspace_id=settings.default_workspace_id,
        )
        logger.info("admin account repaired email=%s role=admin", email)
        return True
    except IdentityError as exc:
        logger.error("supabase admin bootstrap failed: %s", exc.detail)
        return False
    except Exception:  # noqa: BLE001 - startup must not crash on a network blip
        logger.exception("supabase admin bootstrap failed unexpectedly")
        return False
