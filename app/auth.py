from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from httpx import AsyncClient
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select

from app.config import BASE_URL, GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, SESSION_SECRET
from app.database import SessionDep
from app.models import User

router = APIRouter()

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

REDIRECT_URI = f"{BASE_URL}/auth/callback"

_signer = URLSafeTimedSerializer(SESSION_SECRET)
STATE_MAX_AGE = 300  # 5 minutes


@router.get("/login")
async def login() -> RedirectResponse:
    state = _signer.dumps({"v": 1})

    params = urlencode(
        {
            "client_id": GITHUB_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": "read:user",
            "state": state,
        }
    )
    return RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{params}")


@router.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: str,
    state: str,
    session: SessionDep,
) -> RedirectResponse:
    try:
        _signer.loads(state, max_age=STATE_MAX_AGE)
    except SignatureExpired:
        raise HTTPException(
            status_code=403, detail="OAuth state expired — please try logging in again"
        ) from None
    except BadSignature:
        raise HTTPException(status_code=403, detail="Invalid OAuth state — possible CSRF") from None

    async with AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        user_resp = await client.get(
            GITHUB_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_resp.raise_for_status()
        gh_user = user_resp.json()

    result = await session.execute(select(User).where(User.github_id == gh_user["id"]))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            github_id=gh_user["id"],
            username=gh_user["login"],
            avatar_url=gh_user.get("avatar_url"),
            access_token=access_token,
        )
        session.add(user)
    else:
        user.username = gh_user["login"]
        user.avatar_url = gh_user.get("avatar_url")
        user.access_token = access_token

    await session.commit()
    await session.refresh(user)

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["avatar_url"] = user.avatar_url

    return RedirectResponse(url="/vote", status_code=303)


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login")


def current_user_id(request: Request) -> int | None:
    """Return the logged-in user_id from the session, or None."""
    return request.session.get("user_id")
