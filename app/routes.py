"""HTML and JSON API routes for voting and results."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.auth import (
    ROLE_HIERARCHY,
    AdminUid,
    ContributorUid,
    CurrentRole,
    MaintainerUid,
    current_user_id,
    current_user_role,
)
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
from app.errors import (
    BatchTooLargeError,
    DuplicateUsernameError,
    DuplicateVoteError,
    EmptyFieldError,
    ForbiddenAccessError,
    IssueNotFoundError,
    MissingConfigError,
    NoPasswordSetError,
    PasswordTooShortError,
    RoleEscalationError,
    SelfActionError,
    TokenNotFoundError,
    UserNotFoundError,
    VoteNotFoundError,
    WrongPasswordError,
)
from app.github import fetch_and_store
from app.version import __version__

if TYPE_CHECKING:
    from collections.abc import Sequence

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
    IssueOut,
    PaginatedAuditLog,
    PaginatedIssueSummaries,
    PaginatedResults,
    PaginatedVotes,
    PasswordUpdate,
    RoleUpdate,
    TokenStatusOut,
    UserCreate,
    UserOut,
    VoteCreate,
    VoteOut,
    VoteRankingUpdate,
    VoteUpdate,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["APP_VERSION"] = __version__


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    "user_created": ("User Created", "bg-success"),
    "user_deleted": ("User Deleted", "bg-danger"),
}


async def _next_issue_for_user(
    session: AsyncSession,
    user_id: int | None = None,
) -> Issue | None:
    """Pick a random issue with the fewest total votes (across all users).

    When *user_id* is provided the issues that user has already voted on are
    excluded so the caller always receives a fresh issue to vote on.

    Among the remaining candidates the one with the globally smallest vote
    count is chosen at random, so unvoted issues (count 0) are naturally
    preferred.  Returns ``None`` when no eligible issue exists.
    """
    base = select(
        Issue.id.label("issue_id"),
        func.count(Vote.id).label("cnt"),
    ).outerjoin(Vote, Vote.issue_id == Issue.id)

    if user_id is not None:
        already_voted = select(Vote.issue_id).where(Vote.user_id == user_id).subquery()
        base = base.where(Issue.id.notin_(select(already_voted)))

    vote_counts = base.group_by(Issue.id).subquery()

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

    issue = await _next_issue_for_user(session, user_id=uid)
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
        raise IssueNotFoundError

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

    issue = await _next_issue_for_user(session, user_id=uid)
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
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    action_type: str | None = None,
    user_id: int | None = None,
) -> HTMLResponse:
    """Render the paginated activity log.

    Maintainer+ sees all users' activity; contributors see only their own.
    """
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]

    role = current_user_role(request) or "contributor"
    is_maintainer = ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY["maintainer"]

    base = select(AuditLog)
    if not is_maintainer:
        base = base.where(AuditLog.user_id == uid)
    elif user_id is not None:
        base = base.where(AuditLog.user_id == user_id)

    if action_type:
        base = base.where(AuditLog.action["type"].as_string() == action_type.lower())

    count_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar_one()

    offset = (max(page, 1) - 1) * per_page
    result = await session.execute(
        base.options(selectinload(AuditLog.user))
        .order_by(AuditLog.timestamp.desc())
        .offset(offset)
        .limit(per_page),
    )
    entries = list(result.scalars().all())

    users: list[User] = []
    if is_maintainer:
        users_result = await session.execute(select(User).order_by(User.username))
        users = list(users_result.scalars().all())

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
            "is_maintainer": is_maintainer,
            "users": users,
            "filter_user_id": user_id,
        },
    )


@router.get("/votes", response_class=HTMLResponse)
async def results_page(
    request: Request,
    session: SessionDep,
    sort_by: str = "avg_ranking",
    order: str = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
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
# JSON API — public
# ---------------------------------------------------------------------------


@router.get(
    "/api/issues/json",
    response_model=PaginatedIssueSummaries,
    tags=["api"],
    operation_id="list_issues",
)
async def list_issues(
    session: SessionDep,
    org: str | None = None,
    repo: str | None = None,
    item_type: str | None = None,
    state: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """Return a paginated, filterable list of stored issues (public)."""
    base = select(Issue)

    if org is not None:
        base = base.where(Issue.org == org)
    if repo is not None:
        base = base.where(Issue.repo == repo)
    if item_type is not None:
        base = base.where(Issue.type == item_type)
    if state is not None:
        base = base.where(Issue.state == state)

    count_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar_one()

    offset = (max(page, 1) - 1) * per_page
    result = await session.execute(
        base.order_by(Issue.created_at.desc().nulls_last()).offset(offset).limit(per_page),
    )
    items = list(result.scalars().all())

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get(
    "/api/issues/{org}/{repo}/{item_type}/{number}/json",
    response_model=IssueOut,
    tags=["api"],
    operation_id="get_issue",
)
async def get_issue(
    org: str,
    repo: str,
    item_type: str,
    number: int,
    session: SessionDep,
) -> Issue:
    """Return a single stored issue by its components (public)."""
    issue_id = f"{org}/{repo}/{item_type}/{number}"
    result = await session.execute(select(Issue).where(Issue.id == issue_id))
    issue = result.scalar_one_or_none()
    if issue is None:
        raise IssueNotFoundError
    return issue


@router.get(
    "/api/results/json",
    response_model=PaginatedResults,
    tags=["api"],
    operation_id="list_results",
)
async def list_results(
    session: SessionDep,
    sort_by: str = "avg_ranking",
    order: str = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """Return paginated average rankings per issue (public)."""
    rows, total = await _results_query(
        session,
        sort_by=sort_by,
        order=order,
        page=page,
        per_page=per_page,
    )
    return {"items": rows, "total": total, "page": page, "per_page": per_page}


# ---------------------------------------------------------------------------
# JSON API — "me" shortcuts (contributor+)
# ---------------------------------------------------------------------------


@router.get(
    "/api/me",
    response_model=UserOut,
    tags=["api"],
    operation_id="get_me",
)
async def get_me(
    caller_uid: ContributorUid,
    session: SessionDep,
) -> User:
    """Return the profile of the currently authenticated user (contributor+)."""
    result = await session.execute(select(User).where(User.id == caller_uid))
    return result.scalar_one()


_MAX_BATCH_SIZE = 100


async def _create_votes(
    session: AsyncSession,
    user_id: int,
    items: list[VoteCreate],
) -> list[Vote]:
    """Insert new votes for *user_id*; raises 409 if any already exist."""
    if len(items) > _MAX_BATCH_SIZE:
        raise BatchTooLargeError
    issue_ids = [item.issue_id for item in items]
    existing = await session.execute(
        select(Vote.issue_id).where(Vote.user_id == user_id, Vote.issue_id.in_(issue_ids)),
    )
    if existing.scalars().first() is not None:
        raise DuplicateVoteError
    votes: list[Vote] = []
    for item in items:
        vote = Vote(user_id=user_id, issue_id=item.issue_id, ranking=item.ranking)
        session.add(vote)
        _log_action(
            session,
            user_id,
            {"type": "vote_create", "issue_id": item.issue_id, "ranking": item.ranking},
        )
        votes.append(vote)
    await session.commit()
    for v in votes:
        await session.refresh(v)
    return votes


async def _update_votes(
    session: AsyncSession,
    user_id: int,
    items: list[VoteUpdate],
) -> list[Vote]:
    """Update existing votes for *user_id* by issue_id; raises 404 if any missing."""
    if len(items) > _MAX_BATCH_SIZE:
        raise BatchTooLargeError
    issue_ids = [item.issue_id for item in items]
    result = await session.execute(
        select(Vote).where(Vote.user_id == user_id, Vote.issue_id.in_(issue_ids)),
    )
    vote_map = {v.issue_id: v for v in result.scalars().all()}
    for item in items:
        if item.issue_id not in vote_map:
            raise VoteNotFoundError
    votes: list[Vote] = []
    for item in items:
        vote = vote_map[item.issue_id]
        old_ranking = vote.ranking
        vote.ranking = item.ranking
        _log_action(
            session,
            user_id,
            {
                "type": "vote_update",
                "issue_id": item.issue_id,
                "old_ranking": old_ranking,
                "new_ranking": item.ranking,
            },
        )
        votes.append(vote)
    await session.commit()
    for v in votes:
        await session.refresh(v)
    return votes


async def _update_vote_by_id(
    session: AsyncSession,
    user_id: int,
    vote_id: int,
    ranking: int | None,
) -> Vote:
    """Update a single vote by its DB id; raises 404 if not found or not owned."""
    result = await session.execute(
        select(Vote).where(Vote.id == vote_id, Vote.user_id == user_id),
    )
    vote = result.scalar_one_or_none()
    if vote is None:
        raise VoteNotFoundError
    old_ranking = vote.ranking
    vote.ranking = ranking
    _log_action(
        session,
        user_id,
        {
            "type": "vote_update",
            "issue_id": vote.issue_id,
            "old_ranking": old_ranking,
            "new_ranking": ranking,
        },
    )
    await session.commit()
    await session.refresh(vote)
    return vote


async def _delete_vote_by_id(
    session: AsyncSession,
    user_id: int,
    vote_id: int,
) -> None:
    """Delete a single vote by its DB id; raises 404 if not found or not owned."""
    result = await session.execute(
        select(Vote).where(Vote.id == vote_id, Vote.user_id == user_id),
    )
    vote = result.scalar_one_or_none()
    if vote is None:
        raise VoteNotFoundError
    _log_action(
        session,
        user_id,
        {"type": "vote_delete", "issue_id": vote.issue_id, "ranking": vote.ranking},
    )
    await session.execute(delete(Vote).where(Vote.id == vote_id))
    await session.commit()


# --- /api/me/votes endpoints (thin wrappers) ---


@router.post(
    "/api/me/votes",
    response_model=list[VoteOut],
    status_code=201,
    tags=["api"],
    operation_id="create_my_votes",
)
async def create_my_votes(
    caller_uid: ContributorUid,
    body: list[VoteCreate],
    session: SessionDep,
) -> list[Vote]:
    """Create votes for the current user (contributor+). Body is a list."""
    return await _create_votes(session, caller_uid, body)


@router.put(
    "/api/me/votes",
    response_model=list[VoteOut],
    tags=["api"],
    operation_id="update_my_votes",
)
async def update_my_votes(
    caller_uid: ContributorUid,
    body: list[VoteUpdate],
    session: SessionDep,
) -> list[Vote]:
    """Update votes for the current user by issue_id (contributor+). Body is a list."""
    return await _update_votes(session, caller_uid, body)


@router.put(
    "/api/me/votes/{vote_id}",
    response_model=VoteOut,
    tags=["api"],
    operation_id="update_my_vote",
)
async def update_my_vote(
    caller_uid: ContributorUid,
    vote_id: int,
    body: VoteRankingUpdate,
    session: SessionDep,
) -> Vote:
    """Update a single vote by its DB id for the current user (contributor+)."""
    return await _update_vote_by_id(session, caller_uid, vote_id, body.ranking)


@router.delete(
    "/api/me/votes/{vote_id}",
    status_code=204,
    tags=["api"],
    operation_id="delete_my_vote",
)
async def delete_my_vote(
    caller_uid: ContributorUid,
    vote_id: int,
    session: SessionDep,
) -> Response:
    """Delete a single vote by its DB id for the current user (contributor+)."""
    await _delete_vote_by_id(session, caller_uid, vote_id)
    return Response(status_code=204)


@router.get(
    "/api/me/votes/pick/json",
    response_model=IssueOut,
    tags=["api"],
    operation_id="pick_issue_to_vote",
    responses={204: {"description": "No unvoted issues available"}},
)
async def pick_issue_to_vote(
    caller_uid: ContributorUid,
    session: SessionDep,
) -> Issue | Response:
    """Return a random issue the caller has not yet voted on (contributor+).

    Prefers issues with the fewest total votes globally.  Returns 204 when
    every issue has already been voted on by the caller.
    """
    issue = await _next_issue_for_user(session, user_id=caller_uid)
    if issue is None:
        return Response(status_code=204)
    return issue


# ---------------------------------------------------------------------------
# JSON API — contributor+
# ---------------------------------------------------------------------------


@router.get(
    "/api/votes/json",
    response_model=PaginatedVotes,
    tags=["api"],
    operation_id="list_votes",
)
async def list_votes(
    caller_uid: ContributorUid,  # noqa: ARG001
    session: SessionDep,
    issue_id: str | None = None,
    org: str | None = None,
    repo: str | None = None,
    user_id: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """Return a paginated, filterable list of votes (contributor+)."""
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


@router.get(
    "/api/users/{user_id}/votes/json",
    response_model=list[VoteOut],
    tags=["api"],
    operation_id="get_user_votes",
)
async def get_user_votes(
    caller_uid: ContributorUid,
    caller_role: CurrentRole,
    user_id: int,
    session: SessionDep,
    issue_id: str | None = None,
) -> list[Vote]:
    """Return all votes for a user (own for contributor, any for maintainer+)."""
    if caller_uid != user_id and ROLE_HIERARCHY.get(caller_role, 0) < ROLE_HIERARCHY["maintainer"]:
        raise ForbiddenAccessError
    stmt = select(Vote).where(Vote.user_id == user_id)
    if issue_id is not None:
        stmt = stmt.where(Vote.issue_id == issue_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/users/{user_id}/votes",
    response_model=list[VoteOut],
    status_code=201,
    tags=["api"],
    operation_id="create_user_votes",
)
async def create_user_votes(
    caller_uid: ContributorUid,
    user_id: int,
    body: list[VoteCreate],
    session: SessionDep,
) -> list[Vote]:
    """Create votes for the given user; 409 if any already exist (contributor+, own only)."""
    if caller_uid != user_id:
        raise ForbiddenAccessError
    return await _create_votes(session, user_id, body)


@router.put(
    "/api/users/{user_id}/votes",
    response_model=list[VoteOut],
    tags=["api"],
    operation_id="update_user_votes",
)
async def update_user_votes(
    caller_uid: ContributorUid,
    user_id: int,
    body: list[VoteUpdate],
    session: SessionDep,
) -> list[Vote]:
    """Update votes for the given user by issue_id; 404 if any missing (contributor+, own only)."""
    if caller_uid != user_id:
        raise ForbiddenAccessError
    return await _update_votes(session, user_id, body)


@router.put(
    "/api/users/{user_id}/votes/{vote_id}",
    response_model=VoteOut,
    tags=["api"],
    operation_id="update_user_vote",
)
async def update_user_vote(
    caller_uid: ContributorUid,
    user_id: int,
    vote_id: int,
    body: VoteRankingUpdate,
    session: SessionDep,
) -> Vote:
    """Update a single vote by its DB id (contributor+, own only)."""
    if caller_uid != user_id:
        raise ForbiddenAccessError
    return await _update_vote_by_id(session, user_id, vote_id, body.ranking)


@router.delete(
    "/api/users/{user_id}/votes/{vote_id}",
    status_code=204,
    tags=["api"],
    operation_id="delete_user_vote",
)
async def delete_user_vote(
    caller_uid: ContributorUid,
    user_id: int,
    vote_id: int,
    session: SessionDep,
) -> Response:
    """Delete a specific vote owned by the given user; 404 if not found (contributor+, own only)."""
    if caller_uid != user_id:
        raise ForbiddenAccessError
    await _delete_vote_by_id(session, user_id, vote_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Activity log API
# ---------------------------------------------------------------------------


@router.get(
    "/api/activity/json",
    response_model=PaginatedAuditLog,
    tags=["api"],
    operation_id="list_activity",
)
async def list_activity(
    caller_uid: MaintainerUid,  # noqa: ARG001
    session: SessionDep,
    user_id: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """Return a paginated, optionally user-filtered activity log (maintainer+)."""
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


@router.get(
    "/api/users/{user_id}/activity/json",
    response_model=list[AuditLogOut],
    tags=["api"],
    operation_id="get_user_activity",
)
async def get_user_activity(
    caller_uid: ContributorUid,
    caller_role: CurrentRole,
    user_id: int,
    session: SessionDep,
) -> list[AuditLog]:
    """Return activity for a user (own for contributor, any for maintainer+)."""
    if caller_uid != user_id and ROLE_HIERARCHY.get(caller_role, 0) < ROLE_HIERARCHY["maintainer"]:
        raise ForbiddenAccessError
    result = await session.execute(
        select(AuditLog).where(AuditLog.user_id == user_id).order_by(AuditLog.timestamp.desc()),
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Admin / maintainer API
# ---------------------------------------------------------------------------


@router.get(
    "/api/admin/users/json",
    response_model=list[UserOut],
    tags=["api"],
    operation_id="list_users",
)
async def list_users(
    caller_uid: MaintainerUid,  # noqa: ARG001
    session: SessionDep,
) -> list[User]:
    """Return all users with their roles (maintainer+)."""
    result = await session.execute(select(User).order_by(User.username))
    return list(result.scalars().all())


@router.post(
    "/api/admin/users",
    response_model=UserOut,
    status_code=201,
    tags=["api"],
    operation_id="create_user",
)
async def create_user(
    admin_uid: AdminUid,
    body: UserCreate,
    session: SessionDep,
) -> User:
    """Create a new user with a role and password (admin only)."""
    username = body.username.strip()
    if not username:
        raise EmptyFieldError
    min_password_length = 8
    if len(body.password) < min_password_length:
        raise PasswordTooShortError

    existing = await session.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none() is not None:
        raise DuplicateUsernameError

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


@router.delete(
    "/api/admin/users/{user_id}",
    status_code=204,
    tags=["api"],
    operation_id="delete_user",
)
async def delete_user(
    admin_uid: AdminUid,
    user_id: int,
    session: SessionDep,
) -> Response:
    """Delete a user and all their related data (admin only)."""
    if admin_uid == user_id:
        raise SelfActionError
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFoundError

    username = user.username
    await session.execute(delete(ApiToken).where(ApiToken.user_id == user_id))
    await session.execute(delete(Vote).where(Vote.user_id == user_id))
    await session.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
    await session.execute(delete(User).where(User.id == user_id))
    _log_action(
        session,
        admin_uid,
        {"type": "user_deleted", "target_user_id": user_id, "username": username},
    )
    await session.commit()
    return Response(status_code=204)


@router.patch("/api/admin/users/{user_id}/role", response_model=UserOut)
async def update_user_role(
    admin_uid: AdminUid,
    user_id: int,
    body: RoleUpdate,
    session: SessionDep,
) -> User:
    """Change a user's role (admin only)."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFoundError
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


