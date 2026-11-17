"""Passwords, session tokens and cookies.

Everything security-sensitive about accounts lives here so the HTTP layer stays
thin:

* passwords: stdlib ``hashlib.scrypt`` with a per-user salt, never logged;
* sessions: random token, only ``sha256(token)`` reaches the database;
* CSRF: a second random token whose hash is stored beside the session;
* cookies: ``eais_session`` (HttpOnly) and ``eais_csrf`` (readable).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Response

from . import db
from .config import settings

logger = logging.getLogger(__name__)

SESSION_COOKIE = "eais_session"
CSRF_COOKIE = "eais_csrf"
ROLES = ("viewer", "user", "admin")

# scrypt at n=2**14 keeps verification well under a second on a 0.1 CPU
# instance while still being memory-hard (16 MiB per hash).
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
# A precomputed hash for unknown emails: verifying it costs the same as a real
# check, so response timing does not reveal whether an account exists.
_DUMMY_HASH = ""


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    """Return ``scrypt$n$r$p$salt$hash``; the plaintext is never stored."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = (stored or "").split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def hash_token(token: str) -> str:
    """Sessions and CSRF tokens are stored only as their SHA-256 hex digest."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


def password_error(password: str) -> str | None:
    """A human-readable reason, or ``None`` when the password is acceptable."""
    minimum = max(1, settings.password_min_length)
    if len(password or "") < minimum:
        return f"Password must be at least {minimum} characters"
    if len(password) > 200:
        return "Password is too long"
    return None


def new_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=settings.session_ttl_hours)).isoformat()


def is_expired(expires_at: str, now: datetime | None = None) -> bool:
    try:
        moment = datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment <= (now or datetime.now(timezone.utc))


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    """The safe projection of a ``users`` row (never a hash)."""
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "display_name": user.get("display_name"),
        "is_guest": bool(user.get("is_guest")),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


# --------------------------------------------------------------------------- #
# Cookies
# --------------------------------------------------------------------------- #
def _cookie_kwargs() -> dict[str, Any]:
    return {
        "max_age": settings.session_ttl_seconds,
        "path": "/",
        "domain": settings.cookie_domain or None,
        "secure": settings.session_secure,
        "samesite": "lax",
    }


def set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    common = _cookie_kwargs()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf_token, httponly=False, **common)


def clear_session_cookies(response: Response) -> None:
    common = _cookie_kwargs()
    common["max_age"] = 0
    response.delete_cookie(SESSION_COOKIE, **{k: v for k, v in common.items() if k != "max_age"})
    response.delete_cookie(CSRF_COOKIE, **{k: v for k, v in common.items() if k != "max_age"})


def start_session(user_id: str, user_agent: str | None = None) -> tuple[str, str]:
    """Create a session row; return ``(raw_token, raw_csrf_token)``."""
    token = new_session_token()
    csrf_token = new_csrf_token()
    db.create_session(
        user_id=user_id,
        token_hash=hash_token(token),
        csrf_hash=hash_token(csrf_token),
        expires_at=new_expiry(),
        user_agent=(user_agent or "")[:200] or None,
    )
    return token, csrf_token


# --------------------------------------------------------------------------- #
# Registration helpers
# --------------------------------------------------------------------------- #
def invite_accepted(code: str) -> bool:
    """Constant-time check against the configured invite code.

    Callers only enforce this when ``settings.invite_code`` is set; an empty
    setting means registration is public, not "no code ever matches".
    """
    if not settings.invite_code:
        return False
    return hmac.compare_digest((code or "").strip(), settings.invite_code)


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    """Return the user row for valid credentials, else ``None``.

    Unknown emails still pay for one scrypt verification, so the response time
    does not disclose which half of the pair was wrong.
    """
    global _DUMMY_HASH
    user = db.get_user_by_email(normalise_email(email))
    if user is None:
        if not _DUMMY_HASH:
            _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    if not user.get("is_active"):
        return None
    return user


def bootstrap_admin() -> bool:
    """Create or repair the operator's admin account from the environment.

    Idempotent and env-as-source-of-truth: a redeploy repairs a deleted,
    demoted or password-changed admin. Passwords are never logged.
    """
    email = normalise_email(settings.admin_email)
    password = settings.admin_password or ""
    if not email or not password:
        return False
    if not valid_email(email):
        logger.error("admin bootstrap skipped: ADMIN_EMAIL is not a valid address")
        return False
    problem = password_error(password)
    if problem:
        logger.error("admin bootstrap skipped: %s", problem)
        return False

    # The bootstrap account always lives in the default workspace; make sure
    # that row exists before creating or repairing the user.
    db.default_workspace()
    workspace_id = settings.default_workspace_id

    password_hash = hash_password(password)
    existing = db.get_user_by_email(email)
    if existing is not None:
        db.update_user(
            existing["id"],
            password_hash=password_hash,
            role="admin",
            is_active=1,
            workspace_id=workspace_id,
        )
        logger.info("admin account repaired email=%s role=admin", email)
        return True

    try:
        db.create_user(
            email=email,
            password_hash=password_hash,
            role="admin",
            display_name="Administrator",
            workspace_id=workspace_id,
        )
    except db.IntegrityErrors:
        # Another instance won the race at startup.
        existing = db.get_user_by_email(email)
        if existing is None:
            raise
        db.update_user(
            existing["id"],
            password_hash=password_hash,
            role="admin",
            is_active=1,
            workspace_id=workspace_id,
        )
    logger.info("admin account ready email=%s role=admin", email)
    return True
