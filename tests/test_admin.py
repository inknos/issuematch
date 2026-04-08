"""Tests for admin/maintainer role management, token storage, issue fetch, and user CRUD."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from app.crypto import encrypt_token
from app.models import User

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.conftest import _AuthOverrider

pytestmark = pytest.mark.asyncio


# -- GET /api/admin/users/json (maintainer+) --------------------------------


@pytest.mark.usefixtures("seed_data")
async def test_list_users_admin(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.get("/api/admin/users/json")
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) >= 2
    assert all("role" in u for u in users)


@pytest.mark.usefixtures("seed_data")
async def test_list_users_maintainer(
    client: AsyncClient,
    maintainer_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(maintainer_user["user_id"], "maintainer"):
        resp = await client.get("/api/admin/users/json")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


async def test_list_users_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.get("/api/admin/users/json")
    assert resp.status_code == 403


async def test_list_users_anonymous_unauthorized(client: AsyncClient) -> None:
    resp = await client.get("/api/admin/users/json")
    assert resp.status_code == 401


# -- PATCH /api/admin/users/{user_id}/role (admin only) ----------------------


async def test_update_role_admin(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    target_uid = seed_data["user_id"]
    with auth(admin_user["user_id"], "admin"):
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
    auth: _AuthOverrider,
) -> None:
    target_uid = seed_data["user_id"]
    with auth(admin_user["user_id"], "admin"):
        await client.patch(
            f"/api/admin/users/{target_uid}/role",
            json={"role": "admin"},
        )
        resp = await client.get("/api/activity/json", params={"user_id": admin_user["user_id"]})
    data = resp.json()
    role_changes = [e for e in data["items"] if e["action"]["type"] == "role_change"]
    assert len(role_changes) == 1
    assert role_changes[0]["action"]["target_user_id"] == target_uid
    assert role_changes[0]["action"]["new_role"] == "admin"


async def test_update_role_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.patch(
            f"/api/admin/users/{seed_data['user_id']}/role",
            json={"role": "admin"},
        )
    assert resp.status_code == 403


async def test_update_role_maintainer_forbidden(
    client: AsyncClient,
    seed_data: dict,
    maintainer_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(maintainer_user["user_id"], "maintainer"):
        resp = await client.patch(
            f"/api/admin/users/{seed_data['user_id']}/role",
            json={"role": "admin"},
        )
    assert resp.status_code == 403


async def test_update_role_user_not_found(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.patch(
            "/api/admin/users/99999/role",
            json={"role": "maintainer"},
        )
    assert resp.status_code == 404


async def test_update_role_invalid_value(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.patch(
            f"/api/admin/users/{seed_data['user_id']}/role",
            json={"role": "superadmin"},
        )
    assert resp.status_code == 422


# -- GET /admin/users (HTML, admin only) ------------------------------------


@pytest.mark.usefixtures("seed_data")
async def test_admin_page_renders_for_admin(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
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
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.get("/admin/users")
    assert resp.status_code == 403


async def test_admin_page_unauthorized_anonymous(client: AsyncClient) -> None:
    resp = await client.get("/admin/users")
    assert resp.status_code == 401


# -- Default role on new user -----------------------------------------------


async def test_new_user_defaults_to_contributor(session: AsyncSession) -> None:
    user = User(username="newbie", avatar_url=None)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    assert user.role == "contributor"


# -- GET /api/admin/github/token/json (token status, admin only) -------------


async def test_admin_status_no_token(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.get("/api/admin/github/token/json")
    assert resp.status_code == 200
    assert resp.json() == {"has_token": False}


async def test_admin_status_with_token(
    client: AsyncClient,
    admin_user: dict,
    session: AsyncSession,
    auth: _AuthOverrider,
) -> None:
    from sqlalchemy import select as sa_select  # noqa: PLC0415

    result = await session.execute(sa_select(User).where(User.id == admin_user["user_id"]))
    user = result.scalar_one()
    user.github_token_encrypted = encrypt_token("ghp_test123")
    await session.commit()

    with auth(admin_user["user_id"], "admin"):
        resp = await client.get("/api/admin/github/token/json")
    assert resp.status_code == 200
    assert resp.json() == {"has_token": True}


async def test_admin_status_anonymous(client: AsyncClient) -> None:
    resp = await client.get("/api/admin/github/token/json")
    assert resp.status_code == 401


async def test_admin_status_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.get("/api/admin/github/token/json")
    assert resp.status_code == 403


# -- PUT /api/admin/github/token (set token, admin only) --------------------


async def test_put_admin_sets_token(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.put("/api/admin/github/token", json={"token": "ghp_newtoken123"})
    assert resp.status_code == 200
    assert resp.json() == {"has_token": True}


async def test_put_admin_never_returns_plaintext(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    token = "ghp_supersecret999"
    with auth(admin_user["user_id"], "admin"):
        resp = await client.put("/api/admin/github/token", json={"token": token})
    assert token not in resp.text

    with auth(admin_user["user_id"], "admin"):
        status_resp = await client.get("/api/admin/github/token/json")
    assert token not in status_resp.text


async def test_put_admin_creates_audit_log(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        await client.put("/api/admin/github/token", json={"token": "ghp_audit"})
        resp = await client.get("/api/activity/json", params={"user_id": admin_user["user_id"]})
    data = resp.json()
    token_updates = [e for e in data["items"] if e["action"]["type"] == "token_update"]
    assert len(token_updates) == 1


async def test_put_admin_anonymous(client: AsyncClient) -> None:
    resp = await client.put("/api/admin/github/token", json={"token": "ghp_x"})
    assert resp.status_code == 401


async def test_put_admin_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.put("/api/admin/github/token", json={"token": "ghp_x"})
    assert resp.status_code == 403


# -- POST /api/admin/github/fetch (maintainer+) -----------------------------


async def test_fetch_no_token_returns_400(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.post(
            "/api/admin/github/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues"},
        )
    assert resp.status_code == 400
    assert "No GitHub token" in resp.json()["error"]["message"]


async def test_fetch_with_mocked_github(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        await client.put("/api/admin/github/token", json={"token": "ghp_mock"})

    mock_fetch = AsyncMock(return_value=(5, 0))
    with auth(admin_user["user_id"], "admin"), patch("app.routes.fetch_and_store", mock_fetch):
        resp = await client.post(
            "/api/admin/github/fetch",
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


async def test_fetch_maintainer_can_fetch(
    client: AsyncClient,
    admin_user: dict,
    maintainer_user: dict,
    auth: _AuthOverrider,
) -> None:
    """Maintainers can trigger a fetch using any stored GitHub token."""
    with auth(admin_user["user_id"], "admin"):
        await client.put("/api/admin/github/token", json={"token": "ghp_mock"})

    mock_fetch = AsyncMock(return_value=(3, 0))
    with (
        auth(maintainer_user["user_id"], "maintainer"),
        patch(
            "app.routes.fetch_and_store",
            mock_fetch,
        ),
    ):
        resp = await client.post(
            "/api/admin/github/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues"},
        )
    assert resp.status_code == 200
    assert resp.json()["upserted"] == 3


async def test_fetch_anonymous(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/admin/github/fetch",
        json={"org": "acme", "repo": "widgets", "type": "issues"},
    )
    assert resp.status_code == 401


async def test_fetch_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.post(
            "/api/admin/github/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues"},
        )
    assert resp.status_code == 403


async def test_fetch_mode_forwarded_replace(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        await client.put("/api/admin/github/token", json={"token": "ghp_mock"})

    mock_fetch = AsyncMock(return_value=(3, 2))
    with auth(admin_user["user_id"], "admin"), patch("app.routes.fetch_and_store", mock_fetch):
        resp = await client.post(
            "/api/admin/github/fetch",
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
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        await client.put("/api/admin/github/token", json={"token": "ghp_mock"})

    mock_fetch = AsyncMock(return_value=(0, 4))
    with auth(admin_user["user_id"], "admin"), patch("app.routes.fetch_and_store", mock_fetch):
        resp = await client.post(
            "/api/admin/github/fetch",
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
    auth: _AuthOverrider,
) -> None:
    """When mode is omitted from the request body, it defaults to merge."""
    with auth(admin_user["user_id"], "admin"):
        await client.put("/api/admin/github/token", json={"token": "ghp_mock"})

    mock_fetch = AsyncMock(return_value=(1, 0))
    with auth(admin_user["user_id"], "admin"), patch("app.routes.fetch_and_store", mock_fetch):
        resp = await client.post(
            "/api/admin/github/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues"},
        )
    assert resp.status_code == 200

    call_kwargs = mock_fetch.call_args.kwargs
    assert call_kwargs["mode"] == "merge"


async def test_fetch_invalid_mode_returns_422(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.post(
            "/api/admin/github/fetch",
            json={"org": "acme", "repo": "widgets", "type": "issues", "mode": "nuke"},
        )
    assert resp.status_code == 422


# -- POST /api/admin/users (create user, admin only) -----------------------


async def test_create_user_as_admin(
    client: AsyncClient,
    admin_user: dict,
    session: AsyncSession,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.post(
            "/api/admin/users",
            json={"username": "newuser", "role": "maintainer", "password": "strong-pw-123"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "newuser"
    assert data["role"] == "maintainer"

    from sqlalchemy import select  # noqa: PLC0415

    row = (await session.execute(select(User).where(User.username == "newuser"))).scalar_one()
    assert row.password_hash is not None


@pytest.mark.usefixtures("seed_data")
async def test_create_user_duplicate_username(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.post(
            "/api/admin/users",
            json={"username": "testuser", "password": "strong-pw-123"},
        )
    assert resp.status_code == 409


async def test_create_user_short_password(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.post(
            "/api/admin/users",
            json={"username": "shortpw", "password": "abc"},
        )
    assert resp.status_code == 400


async def test_create_user_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.post(
            "/api/admin/users",
            json={"username": "nope", "password": "strong-pw-123"},
        )
    assert resp.status_code == 403


# -- DELETE /api/admin/users/{user_id} (admin only) -------------------------


async def test_delete_user_as_admin(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    session: AsyncSession,
    auth: _AuthOverrider,
) -> None:
    target_uid = seed_data["user_id"]
    with auth(admin_user["user_id"], "admin"):
        resp = await client.delete(f"/api/admin/users/{target_uid}")
    assert resp.status_code == 204

    from sqlalchemy import select  # noqa: PLC0415

    row = (await session.execute(select(User).where(User.id == target_uid))).scalar_one_or_none()
    assert row is None


async def test_delete_user_self_forbidden(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.delete(f"/api/admin/users/{admin_user['user_id']}")
    assert resp.status_code == 403


async def test_delete_user_not_found(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.delete("/api/admin/users/99999")
    assert resp.status_code == 404


async def test_delete_user_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.delete(f"/api/admin/users/{seed_data['user_id']}")
    assert resp.status_code == 403


async def test_delete_user_anonymous(client: AsyncClient) -> None:
    resp = await client.delete("/api/admin/users/1")
    assert resp.status_code == 401