@router.get(
    "/api/admin/github/token/json",
    response_model=TokenStatusOut,
    tags=["api"],
    operation_id="get_github_token_status",
)
async def admin_status(
    admin_uid: AdminUid,
    session: SessionDep,
) -> dict:
    """Return whether the current admin has a GitHub API token set (admin only)."""
    result = await session.execute(select(User).where(User.id == admin_uid))
    user = result.scalar_one()
    return {"has_token": user.github_token_encrypted is not None}


@router.put(
    "/api/admin/github/token",
    response_model=TokenStatusOut,
    tags=["api"],
    operation_id="update_github_token",
)
async def update_admin_token(
    admin_uid: AdminUid,
    body: AdminTokenUpdate,
    session: SessionDep,
) -> dict:
    """Set or replace the admin's GitHub API token (encrypted at rest, admin only)."""
    result = await session.execute(select(User).where(User.id == admin_uid))
    user = result.scalar_one()
    user.github_token_encrypted = encrypt_token(body.token)
    _log_action(session, admin_uid, {"type": "token_update"})
    await session.commit()
    return {"has_token": True}


@router.put("/api/admin/users/{user_id}/password", tags=["api"], operation_id="reset_user_password")
async def admin_reset_password(
    admin_uid: AdminUid,
    user_id: int,
    body: AdminPasswordReset,
    session: SessionDep,
) -> dict:
    """Set or reset a user's password (admin only)."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFoundError
    user.password_hash = hash_password(body.new_password)
    _log_action(
        session,
        admin_uid,
        {"type": "password_reset", "target_user_id": user_id},
    )
    await session.commit()
    return {"ok": True}


@router.post(
    "/api/admin/github/fetch",
    response_model=FetchResult,
    tags=["api"],
    operation_id="fetch_issues",
)
async def admin_fetch(
    caller_uid: MaintainerUid,
    body: FetchRequest,
    session: SessionDep,
) -> dict:
    """Fetch issues or PRs from GitHub using a stored token (maintainer+)."""
    result = await session.execute(
        select(User).where(User.github_token_encrypted.isnot(None)).limit(1),
    )
    token_user = result.scalar_one_or_none()
    if token_user is None:
        raise MissingConfigError

    token = decrypt_token(token_user.github_token_encrypted)
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
        caller_uid,
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
    admin_uid: AdminUid,
    request: Request,
    session: SessionDep,
) -> HTMLResponse:
    """Render the admin user-management page (admin only)."""
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
# User page (password + tokens, all authenticated users — contributor+)
# ---------------------------------------------------------------------------


@router.get("/user", response_class=HTMLResponse)
async def user_page(
    caller_uid: ContributorUid,
    caller_role: CurrentRole,
    request: Request,
    session: SessionDep,
) -> HTMLResponse:
    """Render the user account page (password change + API tokens)."""
    result = await session.execute(select(User).where(User.id == caller_uid))
    user = result.scalar_one()
    token_result = await session.execute(
        select(ApiToken).where(ApiToken.user_id == caller_uid).order_by(ApiToken.created_at.desc()),
    )
    tokens = list(token_result.scalars().all())
    role_level = ROLE_HIERARCHY.get(caller_role, 1)
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


@router.put("/api/user/password", tags=["api"], operation_id="change_password")
async def change_own_password(
    caller_uid: ContributorUid,
    body: PasswordUpdate,
    session: SessionDep,
) -> dict:
    """Change the current user's password (requires current password, contributor+)."""
    result = await session.execute(select(User).where(User.id == caller_uid))
    user = result.scalar_one()

    if user.password_hash is None:
        verify_password(body.current_password, DUMMY_HASH)
        raise NoPasswordSetError

    if not verify_password(body.current_password, user.password_hash):
        raise WrongPasswordError

    user.password_hash = hash_password(body.new_password)
    _log_action(session, caller_uid, {"type": "password_change"})
    await session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# API token CRUD (contributor+)
