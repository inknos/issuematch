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
