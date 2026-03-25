#!/usr/bin/env python3
"""Fetch GitHub issues and upsert them into the database."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

import httpx
from app.config import GITHUB_TOKEN
from app.database import async_session
from app.models import Issue
from sqlalchemy import select

GITHUB_API = "https://api.github.com"


async def fetch_and_store(
    org: str,
    repo: str,
    labels: str | None = None,
    state: str = "open",
) -> int:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
    }
    params: dict[str, str | int] = {"state": state, "per_page": 100, "page": 1}
    if labels:
        params["labels"] = labels

    upserted = 0

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        while True:
            resp = await client.get(f"{GITHUB_API}/repos/{org}/{repo}/issues", params=params)
            resp.raise_for_status()
            items = resp.json()
            if not items:
                break

            async with async_session() as session:
                for item in items:
                    if "pull_request" in item:
                        continue

                    issue_id = f"{org}/{repo}#{item['number']}"
                    existing = await session.execute(select(Issue).where(Issue.id == issue_id))

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
                            title=item["title"],
                            body=item.get("body"),
                            url=item["html_url"],
                            labels=label_names,
                            state=item["state"],
                            created_at=created,
                            fetched_at=datetime.now(UTC),
                        )
                        session.add(row)
                    else:
                        row.title = item["title"]
                        row.body = item.get("body")
                        row.url = item["html_url"]
                        row.labels = label_names
                        row.state = item["state"]
                        row.created_at = created
                        row.fetched_at = datetime.now(UTC)

                    upserted += 1

                await session.commit()

            params["page"] = int(params["page"]) + 1

    return upserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch GitHub issues into the DB")
    parser.add_argument("--org", required=True, help="GitHub organisation / owner")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--labels", default=None, help="Comma-separated label filter")
    parser.add_argument(
        "--state",
        default="open",
        choices=["open", "closed", "all"],
        help="Issue state",
    )
    args = parser.parse_args()

    count = asyncio.run(fetch_and_store(args.org, args.repo, labels=args.labels, state=args.state))
    print(f"Upserted {count} issues from {args.org}/{args.repo}")


if __name__ == "__main__":
    main()
