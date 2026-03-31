"""SQLAlchemy ORM models for issues, users, and votes."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Role(enum.StrEnum):
    """Application-level user roles, ordered by privilege."""

    admin = "admin"
    maintainer = "maintainer"
    contributor = "contributor"


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


class Issue(Base):
    """A GitHub issue fetched for ranking."""

    __tablename__ = "issues"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # org/repo/{type}/number
    org: Mapped[str] = mapped_column(String, nullable=False)
    repo: Mapped[str] = mapped_column(String, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False, default="issue")
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    labels: Mapped[list | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="open")
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    votes: Mapped[list[Vote]] = relationship(
        back_populates="issue",
        primaryjoin="Issue.id == foreign(Vote.issue_id)",
    )


class User(Base):
    """An application user authenticated via username/password."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'maintainer', 'contributor')",
            name="ck_user_role",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    github_token_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, nullable=False, default=Role.contributor.value)

    votes: Mapped[list[Vote]] = relationship(back_populates="user")
    api_tokens: Mapped[list[ApiToken]] = relationship(back_populates="user")


class Vote(Base):
    """A user's ranking of an issue (-3..3 or NULL)."""

    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("user_id", "issue_id", name="uq_user_issue"),
        CheckConstraint(
            "ranking IN (-3, -2, -1, 1, 2, 3) OR ranking IS NULL",
            name="ck_ranking_values",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    issue_id: Mapped[str] = mapped_column(String, nullable=False)
    ranking: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    user: Mapped[User] = relationship(back_populates="votes")
    issue: Mapped[Issue | None] = relationship(
        back_populates="votes",
        primaryjoin="Issue.id == foreign(Vote.issue_id)",
    )


class ApiToken(Base):
    """A user-created API token for programmatic Bearer-token access."""

    __tablename__ = "api_tokens"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'maintainer', 'contributor')",
            name="ck_api_token_role",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    token_prefix: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship(back_populates="api_tokens")


class AuditLog(Base):
    """Immutable record of a user action (vote, login, logout, etc.)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    action: Mapped[dict] = mapped_column(JSON, nullable=False)

    user: Mapped[User] = relationship()
