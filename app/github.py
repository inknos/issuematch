"""GitHub API integration for fetching issues and pull requests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import httpx
from sqlalchemy import select

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
    session_factory: async_sessionmaker,
) -> int:
    """Fetch issues or PRs from the GitHub API and upsert them into the database.

    Args:
        token: GitHub API bearer token.
        org: GitHub organisation or owner.
        repo: Repository name.
        item_type: Whether to fetch ``"issues"`` or ``"pulls"``.
        labels: Comma-separated label filter (only for issues).
        state: Issue/PR state filter (``"open"``, ``"closed"``, ``"all"``).
        session_factory: An async session factory (``async_sessionmaker``).

    Returns:
        The number of upserted rows.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    }
    params: dict[str, str | int] = {"state": state, "per_page": 100, "page": 1}
    if labels and item_type == "issues":
        params["labels"] = labels

    type_label = "issue" if item_type == "issues" else "pull"
    upserted = 0

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        while True:
            url = f"{GITHUB_API}/repos/{org}/{repo}/{item_type}"
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            items = resp.json()
            if not items:
                break

            async with session_factory() as db:
                upserted += await _upsert_page(db, items, org, repo, type_label)
                await db.commit()

            params["page"] = int(params["page"]) + 1

    return upserted


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
        if type_label == "issue" and "pull_request" in item:
            continue

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
