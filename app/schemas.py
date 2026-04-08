"""Pydantic request/response schemas for the vote and audit-log APIs."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — Pydantic needs this at runtime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

Ranking = Annotated[
    int,
    Field(
        ge=-3,
        le=3,
        description="Sentiment score from -3 (strong reject) to +3 (strong accept);"
        " 0 is not allowed.",
    ),
]


class _RankingValidator:
    @field_validator("ranking")
    @classmethod
    def ranking_not_zero(cls, v: int | None) -> int | None:
        if v == 0:
            msg = "ranking must not be 0"
            raise ValueError(msg)
        return v


class VoteOut(_RankingValidator, BaseModel):
    """Read-only representation of a persisted vote."""

    id: int
    user_id: int
    issue_id: str
    ranking: Ranking | None
    created_at: datetime

    model_config = {"from_attributes": True}


class VoteCreate(_RankingValidator, BaseModel):
    """Payload for creating a new vote."""

    issue_id: str
    ranking: Ranking | None = None


class VoteUpdate(_RankingValidator, BaseModel):
    """Payload for updating an existing vote's ranking (identified by issue_id)."""

    issue_id: str
    ranking: Ranking | None


class VoteRankingUpdate(_RankingValidator, BaseModel):
    """Payload for updating a vote identified by its DB id (ranking only)."""

    ranking: Ranking | None


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
    username: str
    avatar_url: str | None
    role: str

    model_config = {"from_attributes": True}


class RoleUpdate(BaseModel):
    """Payload for changing a user's role."""

    role: Literal["admin", "maintainer", "contributor"]


class UserCreate(BaseModel):
    """Payload for an admin creating a new user."""

    username: str
    role: Literal["admin", "maintainer", "contributor"] = "contributor"
    password: str


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
    mode: Literal["merge", "replace", "subtract"] = "merge"


class FetchResult(BaseModel):
    """Response after a fetch operation completes."""

    upserted: int
    removed: int = 0
    org: str
    repo: str


class IssueSummaryOut(BaseModel):
    """Lightweight issue representation for listings (no body/labels)."""

    id: str
    org: str
    repo: str
    number: int
    type: str
    title: str
    url: str
    state: str
    created_at: datetime | None
    fetched_at: datetime

    model_config = {"from_attributes": True}


class IssueOut(IssueSummaryOut):
    """Full issue representation including body and labels."""

    body: str | None
    labels: list | None


class PaginatedIssueSummaries(BaseModel):
    """Paginated envelope for summary issue listings."""

    items: list[IssueSummaryOut]
    total: int
    page: int
    per_page: int


class PaginatedIssues(BaseModel):
    """Paginated envelope for full issue listings."""

    items: list[IssueOut]
    total: int
    page: int
    per_page: int


class ResultOut(BaseModel):
    """Aggregated vote result for a single issue."""

    issue_id: str
    org: str
    repo: str
    number: int
    type: str
    title: str
    url: str
    avg_ranking: float | None
    median_ranking: float | None
    vote_count: int


class PaginatedResults(BaseModel):
    """Paginated envelope for aggregated vote results."""

    items: list[ResultOut]
    total: int
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# Password & API-token schemas
# ---------------------------------------------------------------------------


class PasswordUpdate(BaseModel):
    """Payload for a user changing their own password."""

    current_password: str
    new_password: str


class AdminPasswordReset(BaseModel):
    """Payload for an admin resetting any user's password."""

    new_password: str


class ApiTokenCreate(BaseModel):
    """Payload for creating a new API token."""

    name: str
    role: Literal["admin", "maintainer", "contributor"]


class ApiTokenOut(BaseModel):
    """Read-only representation of an API token (no secret)."""

    id: int
    name: str
    token_prefix: str
    role: str
    created_at: datetime
    last_used_at: datetime | None
    is_active: bool

    model_config = {"from_attributes": True}


class ApiTokenCreated(ApiTokenOut):
    """Returned once at creation time — includes the raw secret."""

    raw_token: str
