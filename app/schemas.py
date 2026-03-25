"""Pydantic request/response schemas for the vote API."""

from __future__ import annotations

from pydantic import BaseModel


class VoteOut(BaseModel):
    """Read-only representation of a persisted vote."""

    id: int
    user_id: int
    issue_id: str
    ranking: int | None

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
