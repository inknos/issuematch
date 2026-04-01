"""Password login/logout routes, session helpers, and role dependency chain."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import SESSION_SECRET  # noqa: F401 — re-exported for tests
from app.crypto import DUMMY_HASH, verify_password
from app.database import SessionDep  # noqa: TC001 — runtime-evaluated by FastAPI DI
from app.errors import InsufficientPermissionsError, InvalidCredentialsError, NotAuthenticatedError
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
        raise InvalidCredentialsError

    if not verify_password(password, user.password_hash):
        raise InvalidCredentialsError

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


# ---------------------------------------------------------------------------
# Low-level session/bearer helpers (used by HTML pages & dependency chain)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Hierarchical FastAPI dependency chain
#
#   get_current_uid ──► require_contributor ──► require_maintainer ──► require_admin
#   get_current_role ─┘                    ─┘                     ─┘
# ---------------------------------------------------------------------------


def get_current_uid(request: Request) -> int:
    """Dependency: return authenticated user_id or raise 401."""
    uid = current_user_id(request)
    if uid is None:
        raise NotAuthenticatedError
    return uid


def get_current_role(request: Request) -> str:
    """Dependency: return authenticated user's role or raise 401."""
    role = current_user_role(request)
    if role is None:
        raise NotAuthenticatedError
    return role


CurrentUid = Annotated[int, Depends(get_current_uid)]
CurrentRole = Annotated[str, Depends(get_current_role)]


def require_contributor(uid: CurrentUid, role: CurrentRole) -> int:
    """Dependency: require at least contributor role."""
    if ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY["contributor"]:
        raise InsufficientPermissionsError
    return uid


ContributorUid = Annotated[int, Depends(require_contributor)]


def require_maintainer(uid: ContributorUid, role: CurrentRole) -> int:
    """Dependency: require at least maintainer role."""
    if ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY["maintainer"]:
        raise InsufficientPermissionsError
    return uid


MaintainerUid = Annotated[int, Depends(require_maintainer)]


def require_admin(uid: MaintainerUid, role: CurrentRole) -> int:
    """Dependency: require admin role."""
    if ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY["admin"]:
        raise InsufficientPermissionsError
    return uid


AdminUid = Annotated[int, Depends(require_admin)]
