"""Pydantic request/response schemas for the vote and audit-log APIs."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — Pydantic needs this at runtime
from typing import Literal

from pydantic import BaseModel


class VoteOut(BaseModel):
    """Read-only representation of a persisted vote."""

    id: int
    user_id: int
    issue_id: str
    ranking: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class VoteCreate(BaseModel):
    """Payload for creating a new vote."""

    issue_id: str
    ranking: int | None = None


class VoteUpdate(BaseModel):
    """Payload for updating an existing vote's ranking."""

    issue_id: str
    ranking: int | None


class PaginatedVotes(BaseModel):
    """Paginated envelope for vote listings."""

    items: list[VoteOut]
    total: int
    page: int
    per_page: int


class AuditLogOut(BaseModel):
    """Read-only representation of an audit-log entry."""

    id: int
    user_id: int
    timestamp: datetime
    action: dict

    model_config = {"from_attributes": True}


class PaginatedAuditLog(BaseModel):
    """Paginated envelope for audit-log listings."""

    items: list[AuditLogOut]
    total: int
    page: int
    per_page: int


class UserOut(BaseModel):
    """Read-only representation of a user."""

    id: int
    github_id: int
    username: str
    avatar_url: str | None
    role: str

    model_config = {"from_attributes": True}


class RoleUpdate(BaseModel):
    """Payload for changing a user's role."""

    role: Literal["admin", "maintainer", "contributor"]


class AdminTokenUpdate(BaseModel):
    """Payload for setting or replacing the admin's GitHub API token."""

    token: str


class TokenStatusOut(BaseModel):
    """Response indicating whether the admin has a GitHub API token set."""

    has_token: bool


class FetchRequest(BaseModel):
    """Payload for fetching issues or PRs from a GitHub repository."""

    org: str
    repo: str
    type: Literal["issues", "pulls"]
    labels: str | None = None


class FetchResult(BaseModel):
    """Response after a fetch operation completes."""

    upserted: int
    org: str
    repo: str
