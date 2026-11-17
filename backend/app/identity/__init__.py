"""Identity facade: one API for the local provider and Supabase Auth.

Routes and dependencies import this module, never a provider directly, so an
offline checkout (``AUTH_PROVIDER=local``) and a Supabase deployment run the
same HTTP surface.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import replace
from typing import Any

from fastapi import Request, Response

from .. import auth, db
from ..config import settings
from . import local, supabase
from .base import (
    AuthResult,
    AuthTokens,
    BadRequest,
    Conflict,
    IdentityError,
    InvalidCredentials,
    InvalidToken,
    NotConfigured,
    NotSupported,
    ProviderUnavailable,
    TokenExpired,
    admin_user,
    public_user,
    role_or_viewer,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AuthResult",
    "AuthTokens",
    "BadRequest",
    "Conflict",
    "IdentityError",
    "InvalidCredentials",
    "InvalidToken",
    "NotConfigured",
    "NotSupported",
    "ProviderUnavailable",
    "TokenExpired",
    "admin_configured",
    "admin_create",
    "admin_delete",
    "admin_list",
    "admin_reset",
    "admin_update",
    "bootstrap_admin",
    "clear_cookies",
    "count_active_admins",
    "health",
    "is_local",
    "login",
    "logout",
    "provider_name",
    "public_session",
    "register",
    "set_cookies",
    "set_password",
    "sync",
    "target",
]


def provider_name() -> str:
    return "supabase" if settings.auth_provider == "supabase" else "local"


def is_local() -> bool:
    return provider_name() == "local"


def _module():
    return local if is_local() else supabase


def admin_configured() -> bool:
    return True if is_local() else supabase.admin_configured()


def health() -> dict[str, Any]:
    """Secret-free provider flags for ``/health``."""
    name = provider_name()
    configured = True if name == "local" else supabase.auth_configured()
    admin_api = True if name == "local" else supabase.admin_configured()
    return {
        "status": "healthy" if configured else "unconfigured",
        "provider": name,
        "configured": configured,
        "demo": False,
        "registration": True,
        "invite_required": bool(settings.invite_code),
        "password_reset": name == "supabase",
        "admin_api": admin_api,
        # Which keys can verify a session token. `jwks` is what projects with
        # asymmetric (ES256) signing keys need; without it every session is
        # rejected even though sign-in succeeded.
        "jwt": "local" if name == "local" else supabase.jwt_mode(),
    }


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def login(email: str, password: str, user_agent: str | None = None) -> AuthResult:
    result = _module().login(email, password, user_agent)
    if not is_local():
        profile = supabase.upsert_from_auth_result(result)
        if not profile.get("is_active"):
            # A disabled account must not get a fresh session even though
            # GoTrue still accepted the password.
            supabase.logout(result.tokens.access_token)
            raise InvalidCredentials()
    return result


def _public_workspace(workspace: dict[str, Any]) -> dict[str, Any]:
    """The workspace fields a browser is allowed to see."""

    shown = db.public_workspace(workspace)
    return {
        "id": shown["id"],
        "name": shown["name"],
        "invite_code": shown["invite_code"],
    }


def register(
    email: str,
    password: str,
    display_name: str | None = None,
    user_agent: str | None = None,
    kind: str = "member",
    workspace_name: str | None = None,
    invite_code: str | None = None,
) -> AuthResult:
    """Register an employer (new workspace) or a member (existing workspace)."""

    if kind not in ("employer", "member"):
        raise BadRequest("Choose employer or member registration")

    workspace: dict[str, Any] | None = None
    if kind == "employer":
        name = (workspace_name or "").strip()
        if not name:
            raise BadRequest("A workspace name is required")
        workspace = db.create_workspace(
            name=name, invite_code=secrets.token_urlsafe(12)
        )
        workspace_id, role = workspace["id"], "admin"
    else:
        code = (invite_code or "").strip()
        workspace = db.get_workspace_by_invite(code) if code else None
        if workspace is None:
            # Legacy global code: the deployment's shared code maps members to
            # the well-known default workspace instead of a generated invite.
            if settings.invite_code and auth.invite_accepted(code):
                workspace = db.default_workspace()
            if workspace is None:
                raise BadRequest("Invalid invite code", status_code=403)
        workspace_id, role = workspace["id"], "user"

    try:
        result = _module().register(
            email,
            password,
            display_name,
            user_agent,
            workspace_id=workspace_id,
            role=role,
        )
    except Exception:
        # Never leave an orphan workspace behind when the account itself could
        # not be created (duplicate email, provider outage, validation failure).
        if kind == "employer":
            db.delete_workspace(workspace_id)
        raise
    if kind == "employer":
        db.set_workspace_owner(workspace_id, result.user["id"])
    if workspace is not None:
        result = replace(result, workspace=_public_workspace(workspace))
    if not is_local():
        supabase.upsert_from_auth_result(result)
    return result


def logout(request: Request) -> None:
    if is_local():
        local.logout(request.cookies.get(auth.SESSION_COOKIE))
        return
    access = request.cookies.get(supabase.ACCESS_COOKIE)
    refresh_token = request.cookies.get(supabase.REFRESH_COOKIE)
    if refresh_token:
        try:
            refreshed = supabase.refresh(refresh_token)
            access = refreshed.tokens.access_token
        except (IdentityError, InvalidToken, TokenExpired):
            pass
    supabase.logout(access)


def set_cookies(response: Response, tokens: AuthTokens) -> None:
    if is_local():
        assert tokens.csrf_token is not None
        auth.set_session_cookies(response, tokens.access_token, tokens.csrf_token)
    else:
        supabase.set_session_cookies(response, tokens)


def clear_cookies(response: Response) -> None:
    if is_local():
        auth.clear_session_cookies(response)
    else:
        supabase.clear_session_cookies(response)


def public_session(
    principal_id: str, workspace_id: str | None = None
) -> dict[str, Any] | None:
    if is_local():
        return local.public_session(principal_id, workspace_id=workspace_id)
    profile = db.get_profile(principal_id, workspace_id=workspace_id)
    return public_user(profile) if profile else None


# --------------------------------------------------------------------------- #
# Administration
# --------------------------------------------------------------------------- #
def admin_list(
    *,
    q: str = "",
    include_guests: bool = False,
    page: int = 1,
    page_size: int = 20,
    workspace_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    return _module().admin_list(
        q=q,
        include_guests=include_guests,
        page=page,
        page_size=page_size,
        workspace_id=workspace_id,
    )


def admin_create(
    *,
    email: str,
    password: str,
    role: str,
    display_name: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    created = _module().admin_create(
        email=email,
        password=password,
        role=role,
        display_name=display_name,
        workspace_id=workspace_id,
    )
    if not is_local():
        db.upsert_profile(
            profile_id=created["id"],
            email=created.get("email"),
            role=role,
            display_name=created.get("display_name") or display_name,
            is_guest=False,
            is_active=True,
            workspace_id=workspace_id,
        )
    return created


def admin_update(
    user_id: str,
    *,
    role: str | None = None,
    is_active: bool | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any] | None:
    updated = _module().admin_update(
        user_id, role=role, is_active=is_active, workspace_id=workspace_id
    )
    if updated is None:
        return None
    if not is_local():
        current = db.get_profile(user_id, workspace_id=workspace_id)
        db.upsert_profile(
            profile_id=user_id,
            email=updated.get("email"),
            role=role_or_viewer(role if role is not None else (current or updated).get("role")),
            display_name=updated.get("display_name"),
            is_guest=bool(updated.get("is_guest")),
            is_active=is_active if is_active is not None else None,
            last_sign_in_at=updated.get("last_sign_in_at"),
            workspace_id=workspace_id,
        )
        return admin_user(
            db.get_profile(user_id, workspace_id=workspace_id) or updated
        )
    return updated


def admin_reset(user_id: str, workspace_id: str | None = None) -> None:
    _module().admin_reset(user_id, workspace_id=workspace_id)


def set_password(access_token: str, password: str) -> None:
    """Finish a password recovery, using the token from the email link."""
    if is_local():
        raise NotSupported("Password reset requires Supabase Auth")
    supabase.set_password(access_token, password)


def admin_delete(user_id: str, workspace_id: str | None = None) -> bool:
    deleted = _module().admin_delete(user_id, workspace_id=workspace_id)
    if not is_local():
        db.delete_profile(user_id, workspace_id=workspace_id)
    return deleted


def sync() -> int:
    if is_local():
        return 0
    return supabase.sync_profiles()


def target(user_id: str, workspace_id: str | None = None) -> dict[str, Any] | None:
    return _module().target(user_id, workspace_id=workspace_id)


def count_active_admins(workspace_id: str | None = None) -> int:
    return _module().count_active_admins(workspace_id=workspace_id)


def bootstrap_admin() -> bool:
    return _module().bootstrap_admin()
