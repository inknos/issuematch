from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from app.auth import _signer
from httpx import AsyncClient
from itsdangerous import SignatureExpired


async def test_login_redirects_to_github(client: AsyncClient) -> None:
    resp = await client.get("/login", follow_redirects=False)
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert "github.com/login/oauth/authorize" in location

    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    assert "client_id" in params
    assert "state" in params
    assert params["scope"] == ["read:user"]


async def test_callback_bad_state_returns_403(client: AsyncClient) -> None:
    resp = await client.get("/auth/callback", params={"code": "abc", "state": "garbage"})
    assert resp.status_code == 403


async def test_callback_expired_state_returns_403(client: AsyncClient) -> None:
    state = _signer.dumps({"v": 1})

    with patch.object(_signer, "loads", side_effect=SignatureExpired("expired")):
        resp = await client.get("/auth/callback", params={"code": "abc", "state": state})

    assert resp.status_code == 403
    assert "expired" in resp.json()["detail"].lower()


@pytest.mark.usefixtures("seed_data")
async def test_callback_happy_path(client: AsyncClient) -> None:
    state = _signer.dumps({"v": 1})

    mock_token_resp = Mock(spec=httpx.Response)
    mock_token_resp.json.return_value = {"access_token": "gho_test_token"}
    mock_token_resp.raise_for_status = Mock()

    mock_user_resp = Mock(spec=httpx.Response)
    mock_user_resp.json.return_value = {
        "id": 12345,
        "login": "testuser",
        "avatar_url": "https://example.com/avatar.png",
    }
    mock_user_resp.raise_for_status = Mock()

    async def mock_post(*_args: object, **_kwargs: object) -> httpx.Response:
        return mock_token_resp

    async def mock_get(*_args: object, **_kwargs: object) -> httpx.Response:
        return mock_user_resp

    with patch("app.auth.AsyncClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.post = mock_post
        mock_instance.get = mock_get
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        resp = await client.get(
            "/auth/callback",
            params={"code": "test_code", "state": state},
            follow_redirects=False,
        )

    assert resp.status_code == 303
    assert "/vote" in resp.headers["location"]


async def test_callback_creates_new_user(client: AsyncClient) -> None:
    state = _signer.dumps({"v": 1})

    mock_token_resp = Mock(spec=httpx.Response)
    mock_token_resp.json.return_value = {"access_token": "gho_new_token"}
    mock_token_resp.raise_for_status = Mock()

    mock_user_resp = Mock(spec=httpx.Response)
    mock_user_resp.json.return_value = {
        "id": 99999,
        "login": "newuser",
        "avatar_url": None,
    }
    mock_user_resp.raise_for_status = Mock()

    async def mock_post(*_args: object, **_kwargs: object) -> httpx.Response:
        return mock_token_resp

    async def mock_get(*_args: object, **_kwargs: object) -> httpx.Response:
        return mock_user_resp

    with patch("app.auth.AsyncClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.post = mock_post
        mock_instance.get = mock_get
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        resp = await client.get(
            "/auth/callback",
            params={"code": "code123", "state": state},
            follow_redirects=False,
        )

    assert resp.status_code == 303


async def test_logout_clears_session(client: AsyncClient) -> None:
    resp = await client.get("/logout", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"
