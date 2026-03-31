"""HTML and JSON API routes for voting and results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select

from app.auth import ROLE_HIERARCHY, current_user_id, current_user_role, require_role
from app.crypto import (
    DUMMY_HASH,
    decrypt_token,
    encrypt_token,
    generate_api_token,
    hash_password,
    verify_password,
)
from app.database import SessionDep
from app.database import async_session as app_session_factory
from app.github import fetch_and_store

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
from app.models import ApiToken, AuditLog, Issue, User, Vote
from app.schemas import (
    AdminPasswordReset,
    AdminTokenUpdate,
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenOut,
    AuditLogOut,
    FetchRequest,
    FetchResult,
    PaginatedAuditLog,
    PaginatedVotes,
    PasswordUpdate,
    RoleUpdate,
    TokenStatusOut,
    UserCreate,
    UserOut,
    VoteCreate,
    VoteOut,
    VoteUpdate,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_login(request: Request) -> int:
    uid = current_user_id(request)
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return uid


def _issue_vote_url(issue: Issue) -> str:
    return f"/vote/{issue.org}/{issue.repo}/{issue.type}/{issue.number}"


def _log_action(session: AsyncSession, user_id: int, action: dict) -> None:
    """Append an audit-log entry (committed with the caller's transaction)."""
    session.add(AuditLog(user_id=user_id, action=action))


ACTION_LABELS: dict[str, tuple[str, str]] = {
    "vote_create": ("Voted", "bg-success"),
    "vote_update": ("Vote Updated", "bg-primary"),
    "vote_delete": ("Vote Deleted", "bg-danger"),
    "login": ("Logged In", "bg-info text-dark"),
    "logout": ("Logged Out", "bg-secondary"),
    "role_change": ("Role Changed", "bg-warning text-dark"),
    "token_update": ("Token Updated", "bg-dark"),
    "fetch": ("Fetched", "bg-dark"),
    "password_change": ("Password Changed", "bg-warning text-dark"),
    "password_reset": ("Password Reset", "bg-warning text-dark"),
    "api_token_create": ("API Token Created", "bg-success"),
    "api_token_revoke": ("API Token Revoked", "bg-danger"),
}


async def _next_issue(session: AsyncSession) -> Issue | None:
    """Pick a random issue with the fewest total votes (across all users).

    Unvoted issues (count 0) are naturally preferred.  When every issue has
    at least one vote the issue with the smallest count is chosen at random.
    Returns ``None`` only when the issues table is empty.
    """
    vote_counts = (
        select(
            Issue.id.label("issue_id"),
            func.count(Vote.id).label("cnt"),
        )
        .outerjoin(Vote, Vote.issue_id == Issue.id)
        .group_by(Issue.id)
        .subquery()
    )

    min_result = await session.execute(select(func.min(vote_counts.c.cnt)))
    min_count = min_result.scalar_one_or_none()
    if min_count is None:
        return None

    result = await session.execute(
        select(Issue)
        .join(vote_counts, Issue.id == vote_counts.c.issue_id)
        .where(vote_counts.c.cnt == min_count)
        .order_by(func.random())
        .limit(1),
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# HTML pages (server-rendered with HTMX)
# ---------------------------------------------------------------------------


@router.get("/vote", response_class=HTMLResponse, response_model=None)
async def vote_redirect(
    request: Request,
    session: SessionDep,
) -> HTMLResponse | RedirectResponse:
    """Pick a random unvoted issue and redirect, or show the done page."""
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)

    issue = await _next_issue(session)
    if issue is None:
        return templates.TemplateResponse("vote.html", {"request": request, "issue": None})

    return RedirectResponse(url=_issue_vote_url(issue), status_code=303)


@router.get("/vote/{org}/{repo}/{item_type}/{number}", response_class=HTMLResponse)
async def vote_page(
    request: Request,
    org: str,
    repo: str,
    item_type: str,
    number: int,
    session: SessionDep,
) -> HTMLResponse:
    """Render the voting card for a specific issue."""
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]

    issue_id = f"{org}/{repo}/{item_type}/{number}"
    result = await session.execute(select(Issue).where(Issue.id == issue_id))
    issue = result.scalar_one_or_none()

    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    vote_result = await session.execute(
        select(Vote).where(Vote.user_id == uid, Vote.issue_id == issue_id),
    )
    existing_vote = vote_result.scalar_one_or_none()

    resp = templates.TemplateResponse(
        "vote.html",
        {
            "request": request,
            "issue": issue,
            "existing_ranking": existing_vote.ranking if existing_vote else None,
        },
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.post("/vote", response_model=None)
async def submit_vote(
    request: Request,
    session: SessionDep,
) -> RedirectResponse:
    """Create or update a vote from the HTML form and redirect to the next issue."""
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    issue_id = form.get("issue_id")
    ranking_raw = form.get("ranking")

    if issue_id and ranking_raw is not None:
        ranking = int(ranking_raw)
        existing = await session.execute(
            select(Vote).where(Vote.user_id == uid, Vote.issue_id == str(issue_id)),
        )
        vote = existing.scalar_one_or_none()
        if vote is None:
            vote = Vote(user_id=uid, issue_id=str(issue_id), ranking=ranking)
            session.add(vote)
            _log_action(
                session,
                uid,
                {"type": "vote_create", "issue_id": str(issue_id), "ranking": ranking},
            )
        else:
            old_ranking = vote.ranking
            vote.ranking = ranking
            _log_action(
                session,
                uid,
                {
                    "type": "vote_update",
                    "issue_id": str(issue_id),
                    "old_ranking": old_ranking,
                    "new_ranking": ranking,
                },
            )
        await session.commit()

    issue = await _next_issue(session)
    if issue:
        return RedirectResponse(url=_issue_vote_url(issue), status_code=303)
    return RedirectResponse(url="/vote/done", status_code=303)


@router.get("/vote/done", response_class=HTMLResponse)
async def vote_done(request: Request) -> HTMLResponse:
    """Show the 'all issues voted' confirmation page."""
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
    return templates.TemplateResponse("vote.html", {"request": request, "issue": None})


@router.get("/activity", response_class=HTMLResponse)
async def activity_page(
    request: Request,
    session: SessionDep,
    page: int = 1,
    per_page: int = 20,
    action_type: str | None = None,
) -> HTMLResponse:
    """Render the paginated activity log for the current user."""
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]

    base = select(AuditLog).where(AuditLog.user_id == uid)

    if action_type:
        base = base.where(AuditLog.action["type"].as_string() == action_type.lower())

    count_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar_one()

    offset = (max(page, 1) - 1) * per_page
    result = await session.execute(
        base.order_by(AuditLog.timestamp.desc()).offset(offset).limit(per_page),
    )
    entries = list(result.scalars().all())

    total_pages = max(1, -(-total // per_page))
    return templates.TemplateResponse(
        "activity.html",
        {
            "request": request,
            "entries": entries,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "action_type": action_type.lower() if action_type else None,
            "action_labels": ACTION_LABELS,
        },
    )


@router.get("/votes", response_class=HTMLResponse)
async def results_page(
    request: Request,
    session: SessionDep,
    sort_by: str = "avg_ranking",
    order: str = "desc",
    page: int = 1,
    per_page: int = 20,
) -> HTMLResponse:
    """Render the sortable, paginated results table."""
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]

    rows, total = await _results_query(
        session,
        sort_by=sort_by,
        order=order,
        page=page,
        per_page=per_page,
    )
    total_pages = max(1, -(-total // per_page))  # ceil division

    vote_result = await session.execute(
        select(Vote.issue_id, Vote.id).where(Vote.user_id == uid),
    )
    user_votes = {row.issue_id: row.id for row in vote_result.all()}

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "results": rows,
            "sort_by": sort_by,
            "order": order,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "user_votes": user_votes,
            "current_user_id": uid,
        },
    )


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------


@router.get("/api/votes", response_model=PaginatedVotes)
async def list_votes(
    session: SessionDep,
    issue_id: str | None = None,
    org: str | None = None,
    repo: str | None = None,
    user_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Return a paginated, filterable list of votes."""
    base = select(Vote)

    needs_issue_join = org is not None or repo is not None
    if needs_issue_join:
        base = base.outerjoin(Issue, Vote.issue_id == Issue.id)

    if issue_id is not None:
        base = base.where(Vote.issue_id == issue_id)
    if org is not None:
        base = base.where(Issue.org == org)
    if repo is not None:
        base = base.where(Issue.repo == repo)
    if user_id is not None:
        base = base.where(Vote.user_id == user_id)

    count_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar_one()

    offset = (max(page, 1) - 1) * per_page
    result = await session.execute(base.offset(offset).limit(per_page))
    items = list(result.scalars().all())

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/api/users/{user_id}/votes", response_model=list[VoteOut])
async def get_user_votes(
    user_id: int,
    session: SessionDep,
    issue_id: str | None = None,
) -> list[Vote]:
    """Return all votes for a user, optionally filtered by issue."""
    stmt = select(Vote).where(Vote.user_id == user_id)
    if issue_id is not None:
        stmt = stmt.where(Vote.issue_id == issue_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("/api/users/{user_id}/votes", response_model=VoteOut, status_code=201)
async def create_user_vote(
    user_id: int,
    body: VoteCreate,
    session: SessionDep,
) -> Vote:
    """Create a vote for the given user; 409 if a vote already exists."""
    existing = await session.execute(
        select(Vote).where(Vote.user_id == user_id, Vote.issue_id == body.issue_id),
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Vote already exists")
    vote = Vote(user_id=user_id, issue_id=body.issue_id, ranking=body.ranking)
    session.add(vote)
    _log_action(
        session,
        user_id,
        {"type": "vote_create", "issue_id": body.issue_id, "ranking": body.ranking},
    )
    await session.commit()
    await session.refresh(vote)
    return vote


@router.put("/api/users/{user_id}/votes", response_model=VoteOut)
async def update_user_vote(
    user_id: int,
    body: VoteUpdate,
    session: SessionDep,
) -> Vote:
    """Update the ranking of an existing vote; 404 if not found."""
    result = await session.execute(
        select(Vote).where(Vote.user_id == user_id, Vote.issue_id == body.issue_id),
    )
    vote = result.scalar_one_or_none()
    if vote is None:
        raise HTTPException(status_code=404, detail="Vote not found")
    old_ranking = vote.ranking
    vote.ranking = body.ranking
    _log_action(
        session,
        user_id,
        {
            "type": "vote_update",
            "issue_id": body.issue_id,
            "old_ranking": old_ranking,
            "new_ranking": body.ranking,
        },
    )
    await session.commit()
    await session.refresh(vote)
    return vote


@router.delete("/api/users/{user_id}/votes/{vote_id}", status_code=204)
async def delete_user_vote(
    user_id: int,
    vote_id: int,
    session: SessionDep,
) -> Response:
    """Delete a specific vote owned by the given user; 404 if not found."""
    result = await session.execute(
        select(Vote).where(Vote.id == vote_id, Vote.user_id == user_id),
    )
    vote = result.scalar_one_or_none()
    if vote is None:
        raise HTTPException(status_code=404, detail="Vote not found")
    _log_action(
        session,
        user_id,
        {
            "type": "vote_delete",
            "issue_id": vote.issue_id,
            "ranking": vote.ranking,
        },
    )
    await session.execute(delete(Vote).where(Vote.id == vote_id))
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Activity log API
# ---------------------------------------------------------------------------


@router.get("/api/activity", response_model=PaginatedAuditLog)
async def list_activity(
    session: SessionDep,
    user_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Return a paginated, optionally user-filtered activity log."""
    base = select(AuditLog)
    if user_id is not None:
        base = base.where(AuditLog.user_id == user_id)

    count_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar_one()

    offset = (max(page, 1) - 1) * per_page
    result = await session.execute(
        base.order_by(AuditLog.timestamp.desc()).offset(offset).limit(per_page),
    )
    items = list(result.scalars().all())

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/api/users/{user_id}/activity", response_model=list[AuditLogOut])
async def get_user_activity(
    user_id: int,
    session: SessionDep,
) -> list[AuditLog]:
    """Return all activity-log entries for a user, newest first."""
    result = await session.execute(
        select(AuditLog).where(AuditLog.user_id == user_id).order_by(AuditLog.timestamp.desc()),
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------


@router.get("/api/admin/users", response_model=list[UserOut])
async def list_users(
    request: Request,
    session: SessionDep,
) -> list[User]:
    """Return all users with their roles (admin only)."""
    require_role(request, "admin")
    result = await session.execute(select(User).order_by(User.username))
    return list(result.scalars().all())


@router.post("/api/admin/users", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    request: Request,
    session: SessionDep,
) -> User:
    """Create a new user with a role and password (admin only)."""
    admin_uid = require_role(request, "admin")

    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username must not be empty")
    min_password_length = 8
    if len(body.password) < min_password_length:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    existing = await session.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = User(
        username=username,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    session.add(user)
    _log_action(
        session,
        admin_uid,
        {"type": "user_created", "username": username, "role": body.role},
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.patch("/api/admin/users/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: int,
    body: RoleUpdate,
    request: Request,
    session: SessionDep,
) -> User:
    """Change a user's role (admin only)."""
    admin_uid = require_role(request, "admin")
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    old_role = user.role
    user.role = body.role
    _log_action(
        session,
        admin_uid,
        {
            "type": "role_change",
            "target_user_id": user_id,
            "old_role": old_role,
            "new_role": body.role,
        },
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/api/admin", response_model=TokenStatusOut)
async def admin_status(
    request: Request,
    session: SessionDep,
) -> dict:
    """Return whether the current admin has a GitHub API token set."""
    admin_uid = require_role(request, "admin")
    result = await session.execute(select(User).where(User.id == admin_uid))
    user = result.scalar_one()
    return {"has_token": user.github_token_encrypted is not None}


@router.put("/api/admin", response_model=TokenStatusOut)
async def update_admin_token(
    body: AdminTokenUpdate,
    request: Request,
    session: SessionDep,
) -> dict:
    """Set or replace the admin's GitHub API token (encrypted at rest)."""
    admin_uid = require_role(request, "admin")
    result = await session.execute(select(User).where(User.id == admin_uid))
    user = result.scalar_one()
    user.github_token_encrypted = encrypt_token(body.token)
    _log_action(session, admin_uid, {"type": "token_update"})
    await session.commit()
    return {"has_token": True}


@router.put("/api/admin/users/{user_id}/password")
async def admin_reset_password(
    user_id: int,
    body: AdminPasswordReset,
    request: Request,
    session: SessionDep,
) -> dict:
    """Set or reset a user's password (admin only)."""
    admin_uid = require_role(request, "admin")
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(body.new_password)
    _log_action(
        session,
        admin_uid,
        {"type": "password_reset", "target_user_id": user_id},
    )
    await session.commit()
    return {"ok": True}


@router.post("/api/admin/fetch", response_model=FetchResult)
async def admin_fetch(
    body: FetchRequest,
    request: Request,
    session: SessionDep,
) -> dict:
    """Fetch issues or PRs from GitHub using the admin's stored token."""
    admin_uid = require_role(request, "admin")
    result = await session.execute(select(User).where(User.id == admin_uid))
    user = result.scalar_one()
    if user.github_token_encrypted is None:
        raise HTTPException(status_code=400, detail="No GitHub token configured")

    token = decrypt_token(user.github_token_encrypted)
    upserted, removed = await fetch_and_store(
        token=token,
        org=body.org,
        repo=body.repo,
        item_type=body.type,
        labels=body.labels,
        mode=body.mode,
        session_factory=app_session_factory,
    )
    _log_action(
        session,
        admin_uid,
        {
            "type": "fetch",
            "org": body.org,
            "repo": body.repo,
            "mode": body.mode,
            "upserted": upserted,
            "removed": removed,
        },
    )
    await session.commit()
    return {"upserted": upserted, "removed": removed, "org": body.org, "repo": body.repo}


# ---------------------------------------------------------------------------
# Admin HTML
# ---------------------------------------------------------------------------


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    session: SessionDep,
) -> HTMLResponse:
    """Render the admin user-management page (admin only)."""
    admin_uid = require_role(request, "admin")
    result = await session.execute(select(User).order_by(User.username))
    users = list(result.scalars().all())
    admin_result = await session.execute(select(User).where(User.id == admin_uid))
    admin = admin_result.scalar_one()
    return templates.TemplateResponse(
        "admin_users.html",
        {
            "request": request,
            "users": users,
            "has_token": admin.github_token_encrypted is not None,
        },
    )


# ---------------------------------------------------------------------------
# User page (password + tokens, all authenticated users)
# ---------------------------------------------------------------------------


@router.get("/user", response_class=HTMLResponse)
async def user_page(
    request: Request,
    session: SessionDep,
) -> HTMLResponse:
    """Render the user account page (password change + API tokens)."""
    uid = _require_login(request)
    result = await session.execute(select(User).where(User.id == uid))
    user = result.scalar_one()
    token_result = await session.execute(
        select(ApiToken).where(ApiToken.user_id == uid).order_by(ApiToken.created_at.desc()),
    )
    tokens = list(token_result.scalars().all())
    user_role = current_user_role(request) or "contributor"
    role_level = ROLE_HIERARCHY.get(user_role, 1)
    allowed_roles = [r for r, lvl in ROLE_HIERARCHY.items() if lvl <= role_level]
    return templates.TemplateResponse(
        "user.html",
        {
            "request": request,
            "user": user,
            "tokens": tokens,
            "allowed_roles": allowed_roles,
            "has_password": user.password_hash is not None,
        },
    )


@router.put("/api/user/password")
async def change_own_password(
    body: PasswordUpdate,
    request: Request,
    session: SessionDep,
) -> dict:
    """Change the current user's password (requires current password)."""
    uid = _require_login(request)
    result = await session.execute(select(User).where(User.id == uid))
    user = result.scalar_one()

    if user.password_hash is None:
        verify_password(body.current_password, DUMMY_HASH)
        raise HTTPException(status_code=400, detail="No password set — ask an admin to set one")

    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    user.password_hash = hash_password(body.new_password)
    _log_action(session, uid, {"type": "password_change"})
    await session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# API token CRUD (all authenticated users)
# ---------------------------------------------------------------------------


@router.get("/api/tokens", response_model=list[ApiTokenOut])
async def list_tokens(
    request: Request,
    session: SessionDep,
) -> list[ApiToken]:
    """List the current user's API tokens."""
    uid = _require_login(request)
    result = await session.execute(
        select(ApiToken).where(ApiToken.user_id == uid).order_by(ApiToken.created_at.desc()),
    )
    return list(result.scalars().all())


@router.post("/api/tokens", response_model=ApiTokenCreated, status_code=201)
async def create_token(
    body: ApiTokenCreate,
    request: Request,
    session: SessionDep,
) -> dict:
    """Create a new API token. The raw token is returned only once."""
    uid = _require_login(request)
    user_role = current_user_role(request) or "contributor"
    user_level = ROLE_HIERARCHY.get(user_role, 1)
    requested_level = ROLE_HIERARCHY.get(body.role, 0)
    if requested_level > user_level:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot create token with role '{body.role}' — exceeds your level",
        )

    raw, token_hash, prefix = generate_api_token()
    api_token = ApiToken(
        user_id=uid,
        token_hash=token_hash,
        token_prefix=prefix,
        name=body.name,
        role=body.role,
    )
    session.add(api_token)
    _log_action(session, uid, {"type": "api_token_create", "name": body.name, "role": body.role})
    await session.commit()
    await session.refresh(api_token)
    return {
        "id": api_token.id,
        "name": api_token.name,
        "token_prefix": api_token.token_prefix,
        "role": api_token.role,
        "created_at": api_token.created_at,
        "last_used_at": api_token.last_used_at,
        "is_active": api_token.is_active,
        "raw_token": raw,
    }


@router.delete("/api/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: int,
    request: Request,
    session: SessionDep,
) -> Response:
    """Revoke (soft-delete) an API token. Only the owner can revoke."""
    uid = _require_login(request)
    result = await session.execute(
        select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == uid),
    )
    api_token = result.scalar_one_or_none()
    if api_token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    api_token.is_active = False
    _log_action(session, uid, {"type": "api_token_revoke", "token_id": token_id})
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Shared query
# ---------------------------------------------------------------------------

_RESULTS_SORT_COLUMNS = {
    "title": Issue.title,
    "avg_ranking": func.avg(Vote.ranking),
    "vote_count": func.count(Vote.id),
}


async def _results_query(
    session: AsyncSession,
    *,
    sort_by: str = "avg_ranking",
    order: str = "desc",
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[dict], int]:
    base = (
        select(
            Issue.id.label("issue_id"),
            Issue.org,
            Issue.repo,
            Issue.number,
            Issue.type,
            Issue.title,
            Issue.url,
            func.avg(Vote.ranking).label("avg_ranking"),
            func.count(Vote.id).label("vote_count"),
        )
        .outerjoin(Vote, Vote.issue_id == Issue.id)
        .group_by(
            Issue.id,
            Issue.org,
            Issue.repo,
            Issue.number,
            Issue.type,
            Issue.title,
            Issue.url,
        )
    )

    sort_col = _RESULTS_SORT_COLUMNS.get(sort_by, func.avg(Vote.ranking))
    if order == "asc":
        base = base.order_by(sort_col.asc().nulls_last())
    else:
        base = base.order_by(sort_col.desc().nulls_last())

    count_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar_one()

    offset = (max(page, 1) - 1) * per_page
    result = await session.execute(base.offset(offset).limit(per_page))
    rows = [
        {
            "issue_id": row.issue_id,
            "org": row.org,
            "repo": row.repo,
            "number": row.number,
            "type": row.type,
            "title": row.title,
            "url": row.url,
            "avg_ranking": round(row.avg_ranking, 2) if row.avg_ranking else None,
            "vote_count": row.vote_count,
        }
        for row in result.all()
    ]
    return rows, total
