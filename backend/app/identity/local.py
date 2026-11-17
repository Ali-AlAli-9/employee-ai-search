"""The spec-004 provider: scrypt passwords, server-side sessions, local CSRF.

Keeping this implementation means the test suite and an offline checkout never
need a Supabase project. Everything here writes the same ``users``/``sessions``
tables that shipped in spec 004.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import auth, db
from ..config import settings
from .base import (
    AuthResult,
    AuthTokens,
    Conflict,
    InvalidCredentials,
    NotSupported,
    admin_user,
    public_user,
)

logger = logging.getLogger(__name__)


def _session(user: dict[str, Any], user_agent: str | None) -> AuthResult:
    token, csrf_token = auth.start_session(user["id"], user_agent)
    return AuthResult(
        user=public_user(user),
        tokens=AuthTokens(
            access_token=token,
            refresh_token=None,
            csrf_token=csrf_token,
            expires_in=settings.session_ttl_seconds,
        ),
    )


def login(email: str, password: str, user_agent: str | None = None) -> AuthResult:
    user = auth.authenticate(email, password)
    if user is None:
        raise InvalidCredentials()
    db.update_user(user["id"], last_login_at=db.now_iso())
    refreshed = db.get_user(user["id"]) or user
    return _session(refreshed, user_agent)


def register(
    email: str,
    password: str,
    display_name: str | None = None,
    user_agent: str | None = None,
    *,
    workspace_id: str | None = None,
    role: str = "user",
) -> AuthResult:
    try:
        user = db.create_user(
            email=email,
            password_hash=auth.hash_password(password),
            role=role,
            display_name=display_name,
            workspace_id=workspace_id,
        )
    except db.IntegrityErrors as exc:
        raise Conflict("An account with this email already exists") from exc
    logger.info("account created email=%s role=%s", email, role)
    return _session(user, user_agent)


def logout(access_token: str | None) -> None:
    if access_token:
        db.delete_session(auth.hash_token(access_token))


def session_user(access_token: str | None) -> dict[str, Any] | None:
    """Resolve a raw local session token to its active user row."""
    if not access_token:
        return None
    token_hash = auth.hash_token(access_token)
    session = db.get_session(token_hash)
    if session is None:
        return None
    if auth.is_expired(session["expires_at"]):
        db.delete_session(token_hash)
        return None
    user = db.get_user(session["user_id"])
    if user is None or not user.get("is_active"):
        return None
    return {**user, "csrf_hash": session["csrf_hash"]}


def public_session(
    principal_id: str, workspace_id: str | None = None
) -> dict[str, Any] | None:
    user = db.get_user(principal_id, workspace_id=workspace_id)
    return public_user(user) if user else None


# --------------------------------------------------------------------------- #
# Administration (local tables)
# --------------------------------------------------------------------------- #
def admin_list(
    *,
    q: str = "",
    include_guests: bool = False,
    page: int = 1,
    page_size: int = 20,
    workspace_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    items, total = db.list_users(
        q=q,
        include_guests=include_guests,
        page=page,
        page_size=page_size,
        workspace_id=workspace_id,
    )
    return [admin_user(item) for item in items], total


def admin_create(
    *,
    email: str,
    password: str,
    role: str,
    display_name: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    try:
        user = db.create_user(
            email=email,
            password_hash=auth.hash_password(password),
            role=role,
            display_name=display_name,
            workspace_id=workspace_id,
        )
    except db.IntegrityErrors as exc:
        raise Conflict("An account with this email already exists") from exc
    logger.info("account created email=%s role=%s", email, role)
    return admin_user(user)


def admin_update(
    user_id: str,
    *,
    role: str | None = None,
    is_active: bool | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any] | None:
    fields: dict[str, Any] = {}
    if role is not None:
        fields["role"] = role
    if is_active is not None:
        fields["is_active"] = 1 if is_active else 0
    if fields:
        db.update_user(user_id, workspace_id=workspace_id, **fields)
    user = db.get_user(user_id, workspace_id=workspace_id)
    return admin_user(user) if user else None


def admin_reset(user_id: str, workspace_id: str | None = None) -> None:
    raise NotSupported("Password reset requires Supabase Auth")


def admin_delete(user_id: str, workspace_id: str | None = None) -> bool:
    return db.delete_user(user_id, workspace_id=workspace_id)


def count_active_admins(workspace_id: str | None = None) -> int:
    return db.count_active_user_admins(workspace_id=workspace_id)


def target(user_id: str, workspace_id: str | None = None) -> dict[str, Any] | None:
    return db.get_user(user_id, workspace_id=workspace_id)


def sync() -> int:
    return 0


def bootstrap_admin() -> bool:
    return auth.bootstrap_admin()