# ---------------------------------------------------------------------------


@router.get(
    "/api/tokens/json",
    response_model=list[ApiTokenOut],
    tags=["api"],
    operation_id="list_tokens",
)
async def list_tokens(
    caller_uid: ContributorUid,
    caller_role: CurrentRole,  # noqa: ARG001
    session: SessionDep,
) -> list[ApiToken]:
    """List the current user's API tokens."""
    result = await session.execute(
        select(ApiToken).where(ApiToken.user_id == caller_uid).order_by(ApiToken.created_at.desc()),
    )
    return list(result.scalars().all())


@router.post(
    "/api/tokens",
    response_model=ApiTokenCreated,
    status_code=201,
    tags=["api"],
    operation_id="create_token",
)
async def create_token(
    caller_uid: ContributorUid,
    caller_role: CurrentRole,
    body: ApiTokenCreate,
    session: SessionDep,
) -> dict:
    """Create a new API token. The raw token is returned only once (contributor+)."""
    user_level = ROLE_HIERARCHY.get(caller_role, 1)
    requested_level = ROLE_HIERARCHY.get(body.role, 0)
    if requested_level > user_level:
        msg = f"Cannot create token with role '{body.role}' — exceeds your level"
        raise RoleEscalationError(msg)

    raw, token_hash, prefix = generate_api_token()
    api_token = ApiToken(
        user_id=caller_uid,
        token_hash=token_hash,
        token_prefix=prefix,
        name=body.name,
        role=body.role,
    )
    session.add(api_token)
    _log_action(
        session,
        caller_uid,
        {"type": "api_token_create", "name": body.name, "role": body.role},
    )
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


