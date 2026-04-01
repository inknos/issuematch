"""Tests for password login, API token CRUD, bearer auth, and admin password reset."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from app.auth import ROLE_HIERARCHY
from app.crypto import generate_api_token, hash_password, verify_password
from app.models import ApiToken, User
from fastapi import HTTPException

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_admin.py)
# ---------------------------------------------------------------------------


def _admin_session(admin_data: dict) -> dict:
    return {"user_id": admin_data["user_id"], "role": "admin"}


def _contributor_session(seed_data: dict) -> dict:
    return {"user_id": seed_data["user_id"], "role": "contributor"}


def _make_require_role(session_dict: dict):  # noqa: ANN202
    def _require(_request: object, minimum: str) -> int:
        uid = session_dict["user_id"]
        user_role = session_dict["role"]
        if ROLE_HIERARCHY.get(user_role, 0) < ROLE_HIERARCHY[minimum]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return uid

    return _require


def _mock_role(session_dict: dict) -> tuple:
    return (
        patch("app.routes.current_user_id", return_value=session_dict["user_id"]),
        patch("app.routes.current_user_role", return_value=session_dict["role"]),
        patch("app.routes.require_role", side_effect=_make_require_role(session_dict)),
    )


# ---------------------------------------------------------------------------
# Password login
# ---------------------------------------------------------------------------


async def test_password_login_success(client: AsyncClient, session: AsyncSession) -> None:
    user = User(
        username="pwuser",
        avatar_url=None,
        password_hash=hash_password("correct-password"),
        role="contributor",
    )
    session.add(user)
    await session.commit()

    resp = await client.post(
        "/auth/login",
        data={"username": "pwuser", "password": "correct-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/vote" in resp.headers["location"]


async def test_password_login_wrong_password(client: AsyncClient, session: AsyncSession) -> None:
    user = User(
        username="pwuser2",
        avatar_url=None,
        password_hash=hash_password("right-pass"),
        role="contributor",
    )
    session.add(user)
    await session.commit()

    resp = await client.post(
        "/auth/login",
        data={"username": "pwuser2", "password": "wrong-pass"},
    )
    assert resp.status_code == 401


@pytest.mark.usefixtures("seed_data")
async def test_password_login_no_password_set(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": "anything"},
    )
    assert resp.status_code == 401


async def test_password_login_unknown_user(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        data={"username": "ghost", "password": "anything"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Change own password
# ---------------------------------------------------------------------------


async def test_change_own_password(client: AsyncClient, session: AsyncSession) -> None:
    user = User(
        username="changer",
        avatar_url=None,
        password_hash=hash_password("old-pass"),
        role="contributor",
    )
    session.add(user)
    await session.commit()

    sd = {"user_id": user.id, "role": "contributor"}
    p1, p2, p3 = _mock_role(sd)
    with p1, p2, p3:
        resp = await client.put(
            "/api/user/password",
            json={"current_password": "old-pass", "new_password": "new-pass-123"},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    await session.refresh(user)
    assert verify_password("new-pass-123", user.password_hash)


async def test_change_password_wrong_current(client: AsyncClient, session: AsyncSession) -> None:
    user = User(
        username="changer2",
        avatar_url=None,
        password_hash=hash_password("real-pass"),
        role="contributor",
    )
    session.add(user)
    await session.commit()

    sd = {"user_id": user.id, "role": "contributor"}
    p1, p2, p3 = _mock_role(sd)
    with p1, p2, p3:
        resp = await client.put(
            "/api/user/password",
            json={"current_password": "wrong", "new_password": "new123456"},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Admin password reset
# ---------------------------------------------------------------------------


async def test_admin_reset_password(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
) -> None:
    target_uid = seed_data["user_id"]
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.put(
            f"/api/admin/users/{target_uid}/password",
            json={"new_password": "admin-set-pw"},
        )
    assert resp.status_code == 200

    resp2 = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": "admin-set-pw"},
        follow_redirects=False,
    )
    assert resp2.status_code == 303


async def test_admin_reset_password_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    p1, p2, p3 = _mock_role(_contributor_session(seed_data))
    with p1, p2, p3:
        resp = await client.put(
            f"/api/admin/users/{seed_data['user_id']}/password",
            json={"new_password": "nope"},
        )
    assert resp.status_code == 403


async def test_admin_reset_password_user_not_found(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    p1, p2, p3 = _mock_role(_admin_session(admin_user))
    with p1, p2, p3:
        resp = await client.put(
            "/api/admin/users/99999/password",
            json={"new_password": "doesntmatter"},
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API token CRUD
# ---------------------------------------------------------------------------


async def test_create_and_list_tokens(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    sd = _contributor_session(seed_data)
    p1, p2, p3 = _mock_role(sd)

    with p1, p2, p3:
        resp = await client.post(
            "/api/tokens",
            json={"name": "my-bot", "role": "contributor"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert "raw_token" in data
    assert data["raw_token"].startswith("im_")
    assert data["name"] == "my-bot"
    assert data["role"] == "contributor"
    assert data["is_active"] is True

    with p1, p2, p3:
        list_resp = await client.get("/api/tokens/json")
    assert list_resp.status_code == 200
    tokens = list_resp.json()
    assert len(tokens) == 1
    assert tokens[0]["name"] == "my-bot"
    assert "raw_token" not in tokens[0]


async def test_create_token_role_exceeds_user_forbidden(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    sd = _contributor_session(seed_data)
    p1, p2, p3 = _mock_role(sd)
    with p1, p2, p3:
        resp = await client.post(
            "/api/tokens",
            json={"name": "escalation", "role": "admin"},
        )
    assert resp.status_code == 403


async def test_revoke_token(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    sd = _contributor_session(seed_data)
    p1, p2, p3 = _mock_role(sd)

    with p1, p2, p3:
        create_resp = await client.post(
            "/api/tokens",
            json={"name": "temp", "role": "contributor"},
        )
    token_id = create_resp.json()["id"]

    with p1, p2, p3:
        del_resp = await client.delete(f"/api/tokens/{token_id}")
    assert del_resp.status_code == 204

    with p1, p2, p3:
        list_resp = await client.get("/api/tokens/json")
    tokens = list_resp.json()
    assert tokens[0]["is_active"] is False


async def test_revoke_nonexistent_token(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    sd = _contributor_session(seed_data)
    p1, p2, p3 = _mock_role(sd)
    with p1, p2, p3:
        resp = await client.delete("/api/tokens/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Bearer token auth
# ---------------------------------------------------------------------------


async def test_bearer_token_authenticates_api(
    client: AsyncClient,
    session: AsyncSession,
    seed_data: dict,
) -> None:
    raw, token_hash, prefix = generate_api_token()
    api_token = ApiToken(
        user_id=seed_data["user_id"],
        token_hash=token_hash,
        token_prefix=prefix,
        name="bearer-test",
        role="contributor",
    )
    session.add(api_token)
    await session.commit()

    resp = await client.get(
        "/api/votes/json",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert resp.status_code == 200


async def test_bearer_token_invalid_rejected(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/admin/users/json",
        headers={"Authorization": "Bearer im_totallyinvalid"},
    )
    assert resp.status_code == 401


async def test_bearer_token_revoked_rejected(
    client: AsyncClient,
    session: AsyncSession,
    seed_data: dict,
) -> None:
    raw, token_hash, prefix = generate_api_token()
    api_token = ApiToken(
        user_id=seed_data["user_id"],
        token_hash=token_hash,
        token_prefix=prefix,
        name="revoked",
        role="contributor",
        is_active=False,
    )
    session.add(api_token)
    await session.commit()

    resp = await client.get(
        "/api/admin/users/json",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert resp.status_code == 401


async def test_bearer_token_role_enforced(
    client: AsyncClient,
    session: AsyncSession,
    seed_data: dict,
) -> None:
    raw, token_hash, prefix = generate_api_token()
    api_token = ApiToken(
        user_id=seed_data["user_id"],
        token_hash=token_hash,
        token_prefix=prefix,
        name="contrib-token",
        role="contributor",
    )
    session.add(api_token)
    await session.commit()

    resp = await client.get(
        "/api/admin/users/json",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# User page HTML
# ---------------------------------------------------------------------------


async def test_user_page_renders(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    sd = _contributor_session(seed_data)
    p1, p2, p3 = _mock_role(sd)
    with p1, p2, p3:
        resp = await client.get("/user")
    assert resp.status_code == 200
    assert "Account" in resp.text
    assert "API Tokens" in resp.text


async def test_user_page_unauthorized(client: AsyncClient) -> None:
    resp = await client.get("/user")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


async def test_logout_clears_session(client: AsyncClient) -> None:
    resp = await client.get("/logout", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"
