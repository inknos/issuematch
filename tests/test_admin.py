"""Tests for admin role management, token storage, and issue fetch (API + HTML)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from app.auth import ROLE_HIERARCHY
from app.crypto import encrypt_token
from app.models import User
from fastapi import HTTPException

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _admin_session(admin_data: dict) -> dict:
    return {"user_id": admin_data["user_id"], "role": "admin"}


def _contributor_session(seed_data: dict) -> dict:
    return {"user_id": seed_data["user_id"], "role": "contributor"}


def _make_require_role(session_dict: dict):  # noqa: ANN202
    """Build a fake ``require_role`` that uses *session_dict* instead of the real session."""

    def _require(_request: object, minimum: str) -> int:
        uid = session_dict["user_id"]
        user_role = session_dict["role"]
        if ROLE_HIERARCHY.get(user_role, 0) < ROLE_HIERARCHY[minimum]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return uid

    return _require


def _mock_role(session_dict: dict) -> tuple:
    """Return context-manager patches for current_user_id, current_user_role, and require_role."""
    return (
        patch("app.routes.current_user_id", return_value=session_dict["user_id"]),
        patch("app.auth.current_user_role", return_value=session_dict["role"]),
        patch("app.routes.require_role", side_effect=_make_require_role(session_dict)),
    )


# -- GET /api/admin/users ---------------------------------------------------


@pytest.mark.usefixtures("seed_data")
async def test_list_users_admin(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.get("/api/admin/users")
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) >= 2
    assert all("role" in u for u in users)


async def test_list_users_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    p1, p2, p3 = _mock_role(_contributor_session(seed_data))
    with p1, p2, p3:
        resp = await client.get("/api/admin/users")
    assert resp.status_code == 403


async def test_list_users_anonymous_unauthorized(client: AsyncClient) -> None:
    resp = await client.get("/api/admin/users")
    assert resp.status_code == 401


# -- PATCH /api/admin/users/{user_id}/role -----------------------------------


async def test_update_role_admin(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
) -> None:
    target_uid = seed_data["user_id"]
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.patch(
            f"/api/admin/users/{target_uid}/role",
            json={"role": "maintainer"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "maintainer"
    assert data["id"] == target_uid


async def test_update_role_creates_audit_log(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
) -> None:
    target_uid = seed_data["user_id"]
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        await client.patch(
            f"/api/admin/users/{target_uid}/role",
            json={"role": "admin"},
        )

    resp = await client.get("/api/activity", params={"user_id": admin_user["user_id"]})
    data = resp.json()
    role_changes = [e for e in data["items"] if e["action"]["type"] == "role_change"]
    assert len(role_changes) == 1
    assert role_changes[0]["action"]["target_user_id"] == target_uid
    assert role_changes[0]["action"]["new_role"] == "admin"


async def test_update_role_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    p1, p2, p3 = _mock_role(_contributor_session(seed_data))
    with p1, p2, p3:
        resp = await client.patch(
            f"/api/admin/users/{seed_data['user_id']}/role",
            json={"role": "admin"},
        )
    assert resp.status_code == 403


async def test_update_role_user_not_found(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.patch(
            "/api/admin/users/99999/role",
            json={"role": "maintainer"},
        )
    assert resp.status_code == 404


async def test_update_role_invalid_value(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.patch(
            f"/api/admin/users/{seed_data['user_id']}/role",
            json={"role": "superadmin"},
        )
    assert resp.status_code == 422


# -- GET /admin/users  (HTML) -----------------------------------------------


@pytest.mark.usefixtures("seed_data")
async def test_admin_page_renders_for_admin(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.get("/admin/users")
    assert resp.status_code == 200
    assert "User Management" in resp.text
    assert "testuser" in resp.text
    assert "adminuser" in resp.text
    assert "GitHub API Token" in resp.text
    assert "token-input" in resp.text
    assert "Fetch from GitHub" in resp.text
    assert "fetch-org" in resp.text
    assert "No token set" in resp.text


async def test_admin_page_forbidden_for_contributor(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    p1, p2, p3 = _mock_role(_contributor_session(seed_data))
    with p1, p2, p3:
        resp = await client.get("/admin/users")
    assert resp.status_code == 403


async def test_admin_page_unauthorized_anonymous(client: AsyncClient) -> None:
    resp = await client.get("/admin/users")
    assert resp.status_code == 401


# -- Default role on new user -----------------------------------------------


async def test_new_user_defaults_to_contributor(session: AsyncSession) -> None:
    user = User(github_id=11111, username="newbie", avatar_url=None, access_token=None)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    assert user.role == "contributor"


# -- GET /api/admin  (token status) -----------------------------------------


async def test_admin_status_no_token(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.get("/api/admin")
    assert resp.status_code == 200
    assert resp.json() == {"has_token": False}


async def test_admin_status_with_token(
    client: AsyncClient,
    admin_user: dict,
    session: AsyncSession,
) -> None:
    from sqlalchemy import select as sa_select  # noqa: PLC0415

    result = await session.execute(sa_select(User).where(User.id == admin_user["user_id"]))
    user = result.scalar_one()
    user.github_token_encrypted = encrypt_token("ghp_test123")
    await session.commit()

    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.get("/api/admin")
    assert resp.status_code == 200
    assert resp.json() == {"has_token": True}


async def test_admin_status_anonymous(client: AsyncClient) -> None:
    resp = await client.get("/api/admin")
    assert resp.status_code == 401


async def test_admin_status_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    p1, p2, p3 = _mock_role(_contributor_session(seed_data))
    with p1, p2, p3:
        resp = await client.get("/api/admin")
    assert resp.status_code == 403


# -- PUT /api/admin  (set token) --------------------------------------------


async def test_put_admin_sets_token(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.put("/api/admin", json={"token": "ghp_newtoken123"})
    assert resp.status_code == 200
    assert resp.json() == {"has_token": True}


async def test_put_admin_never_returns_plaintext(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    token = "ghp_supersecret999"
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.put("/api/admin", json={"token": token})
    assert token not in resp.text

    with p1, p2, p3:
        status_resp = await client.get("/api/admin")
    assert token not in status_resp.text


async def test_put_admin_creates_audit_log(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        await client.put("/api/admin", json={"token": "ghp_audit"})

    resp = await client.get("/api/activity", params={"user_id": admin_user["user_id"]})
    data = resp.json()
    token_updates = [e for e in data["items"] if e["action"]["type"] == "token_update"]
    assert len(token_updates) == 1


async def test_put_admin_anonymous(client: AsyncClient) -> None:
    resp = await client.put("/api/admin", json={"token": "ghp_x"})
    assert resp.status_code == 401


async def test_put_admin_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    p1, p2, p3 = _mock_role(_contributor_session(seed_data))
    with p1, p2, p3:
        resp = await client.put("/api/admin", json={"token": "ghp_x"})
    assert resp.status_code == 403


# -- POST /api/admin/fetch --------------------------------------------------


async def test_fetch_no_token_returns_400(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.post(
            "/api/admin/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues"},
        )
    assert resp.status_code == 400
    assert "No GitHub token" in resp.json()["detail"]


async def test_fetch_with_mocked_github(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))

    with p1, p2, p3:
        await client.put("/api/admin", json={"token": "ghp_mock"})

    mock_fetch = AsyncMock(return_value=(5, 0))
    with p1, p2, p3, patch("app.routes.fetch_and_store", mock_fetch):
        resp = await client.post(
            "/api/admin/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues", "labels": "bug"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["upserted"] == 5
    assert data["removed"] == 0
    assert data["org"] == "acme"
    assert data["repo"] == "widgets"

    mock_fetch.assert_awaited_once()
    call_kwargs = mock_fetch.call_args.kwargs
    assert call_kwargs["org"] == "acme"
    assert call_kwargs["repo"] == "widgets"
    assert call_kwargs["item_type"] == "issues"
    assert call_kwargs["labels"] == "bug"
    assert call_kwargs["mode"] == "merge"


async def test_fetch_anonymous(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/admin/fetch",
        json={"org": "acme", "repo": "widgets", "type": "issues"},
    )
    assert resp.status_code == 401


async def test_fetch_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    p1, p2, p3 = _mock_role(_contributor_session(seed_data))
    with p1, p2, p3:
        resp = await client.post(
            "/api/admin/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues"},
        )
    assert resp.status_code == 403


async def test_fetch_mode_forwarded_replace(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))

    with p1, p2, p3:
        await client.put("/api/admin", json={"token": "ghp_mock"})

    mock_fetch = AsyncMock(return_value=(3, 2))
    with p1, p2, p3, patch("app.routes.fetch_and_store", mock_fetch):
        resp = await client.post(
            "/api/admin/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues", "mode": "replace"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["upserted"] == 3
    assert data["removed"] == 2

    call_kwargs = mock_fetch.call_args.kwargs
    assert call_kwargs["mode"] == "replace"


async def test_fetch_mode_forwarded_subtract(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))

    with p1, p2, p3:
        await client.put("/api/admin", json={"token": "ghp_mock"})

    mock_fetch = AsyncMock(return_value=(0, 4))
    with p1, p2, p3, patch("app.routes.fetch_and_store", mock_fetch):
        resp = await client.post(
            "/api/admin/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues", "mode": "subtract"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["upserted"] == 0
    assert data["removed"] == 4

    call_kwargs = mock_fetch.call_args.kwargs
    assert call_kwargs["mode"] == "subtract"


async def test_fetch_default_mode_is_merge(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    """When mode is omitted from the request body, it defaults to merge."""
    p1, p2, p3 = _mock_role(_admin_session(admin_user))

    with p1, p2, p3:
        await client.put("/api/admin", json={"token": "ghp_mock"})

    mock_fetch = AsyncMock(return_value=(1, 0))
    with p1, p2, p3, patch("app.routes.fetch_and_store", mock_fetch):
        resp = await client.post(
            "/api/admin/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues"},
        )
    assert resp.status_code == 200

    call_kwargs = mock_fetch.call_args.kwargs
    assert call_kwargs["mode"] == "merge"


async def test_fetch_invalid_mode_returns_422(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.post(
            "/api/admin/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues", "mode": "nuke"},
        )
    assert resp.status_code == 422
