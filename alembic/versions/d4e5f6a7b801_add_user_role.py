"""add user role column

Revision ID: d4e5f6a7b801
Revises: c3a1f7e2d401
Create Date: 2026-03-25 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b801"
down_revision: str | Sequence[str] | None = "c3a1f7e2d401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(),
            nullable=False,
            server_default="contributor",
        ),
    )
    op.create_check_constraint(
        "ck_user_role",
        "users",
        "role IN ('admin', 'maintainer', 'contributor')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_user_role", "users", type_="check")
    op.drop_column("users", "role")
