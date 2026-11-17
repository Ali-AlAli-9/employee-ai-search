"""HTTP surface for accounts: register, login, logout, me and admin.

The same routes serve both identity providers. Supabase owns credentials in
deployments; the local provider keeps the offline test suite working. Routes
never branch on provider response shapes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from . import auth, db, identity
from .ratelimit import rate_limit
from .schemas import (
    AdminUserUpdate,
    CreateUserRequest,
    LoginRequest,
    PasswordResetRequest,
    RegisterRequest,
)
from .security import Principal, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _user_agent(request: Request) -> str | None:
    value = request.headers.get("user-agent")
    return value[:200] if value else None


def _session_response(
    result: identity.AuthResult, status_code: int = 200
) -> Response:
    response = JSONResponse(
        {
            "user": result.user,
            "csrf_token": result.tokens.csrf_token or "",
            # Registration supplies the workspace; login intentionally leaves
            # the key present but null so clients can rely on its shape.
            "workspace": result.workspace,
        },
        status_code=status_code,
    )
    identity.set_cookies(response, result.tokens)
    return response


def _provider_error(exc: identity.IdentityError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _login_locked(retry_after: int) -> HTTPException:
    """One generic message; the frontend maps 429 to its own localised copy."""
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many login attempts. Try again shortly.",
        headers={"Retry-After": str(max(1, retry_after))},
    )


def _validate_credentials(email: str, password: str) -> str:
    normalised = auth.normalise_email(email)
    if not auth.valid_email(normalised):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    problem = auth.password_error(password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    return normalised


# --------------------------------------------------------------------------- #
# Session routes
# --------------------------------------------------------------------------- #
@router.post("/register")
def register(
    payload: RegisterRequest,
    request: Request,
    _rate: None = Depends(rate_limit("auth")),
) -> Response:
    # Workspace/invite validation lives in the identity facade so both
    # providers enforce the same rule: employers create a workspace, members
    # join one with its invite code (or the legacy global code).
    email = _validate_credentials(payload.email, payload.password)
    try:
        result = identity.register(
            email=email,
            password=payload.password,
            display_name=(payload.display_name or "").strip() or None,
            user_agent=_user_agent(request),
            kind=payload.kind,
            workspace_name=payload.workspace_name,
            invite_code=payload.invite_code,
        )
    except identity.Conflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=exc.detail
        ) from exc
    except identity.IdentityError as exc:
        raise _provider_error(exc) from exc
    return _session_response(result)


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    _rate: None = Depends(rate_limit("auth")),
) -> Response:
    # Account lockout is the second axis beside the per-IP token bucket: an
    # attacker rotating source addresses still hits one key per email.
    db.sweep_login_attempts()
    login_key = db.normalise_login_key(payload.email)
    locked, retry_after = db.login_lock_status(login_key)
    if locked:
        raise _login_locked(retry_after)

    try:
        result = identity.login(
            payload.email, payload.password, _user_agent(request)
        )
    except identity.InvalidCredentials as exc:
        # Count unknown emails too; otherwise a 429 would reveal which accounts
        # exist. Provider outages below are deliberately not counted.
        locked, retry_after = db.record_login_failure(login_key)
        if locked:
            raise _login_locked(retry_after) from exc
        raise _provider_error(exc) from exc
    except identity.IdentityError as exc:
        raise _provider_error(exc) from exc

    db.clear_login_attempts(login_key)
    return _session_response(result)


@router.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    """Idempotent: deleting your own cookie is safe even without a session."""
    identity.logout(request)
    response = Response(status_code=204)
    identity.clear_cookies(response)
    return response


@router.post("/password-reset", status_code=204)
def complete_password_reset(
    payload: PasswordResetRequest,
    _rate: None = Depends(rate_limit("auth")),
) -> Response:
    """Finish a recovery link: the browser posts its access token and a new password.

    Unauthenticated by design (the emailed token *is* the credential) but subject
    to the auth rate limit. The server never stores or logs either value.
    """
    if identity.is_local():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Password reset requires Supabase Auth",
        )
    problem = auth.password_error(payload.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    try:
        identity.set_password(payload.access_token, payload.password)
    except identity.IdentityError as exc:
        raise _provider_error(exc) from exc
    return Response(status_code=204)


@router.get("/me")
def me(principal: Principal = Depends(require_role("viewer"))) -> dict:
    if principal.kind == "session":
        user = identity.public_session(
            principal.id, workspace_id=principal.workspace_id
        )
        if user is None:
            raise HTTPException(status_code=401, detail="Session is no longer valid")
        workspace = db.get_workspace(principal.workspace_id)
        return {
            "user": {
                **user,
                "kind": "session",
                "workspace": db.public_workspace(workspace) if workspace else None,
            }
        }
    # Scripts authenticate with an API key; there is no account row to show.
    return {
        "user": {
            "id": principal.id,
            "email": None,
            "role": principal.role,
            "display_name": None,
            "is_guest": False,
            "created_at": None,
            "last_login_at": None,
            "last_sign_in_at": None,
            "kind": "api_key",
        }
    }


# --------------------------------------------------------------------------- #
# Administration
# --------------------------------------------------------------------------- #
def _guard_update(
    actor: Principal, target: dict, *, role: str | None, is_active: bool | None
) -> None:
    if actor.kind == "session" and actor.id == target["id"]:
        if role is not None and role != "admin":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot demote your own account",
            )
        if is_active is False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot deactivate your own account",
            )
    was_admin = target.get("role") == "admin" and bool(target.get("is_active", True))
    stops_being_admin = (role is not None and role != "admin") or is_active is False
    if (
        was_admin
        and stops_being_admin
        and identity.count_active_admins(workspace_id=actor.workspace_id) <= 1
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="At least one active admin must remain",
        )


@router.get("/users")
def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str = Query(default="", max_length=200),
    include_guests: bool = Query(default=False),
    principal: Principal = Depends(require_role("admin")),
    _rate: None = Depends(rate_limit("admin")),
) -> dict:
    items, total = identity.admin_list(
        q=q,
        include_guests=include_guests,
        page=page,
        page_size=page_size,
        workspace_id=principal.workspace_id,
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "provider": identity.provider_name(),
    }


@router.post("/users", status_code=201)
def create_user(
    payload: CreateUserRequest,
    principal: Principal = Depends(require_role("admin")),
    _rate: None = Depends(rate_limit("admin")),
) -> dict:
    email = _validate_credentials(payload.email, payload.password)
    try:
        user = identity.admin_create(
            email=email,
            password=payload.password,
            role=payload.role,
            display_name=(payload.display_name or "").strip() or None,
            workspace_id=principal.workspace_id,
        )
    except identity.Conflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=exc.detail
        ) from exc
    except identity.IdentityError as exc:
        raise _provider_error(exc) from exc
    return {"user": user}


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    principal: Principal = Depends(require_role("admin")),
    _rate: None = Depends(rate_limit("admin")),
) -> dict:
    target = identity.target(user_id, workspace_id=principal.workspace_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Account not found")
    _guard_update(principal, target, role=payload.role, is_active=payload.is_active)
    try:
        updated = identity.admin_update(
            user_id,
            role=payload.role,
            is_active=payload.is_active,
            workspace_id=principal.workspace_id,
        )
    except identity.IdentityError as exc:
        raise _provider_error(exc) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Account not found")
    logger.info(
        "account updated actor=%s target=%s role=%s active=%s",
        principal.id,
        user_id,
        payload.role,
        payload.is_active,
    )
    return {"user": updated}


@router.post("/users/{user_id}/password-reset", status_code=202)
def reset_password(
    user_id: str,
    principal: Principal = Depends(require_role("admin")),
    _rate: None = Depends(rate_limit("admin")),
) -> dict:
    """Always ``202`` for an admin, so the endpoint cannot enumerate emails."""
    if identity.is_local():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Password reset requires Supabase Auth",
        )
    target = identity.target(user_id, workspace_id=principal.workspace_id)
    try:
        if target is not None:
            identity.admin_reset(user_id, workspace_id=principal.workspace_id)
    except identity.IdentityError as exc:
        # A Supabase outage is a real failure; a missing address is not.
        raise _provider_error(exc) from exc
    logger.info("password reset requested actor=%s target=%s", principal.id, user_id)
    return {"detail": "If the account exists, a reset email has been sent"}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    principal: Principal = Depends(require_role("admin")),
    _rate: None = Depends(rate_limit("admin")),
) -> Response:
    target = identity.target(user_id, workspace_id=principal.workspace_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if not target.get("is_guest"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only guest accounts can be deleted here",
        )
    if principal.kind == "session" and principal.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot delete your own account",
        )
    try:
        identity.admin_delete(user_id, workspace_id=principal.workspace_id)
    except identity.IdentityError as exc:
        raise _provider_error(exc) from exc
    logger.info("guest account deleted actor=%s target=%s", principal.id, user_id)
    return Response(status_code=204)


@router.post("/users/sync")
def sync_users(
    _principal: Principal = Depends(require_role("admin")),
    _rate: None = Depends(rate_limit("admin")),
) -> dict:
    try:
        synced = identity.sync()
    except identity.IdentityError as exc:
        raise _provider_error(exc) from exc
    return {"synced": synced, "provider": identity.provider_name()}
