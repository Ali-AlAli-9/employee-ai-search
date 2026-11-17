"""Provider-neutral value objects shared by the local and Supabase identities.

The HTTP layer only sees :class:`AuthResult` and :class:`IdentityError`, so a
route never branches on GoTrue response shapes or on the spec-004 session rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ROLES = ("viewer", "user", "admin")


@dataclass(frozen=True)
class AuthTokens:
    """What the browser must keep, independent of the provider.

    ``access_token`` is a local session token or a Supabase access JWT,
    ``refresh_token`` is only set by Supabase and ``csrf_token`` is the raw
    double-submit value. ``expires_in`` is the access token lifetime in seconds.
    """

    access_token: str
    refresh_token: str | None = None
    csrf_token: str | None = None
    expires_in: int | None = None


@dataclass(frozen=True)
class AuthResult:
    user: dict[str, Any]
    tokens: AuthTokens
    # Set by registration so the browser can show the new workspace (and its
    # invite code). Login deliberately leaves it ``None``.
    workspace: dict[str, Any] | None = None


class IdentityError(Exception):
    """A provider failure that maps directly to an HTTP response."""

    status_code = 400

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class InvalidCredentials(IdentityError):
    status_code = 401

    def __init__(self) -> None:
        super().__init__("Invalid email or password")


class BadRequest(IdentityError):
    status_code = 400


class Conflict(IdentityError):
    status_code = 409


class NotConfigured(IdentityError):
    status_code = 503


class ProviderUnavailable(IdentityError):
    status_code = 502


class NotSupported(IdentityError):
    status_code = 501


class TokenExpired(Exception):
    """The access token is well-formed but past ``exp``."""


class InvalidToken(Exception):
    """The access token is malformed, unsigned, or signed by an unknown key."""


def role_or_viewer(value: Any) -> str:
    return value if value in ROLES else "viewer"


def public_user(record: dict[str, Any]) -> dict[str, Any]:
    """A safe projection of a local ``users`` row or a ``profiles`` row."""
    return {
        "id": record["id"],
        "email": record.get("email"),
        "role": role_or_viewer(record.get("role")),
        "display_name": record.get("display_name"),
        "is_guest": bool(record.get("is_guest")),
        "workspace_id": record.get("workspace_id"),
        "created_at": record.get("created_at"),
        "last_login_at": record.get("last_login_at"),
        "last_sign_in_at": record.get("last_sign_in_at"),
    }


def admin_user(record: dict[str, Any]) -> dict[str, Any]:
    """The admin table adds the enable/disable flag and normalises booleans."""
    item = public_user(record)
    item["is_active"] = bool(record.get("is_active", True))
    return item
