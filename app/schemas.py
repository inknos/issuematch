from __future__ import annotations

from pydantic import BaseModel


class VoteOut(BaseModel):
    id: int
    user_id: int
    issue_id: str
    ranking: int | None

    model_config = {"from_attributes": True}


class VoteCreate(BaseModel):
    issue_id: str
    ranking: int | None = None


class VoteUpdate(BaseModel):
    issue_id: str
    ranking: int | None


class PaginatedVotes(BaseModel):
    items: list[VoteOut]
    total: int
    page: int
    per_page: int
