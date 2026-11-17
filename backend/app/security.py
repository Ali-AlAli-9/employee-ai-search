"""Authentication: API keys *or* a session cookie, resolved to one Principal.

Both credentials are accepted side by side:

* ``X-API-Key`` keeps working for scripts and CI and carries a role, exactly as
  before (its principal id *is* the role name, so old history stays readable).
* a browser session. In ``local`` mode that is ``eais_session`` backed by a
  server-side row; in Supabase mode it is ``eais_access``/``eais_refresh``.

Unsafe cookie-authenticated methods need ``X-CSRF-Token``: a hashed comparison in
local mode, and a stateless double submit against the readable ``eais_csrf``
cookie in Supabase mode. API keys are exempt in both.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request, Response, status

from . import auth, db, identity
from .config import settings
from .identity import InvalidToken, NotConfigured, TokenExpired, supabase

logger = logging.getLogger(__name__)

ROLE_LEVEL = {"viewer": 1, "user": 2, "admin": 3}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class Principal:
    """Who is calling: an API key, or a signed-in user."""

    id: str
    role: str
    kind: str = "api_key"
    email: str | None = None
    is_guest: bool = False
    # Local mode stores a hash; Supabase mode needs the raw cookie value for
    # the stateless double submit. Exactly one of them is set.
    csrf_hash: str | None = None
    csrf_token: str | None = None
    # Every downstream query is scoped to this workspace. API keys get the
    # well-known default; sessions carry the id from their user/profile row.
    workspace_id: str = settings.default_workspace_id


def resolve_role(api_key: str | None) -> str | None:
    if not api_key:
        return None
    return settings.api_keys.get(api_key)


def _unauthorised(detail: str = "Invalid or missing credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "ApiKey"},
    )


def _from_local_session(request: Request) -> Principal | None:
    token = request.cookies.get(auth.SESSION_COOKIE)
    if not token:
        return None
    session = identity.local.session_user(token)
    if session is None:
        return None
    return Principal(
        id=session["id"],
        role=session["role"],
        kind="session",
        email=session["email"],
        is_guest=bool(session.get("is_guest")),
        csrf_hash=session["csrf_hash"],
        workspace_id=session.get("workspace_id") or settings.default_workspace_id,
    )


def _profile_for_claims(claims: dict) -> dict | None:
    """Read the authorization row, repairing it from claims on first sight."""
    subject = str(claims.get("sub") or "")
    if not subject:
        return None
    profile = db.get_profile(subject)
    if profile is not None:
        return profile
    fields = supabase.claims_profile(claims)
    return db.upsert_profile(
        profile_id=subject,
        email=fields["email"],
        role=fields["role"],
        display_name=fields["display_name"],
        is_guest=fields["is_guest"],
        is_active=None,
        last_sign_in_at=db.now_iso(),
        workspace_id=fields.get("workspace_id"),
    )


def _from_supabase_session(request: Request, response: Response) -> Principal | None:
    access = request.cookies.get(supabase.ACCESS_COOKIE)
    refresh_token = request.cookies.get(supabase.REFRESH_COOKIE)

    claims: dict | None = None
    if access:
        try:
            claims = supabase.verify_access_token(access)
        except TokenExpired:
            claims = None
        except NotConfigured as exc:
            # A missing or unreachable verification key is a deployment
            # problem, not a bad session: keep the cookies so fixing the
            # configuration restores every visitor without a re-login.
            logger.error("session unverifiable reason=no_verifier detail=%s", exc)
            return None
        except InvalidToken as exc:
            # A forged or foreign-signed token is never retried against the
            # refresh endpoint; drop the cookies and treat it as anonymous.
            logger.warning("session rejected reason=invalid_token detail=%s", exc)
            supabase.clear_session_cookies(response)
            return None

    if claims is None and refresh_token:
        try:
            refreshed = supabase.refresh(refresh_token)
        except (identity.IdentityError, InvalidToken, TokenExpired) as exc:
            logger.warning(
                "session rejected reason=refresh_failed detail=%s", type(exc).__name__
            )
            supabase.clear_session_cookies(response)
            return None
        # Rotation is invisible to the browser. The CSRF cookie is deliberately
        # left untouched so an in-flight form keeps working.
        supabase.set_session_cookies(response, refreshed.tokens)
        try:
            claims = supabase.verify_access_token(refreshed.tokens.access_token)
        except (InvalidToken, TokenExpired):
            supabase.clear_session_cookies(response)
            return None

    if claims is None:
        return None

    profile = _profile_for_claims(claims)
    if profile is None or not profile.get("is_active"):
        # Deactivation is effective on this request, not after the JWT expires.
        logger.info(
            "session rejected reason=inactive_or_missing_profile subject=%s",
            claims.get("sub"),
        )
        return None

    claims_workspace = (claims.get("user_metadata") or {}).get("workspace_id")
    return Principal(
        id=profile["id"],
        role=profile["role"],
        kind="session",
        email=profile.get("email"),
        is_guest=bool(profile.get("is_guest")),
        csrf_token=request.cookies.get(supabase.CSRF_COOKIE),
        workspace_id=(
            profile.get("workspace_id")
            or claims_workspace
            or settings.default_workspace_id
        ),
    )


def resolve_principal(
    request: Request, api_key: str | None, response: Response | None = None
) -> Principal:
    if api_key:
        role = resolve_role(api_key)
        if role is None:
            raise _unauthorised("Invalid or missing API key")
        # The role doubles as the principal id for API keys: existing script
        # history and uploaded_by rows keep their old partition.
        return Principal(
            id=role,
            role=role,
            kind="api_key",
            workspace_id=settings.default_workspace_id,
        )

    if identity.is_local():
        principal = _from_local_session(request)
    else:
        principal = (
            _from_supabase_session(request, response)
            if response is not None
            else None
        )
    if principal is not None:
        return principal
    raise _unauthorised()


def _enforce_csrf(request: Request, principal: Principal) -> None:
    if principal.kind != "session":
        return  # API keys are not ambient credentials, so CSRF does not apply.
    if request.method.upper() in _SAFE_METHODS:
        return
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied:
        raise _csrf_failure()
    if identity.is_local():
        stored = principal.csrf_hash or ""
        valid = bool(stored) and hmac.compare_digest(auth.hash_token(supplied), stored)
    else:
        stored = principal.csrf_token or ""
        valid = bool(stored) and hmac.compare_digest(supplied, stored)
    if not valid:
        raise _csrf_failure()


def _csrf_failure() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Missing or invalid CSRF token",
    )


def require_role(minimum: str):
    """FastAPI dependency factory enforcing a minimum role (viewer < user < admin)."""

    minimum_level = ROLE_LEVEL[minimum]

    def checker(
        request: Request,
        response: Response,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> Principal:
        principal = resolve_principal(request, x_api_key, response)
        if ROLE_LEVEL.get(principal.role, 0) < minimum_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires '{minimum}' role or higher",
            )
        _enforce_csrf(request, principal)
        return principal

    return checker
