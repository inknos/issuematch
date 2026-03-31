"""Password login/logout routes and session helpers."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import SESSION_SECRET  # noqa: F401 — re-exported for tests
from app.crypto import DUMMY_HASH, verify_password
from app.database import SessionDep  # noqa: TC001 — runtime-evaluated by FastAPI DI
from app.models import AuditLog, Role, User

router = APIRouter()


@router.post("/auth/login")
async def password_login(
    request: Request,
    session: SessionDep,
) -> RedirectResponse:
    """Authenticate with username + password and create a session."""
    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))

    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None:
        verify_password(password, DUMMY_HASH)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    session.add(AuditLog(user_id=user.id, action={"type": "login", "method": "password"}))
    await session.commit()
    await session.refresh(user)

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["avatar_url"] = user.avatar_url
    request.session["role"] = user.role

    return RedirectResponse(url="/vote", status_code=303)


@router.get("/logout")
async def logout(request: Request, session: SessionDep) -> RedirectResponse:
    """Clear the session and redirect to the login page."""
    uid = current_user_id(request)
    if uid is not None:
        session.add(AuditLog(user_id=uid, action={"type": "logout"}))
        await session.commit()
    request.session.clear()
    return RedirectResponse(url="/")


def current_user_id(request: Request) -> int | None:
    """Return the authenticated user_id (Bearer token first, then session)."""
    bearer_uid = getattr(request.state, "_bearer_user_id", None)
    if bearer_uid is not None:
        return bearer_uid
    return request.session.get("user_id")


ROLE_HIERARCHY: dict[str, int] = {
    Role.admin.value: 3,
    Role.maintainer.value: 2,
    Role.contributor.value: 1,
}


def current_user_role(request: Request) -> str | None:
    """Return the authenticated user's role (Bearer token first, then session)."""
    bearer_role = getattr(request.state, "_bearer_role", None)
    if bearer_role is not None:
        return bearer_role
    return request.session.get("role")


def require_role(request: Request, minimum: str) -> int:
    """Return user_id if the user has at least *minimum* role, else raise.

    Raises 401 if not authenticated, 403 if role is insufficient.
    """
    uid = current_user_id(request)
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_role = current_user_role(request) or ""
    if ROLE_HIERARCHY.get(user_role, 0) < ROLE_HIERARCHY[minimum]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return uid
