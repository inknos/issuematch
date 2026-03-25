"""add issue type column and unify id format to org/repo/type/number

Revision ID: e5f6a7b8c902
Revises: d4e5f6a7b801
Create Date: 2026-03-25 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c902"
down_revision: str | Sequence[str] | None = "d4e5f6a7b801"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "issues",
        sa.Column("type", sa.String(), nullable=False, server_default="issue"),
    )

    conn = op.get_bind()

    conn.execute(
        sa.text("UPDATE issues SET id = REPLACE(id, '#', '/issue/')"),
    )
    conn.execute(
        sa.text("UPDATE votes SET issue_id = REPLACE(issue_id, '#', '/issue/')"),
    )

    conn.execute(
        sa.text(
            "UPDATE audit_log SET action = json_set("
            "  action,"
            "  '$.issue_id',"
            "  REPLACE(json_extract(action, '$.issue_id'), '#', '/issue/')"
            ") WHERE json_extract(action, '$.issue_id') IS NOT NULL",
        ),
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            "UPDATE audit_log SET action = json_set("
            "  action,"
            "  '$.issue_id',"
            "  REPLACE(json_extract(action, '$.issue_id'), '/issue/', '#')"
            ") WHERE json_extract(action, '$.issue_id') IS NOT NULL",
        ),
    )

    conn.execute(
        sa.text("UPDATE votes SET issue_id = REPLACE(issue_id, '/issue/', '#')"),
    )
    conn.execute(
        sa.text("UPDATE issues SET id = REPLACE(id, '/issue/', '#')"),
    )

    op.drop_column("issues", "type")