@router.delete("/api/tokens/{token_id}", status_code=204, tags=["api"], operation_id="revoke_token")
async def revoke_token(
    caller_uid: ContributorUid,
    token_id: int,
    session: SessionDep,
) -> Response:
    """Revoke (soft-delete) an API token. Only the owner can revoke (contributor+)."""
    result = await session.execute(
        select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == caller_uid),
    )
    api_token = result.scalar_one_or_none()
    if api_token is None:
        raise TokenNotFoundError
    api_token.is_active = False
    _log_action(session, caller_uid, {"type": "api_token_revoke", "token_id": token_id})
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


def _compute_median(values: Sequence[int | float]) -> float | None:
    """Return the median of *values*, or ``None`` when empty."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return round((s[mid - 1] + s[mid]) / 2, 2)


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
    raw_rows = result.all()

    issue_ids = [row.issue_id for row in raw_rows]
    median_map: dict[str, float | None] = {}
    if issue_ids:
        vote_result = await session.execute(
            select(Vote.issue_id, Vote.ranking).where(
                Vote.issue_id.in_(issue_ids),
                Vote.ranking.isnot(None),
            ),
        )
        rankings_by_issue: dict[str, list[int]] = {}
        for v in vote_result.all():
            rankings_by_issue.setdefault(v.issue_id, []).append(v.ranking)
        for iid in issue_ids:
            median_map[iid] = _compute_median(rankings_by_issue.get(iid, []))

    rows = [
        {
            "issue_id": row.issue_id,
            "org": row.org,
            "repo": row.repo,
            "number": row.number,
            "type": row.type,
            "title": row.title,
            "url": row.url,
            "avg_ranking": round(row.avg_ranking, 2) if row.avg_ranking is not None else None,
            "median_ranking": median_map.get(row.issue_id),
            "vote_count": row.vote_count,
        }
        for row in raw_rows
    ]

    if sort_by == "median_ranking":
        reverse = order != "asc"
        rows.sort(
            key=lambda r: (r["median_ranking"] is None, r["median_ranking"] or 0),
            reverse=reverse,
        )

    return rows, total
