"""GitHub API integration for fetching issues and pull requests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import httpx
from sqlalchemy import delete, select

from app.errors import GitHubAPIError
from app.models import Issue

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

GITHUB_API = "https://api.github.com"


async def fetch_and_store(
    *,
    token: str,
    org: str,
    repo: str,
    item_type: Literal["issues", "pulls"] = "issues",
    labels: str | None = None,
    state: str = "open",
    mode: Literal["merge", "replace", "subtract"] = "merge",
    session_factory: async_sessionmaker,
) -> tuple[int, int]:
    """Fetch issues or PRs from the GitHub API and store them according to *mode*.

    Modes:
        merge: Upsert fetched items (insert new, update existing, leave others).
        replace: Delete issues in the same org/repo/type scope that were NOT
            returned by the fetch, then upsert the fetched items.
        subtract: Delete issues from the DB that *were* returned by the fetch.

    Returns:
        ``(upserted, removed)`` counts.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    }
    params: dict[str, str | int] = {"state": state, "per_page": 100, "page": 1}
    if labels and item_type == "issues":
        params["labels"] = labels

    type_label = "issue" if item_type == "issues" else "pull"

    all_items: list[dict] = []
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        while True:
            url = f"{GITHUB_API}/repos/{org}/{repo}/{item_type}"
            resp = await client.get(url, params=params)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                msg = f"GitHub API responded with {exc.response.status_code} for {org}/{repo}"
                raise GitHubAPIError(msg) from exc
            items = resp.json()
            if not items:
                break
            all_items.extend(items)
            params["page"] = int(params["page"]) + 1

    if type_label == "issue":
        all_items = [i for i in all_items if "pull_request" not in i]

    fetched_ids = {f"{org}/{repo}/{type_label}/{item['number']}" for item in all_items}

    if mode == "subtract":
        removed = await _remove_issues(session_factory, fetched_ids)
        return 0, removed

    upserted = 0
    for i in range(0, len(all_items), 100):
        page = all_items[i : i + 100]
        async with session_factory() as db:
            upserted += await _upsert_page(db, page, org, repo, type_label)
            await db.commit()

    removed = 0
    if mode == "replace":
        removed = await _remove_stale_issues(
            session_factory,
            org,
            repo,
            type_label,
            fetched_ids,
        )

    return upserted, removed


async def _remove_issues(
    session_factory: async_sessionmaker,
    issue_ids: set[str],
) -> int:
    """Delete issues whose IDs are in *issue_ids*. Votes are preserved."""
    if not issue_ids:
        return 0
    async with session_factory() as db:
        result = await db.execute(delete(Issue).where(Issue.id.in_(issue_ids)))
        await db.commit()
        return result.rowcount  # type: ignore[return-value]


async def _remove_stale_issues(
    session_factory: async_sessionmaker,
    org: str,
    repo: str,
    type_label: str,
    keep_ids: set[str],
) -> int:
    """Delete issues in the org/repo/type scope whose IDs are NOT in *keep_ids*."""
    async with session_factory() as db:
        stale_q = select(Issue.id).where(
            Issue.org == org,
            Issue.repo == repo,
            Issue.type == type_label,
        )
        if keep_ids:
            stale_q = stale_q.where(Issue.id.notin_(keep_ids))

        stale_result = await db.execute(stale_q)
        stale_ids = set(stale_result.scalars().all())

        if not stale_ids:
            return 0

        result = await db.execute(delete(Issue).where(Issue.id.in_(stale_ids)))
        await db.commit()
        return result.rowcount  # type: ignore[return-value]


async def _upsert_page(
    db: AsyncSession,
    items: list[dict],
    org: str,
    repo: str,
    type_label: str,
) -> int:
    """Upsert a single page of GitHub API results. Returns rows touched."""
    count = 0
    for item in items:
        issue_id = f"{org}/{repo}/{type_label}/{item['number']}"
        existing = await db.execute(select(Issue).where(Issue.id == issue_id))

        created = None
        if item.get("created_at"):
            created = datetime.fromisoformat(item["created_at"])

        label_names = [lbl["name"] for lbl in item.get("labels", [])]

        row = existing.scalar_one_or_none()
        if row is None:
            row = Issue(
                id=issue_id,
                org=org,
                repo=repo,
                number=item["number"],
                type=type_label,
                title=item["title"],
                body=item.get("body"),
                url=item["html_url"],
                labels=label_names,
                state=item["state"],
                created_at=created,
                fetched_at=datetime.now(UTC),
            )
            db.add(row)
        else:
            row.title = item["title"]
            row.body = item.get("body")
            row.url = item["html_url"]
            row.labels = label_names
            row.state = item["state"]
            row.created_at = created
            row.fetched_at = datetime.now(UTC)

        count += 1
    return count
