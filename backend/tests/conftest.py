from __future__ import annotations

import os
import tempfile
import uuid
from typing import Any

from fastapi.testclient import TestClient

# Configure an isolated, offline-first environment before importing the app.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="eais-test-")
os.environ["EMBEDDING_BACKEND"] = "hashing"
os.environ["LLM_API_KEY"] = ""
os.environ.pop("QDRANT_URL", None)
os.environ.setdefault("ADMIN_API_KEY", "dev-admin-key")
os.environ.setdefault("USER_API_KEY", "dev-user-key")
os.environ.setdefault("VIEWER_API_KEY", "dev-viewer-key")
# Keep the suite deterministic: the limiter has its own unit/HTTP tests that
# install a low-limit bucket explicitly.
os.environ.setdefault("RATE_LIMIT_SEARCH_PER_MINUTE", "100000")
os.environ.setdefault("RATE_LIMIT_CHAT_PER_MINUTE", "100000")
os.environ.setdefault("RATE_LIMIT_UPLOAD_PER_MINUTE", "100000")
# Accounts: keep the suite independent of a developer's .env. The admin
# bootstrap test overrides these explicitly; every other account is registered
# through the workspace-invite flow below.
os.environ["RATE_LIMIT_AUTH_PER_MINUTE"] = "100000"
os.environ["RATE_LIMIT_ADMIN_PER_MINUTE"] = "100000"
os.environ["DEMO_LOGIN_ENABLED"] = "true"
os.environ["INVITE_CODE"] = ""
os.environ["ADMIN_EMAIL"] = ""
os.environ["ADMIN_PASSWORD"] = ""
os.environ["SESSION_SECURE"] = "false"

PASSWORD = "correct-horse-9"


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}+{uuid.uuid4().hex[:12]}@example.com"


def register_employer(
    client: TestClient,
    *,
    email: str | None = None,
    password: str = PASSWORD,
    workspace_name: str = "Test Workspace",
    display_name: str = "Workspace Admin",
) -> Any:
    """Create a workspace and sign in its admin; return the HTTP response."""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email or unique_email("employer"),
            "password": password,
            "kind": "employer",
            "workspace_name": workspace_name,
            "display_name": display_name,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["role"] == "admin"
    assert response.json()["workspace"]["invite_code"]
    return response


def register_member(
    client: TestClient,
    invite_code: str,
    *,
    email: str | None = None,
    password: str = PASSWORD,
    display_name: str = "Test Person",
    expected_status: int = 200,
) -> Any:
    """Join an existing workspace with its invite code and sign in."""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email or unique_email("member"),
            "password": password,
            "kind": "member",
            "invite_code": invite_code,
            "display_name": display_name,
        },
    )
    assert response.status_code == expected_status, response.text
    if expected_status == 200:
        assert response.json()["user"]["role"] == "user"
        assert response.json()["workspace"]["invite_code"] == invite_code
    return response
