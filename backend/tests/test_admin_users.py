"""User administration on the local provider (spec 005).

These tests also prove the shared guards and CSRF rules that the Supabase tests
exercise through the same routes.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app
from conftest import register_employer, register_member

ADMIN = {"X-API-Key": "dev-admin-key"}
PASSWORD = "correct-horse-9"


@pytest.fixture()
def client() -> TestClient:
    instance = TestClient(app)
    instance.cookies.clear()
    return instance


def unique_email(prefix: str = "admin") -> str:
    return f"{prefix}+{uuid.uuid4().hex[:12]}@example.com"


def csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("eais_csrf")
    return {"X-CSRF-Token": token} if token else {}


def create_account(
    client: TestClient,
    *,
    role: str = "user",
    prefix: str = "user",
    display_name: str = "Test Person",
) -> tuple[str, str]:
    email = unique_email(prefix)
    response = client.post(
        "/api/v1/auth/users",
        headers=ADMIN,
        json={
            "email": email,
            "password": PASSWORD,
            "role": role,
            "display_name": display_name,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"], email


@pytest.fixture()
def admin_client(client: TestClient) -> dict:
    user_id, email = create_account(
        client, role="admin", prefix="operator", display_name="Operator"
    )
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"client": client, "id": user_id, "email": email}


# --------------------------------------------------------------------------- #
# Listing, search, pagination
# --------------------------------------------------------------------------- #
def test_list_is_scoped_to_own_workspace_and_searches(admin_client, client):
    admin = admin_client
    real_id, real_email = create_account(client, prefix="searchable", display_name="Findable Person")

    other_admin = TestClient(app)
    other_admin.cookies.clear()
    workspace = register_employer(other_admin).json()["workspace"]
    other_member = TestClient(app)
    other_member.cookies.clear()
    other = register_member(
        other_member,
        workspace["invite_code"],
        email=unique_email("otherworkspace"),
        display_name="Other Person",
    )
    other_id = other.json()["user"]["id"]

    listed = admin["client"].get("/api/v1/auth/users", params={"page_size": 100})
    assert listed.status_code == 200, listed.text
    ids = {item["id"] for item in listed.json()["items"]}
    assert real_id in ids
    assert admin["id"] in ids
    assert other_id not in ids

    # Even the legacy include_guests flag cannot reach another workspace.
    guests = admin["client"].get(
        "/api/v1/auth/users", params={"include_guests": "true", "page_size": 100}
    )
    assert other_id not in {item["id"] for item in guests.json()["items"]}

    other_listed = other_admin.get("/api/v1/auth/users", params={"page_size": 100})
    assert other_listed.status_code == 200, other_listed.text
    other_ids = {item["id"] for item in other_listed.json()["items"]}
    assert other_id in other_ids
    assert real_id not in other_ids
    assert admin["id"] not in other_ids

    by_email = admin["client"].get(
        "/api/v1/auth/users", params={"q": real_email.split("@")[0]}
    )
    assert by_email.status_code == 200
    assert [item["id"] for item in by_email.json()["items"]] == [real_id]

    by_name = admin["client"].get(
        "/api/v1/auth/users", params={"q": "findable person"}
    )
    assert [item["id"] for item in by_name.json()["items"]] == [real_id]

    # A wildcard is data, not syntax.
    wildcard = admin["client"].get("/api/v1/auth/users", params={"q": "%"})
    assert wildcard.status_code == 200


def test_pagination_and_validation(admin_client, client):
    admin = admin_client
    for _ in range(3):
        create_account(client, prefix="paged")

    first = admin["client"].get(
        "/api/v1/auth/users", params={"page": 1, "page_size": 2}
    )
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 2
    assert body["page"] == 1 and body["page_size"] == 2
    assert body["total"] >= 4

    second = admin["client"].get(
        "/api/v1/auth/users", params={"page": 2, "page_size": 2}
    )
    assert second.json()["items"][0]["id"] != body["items"][0]["id"]

    too_big = admin["client"].get(
        "/api/v1/auth/users", params={"page_size": 500}
    )
    assert too_big.status_code == 422


# --------------------------------------------------------------------------- #
# Role and status changes
# --------------------------------------------------------------------------- #
def test_role_change_and_disable_take_effect(admin_client, client):
    admin = admin_client
    user_id, email = create_account(client, role="viewer", prefix="change")

    promoted = admin["client"].patch(
        f"/api/v1/auth/users/{user_id}",
        json={"role": "user"},
        headers=csrf(admin["client"]),
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["user"]["role"] == "user"
    assert db.get_user(user_id)["role"] == "user"

    disabled = admin["client"].patch(
        f"/api/v1/auth/users/{user_id}",
        json={"is_active": False},
        headers=csrf(admin["client"]),
    )
    assert disabled.status_code == 200
    assert disabled.json()["user"]["is_active"] is False
    assert db.get_user(user_id)["is_active"] == 0

    blocked = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert blocked.status_code == 401

    reenabled = admin["client"].patch(
        f"/api/v1/auth/users/{user_id}",
        json={"is_active": True},
        headers=csrf(admin["client"]),
    )
    assert reenabled.status_code == 200
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        ).status_code
        == 200
    )


def test_unknown_account_and_empty_patch(admin_client):
    admin = admin_client
    missing = admin["client"].patch(
        f"/api/v1/auth/users/{uuid.uuid4()}",
        json={"role": "viewer"},
        headers=csrf(admin["client"]),
    )
    assert missing.status_code == 404

    empty = admin["client"].patch(
        f"/api/v1/auth/users/{admin['id']}",
        json={},
        headers=csrf(admin["client"]),
    )
    assert empty.status_code == 422


def test_admin_cannot_demote_or_deactivate_itself(admin_client):
    admin = admin_client
    demote = admin["client"].patch(
        f"/api/v1/auth/users/{admin['id']}",
        json={"role": "user"},
        headers=csrf(admin["client"]),
    )
    assert demote.status_code == 409
    assert "demote" in demote.json()["detail"].lower()

    deactivate = admin["client"].patch(
        f"/api/v1/auth/users/{admin['id']}",
        json={"is_active": False},
        headers=csrf(admin["client"]),
    )
    assert deactivate.status_code == 409
    assert "deactivate" in deactivate.json()["detail"].lower()

    assert db.get_user(admin["id"])["role"] == "admin"
    assert db.get_user(admin["id"])["is_active"] == 1


def test_the_last_active_admin_cannot_be_removed(admin_client, client):
    admin = admin_client
    target_id, _ = create_account(client, role="admin", prefix="lastadmin")

    # Collapse the world to a single active admin using the database directly:
    # the API itself refuses to remove the last one, which is the point here.
    previous_roles: dict[str, str] = {}
    users, _total = db.list_users(include_guests=True, page=1, page_size=100)
    for user in users:
        if user["role"] == "admin" and user["id"] != target_id:
            previous_roles[user["id"]] = user["role"]
            db.update_user(user["id"], role="viewer")
    db.update_user(target_id, role="admin", is_active=1)
    try:
        assert len([u for u in db.list_users(include_guests=True, page=1, page_size=100)[0] if u["role"] == "admin" and u["is_active"]]) == 1
        blocked = admin["client"].patch(
            f"/api/v1/auth/users/{target_id}",
            json={"role": "viewer"},
            headers=ADMIN,
        )
        assert blocked.status_code == 409
        assert "at least one active admin" in blocked.json()["detail"].lower()
    finally:
        for user_id, role in previous_roles.items():
            db.update_user(user_id, role=role)
        db.update_user(admin["id"], role="admin", is_active=1)


# --------------------------------------------------------------------------- #
# Reset, delete, sync
# --------------------------------------------------------------------------- #
def test_password_reset_is_501_on_the_local_provider(admin_client, client):
    admin = admin_client
    user_id, _ = create_account(client, prefix="reset")
    response = admin["client"].post(
        f"/api/v1/auth/users/{user_id}/password-reset",
        headers=csrf(admin["client"]),
    )
    assert response.status_code == 501


def test_real_accounts_cannot_be_deleted_across_workspaces(admin_client, client):
    admin = admin_client
    real_id, _ = create_account(client, prefix="notguest")

    refused = admin["client"].delete(
        f"/api/v1/auth/users/{real_id}", headers=csrf(admin["client"])
    )
    assert refused.status_code == 409  # no guests exist; real accounts stay
    assert db.get_user(real_id) is not None

    other_admin = TestClient(app)
    other_admin.cookies.clear()
    workspace = register_employer(other_admin).json()["workspace"]
    other_member = TestClient(app)
    other_member.cookies.clear()
    other_id = register_member(
        other_member,
        workspace["invite_code"],
        email=unique_email("keepme"),
    ).json()["user"]["id"]

    cross_workspace = admin["client"].delete(
        f"/api/v1/auth/users/{other_id}", headers=csrf(admin["client"])
    )
    assert cross_workspace.status_code == 404
    assert db.get_user(other_id) is not None


def test_local_sync_is_a_no_op(admin_client):
    response = admin_client["client"].post(
        "/api/v1/auth/users/sync", headers=csrf(admin_client["client"])
    )
    assert response.status_code == 200
    assert response.json() == {"synced": 0, "provider": "local"}


# --------------------------------------------------------------------------- #
# Authorization surface
# --------------------------------------------------------------------------- #
def test_non_admin_is_forbidden(client):
    user_id, email = create_account(client, prefix="plain")
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    assert client.get("/api/v1/auth/users").status_code == 403
    assert (
        client.patch(
            f"/api/v1/auth/users/{user_id}",
            json={"role": "admin"},
            headers=csrf(client),
        ).status_code
        == 403
    )


def test_admin_cookie_routes_require_csrf_but_api_keys_do_not(admin_client, client):
    admin = admin_client
    user_id, _ = create_account(client, prefix="csrf")

    missing = admin["client"].patch(
        f"/api/v1/auth/users/{user_id}", json={"role": "user"}
    )
    assert missing.status_code == 403
    assert "csrf" in missing.json()["detail"].lower()

    allowed = admin["client"].patch(
        f"/api/v1/auth/users/{user_id}",
        json={"role": "user"},
        headers=csrf(admin["client"]),
    )
    assert allowed.status_code == 200

    # Scripts keep working: the API key is not an ambient credential.
    api_key_patch = admin["client"].patch(
        f"/api/v1/auth/users/{user_id}",
        json={"role": "viewer"},
        headers=ADMIN,
    )
    assert api_key_patch.status_code == 200


def test_health_reports_the_local_provider_without_secrets(client):
    body = client.get("/api/v1/health").json()
    auth = body["checks"]["auth"]
    assert auth["provider"] == "local"
    assert auth["admin_api"] is True
    assert auth["registration"] is True
    assert auth["invite_required"] is False
    assert auth["password_reset"] is False
    assert auth["jwt"] == "local"
    assert body["checks"]["llm_api"]["server_key_admin_only"] is True
    assert "service_role" not in str(auth).lower()
    assert settings.supabase_service_role_key == ""


def test_health_flags_an_invite_only_deployment(client):
    previous = settings.invite_code
    object.__setattr__(settings, "invite_code", "invite-123")
    try:
        auth = client.get("/api/v1/health").json()["checks"]["auth"]
    finally:
        object.__setattr__(settings, "invite_code", previous)
    assert auth["registration"] is True
    assert auth["invite_required"] is True


def test_local_mode_cannot_complete_a_password_reset(client):
    response = client.post(
        "/api/v1/auth/password-reset",
        json={"access_token": "a" * 40, "password": PASSWORD},
    )
    assert response.status_code == 501, response.text
    assert "Supabase" in response.json()["detail"]
