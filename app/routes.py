from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user_id
from app.database import SessionDep
from app.models import Issue, Vote
from app.schemas import PaginatedVotes, VoteCreate, VoteOut, VoteUpdate

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
    return f"/vote/{issue.org}/{issue.repo}/{issue.number}"


async def _next_issue(session: AsyncSession, user_id: int) -> Issue | None:
    result = await session.execute(
        select(Issue)
        .where(Issue.id.notin_(select(Vote.issue_id).where(Vote.user_id == user_id)))
        .order_by(func.random())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# HTML pages (server-rendered with HTMX)
# ---------------------------------------------------------------------------


@router.get("/vote", response_class=HTMLResponse, response_model=None)
async def vote_redirect(
    request: Request,
    session: SessionDep,
):
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)

    issue = await _next_issue(session, uid)
    if issue is None:
        return templates.TemplateResponse("vote.html", {"request": request, "issue": None})

    return RedirectResponse(url=_issue_vote_url(issue), status_code=303)


@router.get("/vote/{org}/{repo}/{number}", response_class=HTMLResponse)
async def vote_page(
    request: Request,
    org: str,
    repo: str,
    number: int,
    session: SessionDep,
) -> HTMLResponse:
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]

    issue_id = f"{org}/{repo}#{number}"
    result = await session.execute(select(Issue).where(Issue.id == issue_id))
    issue = result.scalar_one_or_none()

    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    vote_result = await session.execute(
        select(Vote).where(Vote.user_id == uid, Vote.issue_id == issue_id)
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
):
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    issue_id = form.get("issue_id")
    ranking_raw = form.get("ranking")

    if issue_id and ranking_raw is not None:
        ranking = int(ranking_raw)
        existing = await session.execute(
            select(Vote).where(Vote.user_id == uid, Vote.issue_id == str(issue_id))
        )
        vote = existing.scalar_one_or_none()
        if vote is None:
            vote = Vote(user_id=uid, issue_id=str(issue_id), ranking=ranking)
            session.add(vote)
        else:
            vote.ranking = ranking
        await session.commit()

    issue = await _next_issue(session, uid)
    if issue:
        return RedirectResponse(url=_issue_vote_url(issue), status_code=303)
    return RedirectResponse(url="/vote/done", status_code=303)


@router.get("/vote/done", response_class=HTMLResponse)
async def vote_done(request: Request) -> HTMLResponse:
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]
    return templates.TemplateResponse("vote.html", {"request": request, "issue": None})


@router.get("/votes", response_class=HTMLResponse)
async def results_page(
    request: Request,
    session: SessionDep,
    sort_by: str = "avg_ranking",
    order: str = "desc",
    page: int = 1,
    per_page: int = 20,
) -> HTMLResponse:
    uid = current_user_id(request)
    if uid is None:
        return RedirectResponse(url="/login", status_code=303)  # type: ignore[return-value]

    rows, total = await _results_query(
        session, sort_by=sort_by, order=order, page=page, per_page=per_page
    )
    total_pages = max(1, -(-total // per_page))  # ceil division
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
    base = select(Vote)

    needs_issue_join = org is not None or repo is not None
    if needs_issue_join:
        base = base.join(Issue, Vote.issue_id == Issue.id)

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
    existing = await session.execute(
        select(Vote).where(Vote.user_id == user_id, Vote.issue_id == body.issue_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Vote already exists")
    vote = Vote(user_id=user_id, issue_id=body.issue_id, ranking=body.ranking)
    session.add(vote)
    await session.commit()
    await session.refresh(vote)
    return vote


@router.put("/api/users/{user_id}/votes", response_model=VoteOut)
async def update_user_vote(
    user_id: int,
    body: VoteUpdate,
    session: SessionDep,
) -> Vote:
    result = await session.execute(
        select(Vote).where(Vote.user_id == user_id, Vote.issue_id == body.issue_id)
    )
    vote = result.scalar_one_or_none()
    if vote is None:
        raise HTTPException(status_code=404, detail="Vote not found")
    vote.ranking = body.ranking
    await session.commit()
    await session.refresh(vote)
    return vote


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
            Issue.title,
            Issue.url,
            func.avg(Vote.ranking).label("avg_ranking"),
            func.count(Vote.id).label("vote_count"),
        )
        .outerjoin(Vote, Vote.issue_id == Issue.id)
        .group_by(Issue.id, Issue.org, Issue.repo, Issue.number, Issue.title, Issue.url)
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
            "title": row.title,
            "url": row.url,
            "avg_ranking": round(row.avg_ranking, 2) if row.avg_ranking else None,
            "vote_count": row.vote_count,
        }
        for row in result.all()
    ]
    return rows, total
