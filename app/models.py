from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # org/repo#number
    org: Mapped[str] = mapped_column(String, nullable=False)
    repo: Mapped[str] = mapped_column(String, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    labels: Mapped[list | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="open")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    votes: Mapped[list[Vote]] = relationship(back_populates="issue")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    github_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    access_token: Mapped[str | None] = mapped_column(String, nullable=True)

    votes: Mapped[list[Vote]] = relationship(back_populates="user")


class Vote(Base):
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
    issue_id: Mapped[str] = mapped_column(String, ForeignKey("issues.id"), nullable=False)
    ranking: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[User] = relationship(back_populates="votes")
    issue: Mapped[Issue] = relationship(back_populates="votes")
