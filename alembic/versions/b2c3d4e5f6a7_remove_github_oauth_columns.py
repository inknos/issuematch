"""Remove github_id and access_token from users, add unique on username.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-31
"""

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("users_github_id_key", "users", type_="unique")
    op.drop_column("users", "github_id")
    op.drop_column("users", "access_token")
    op.create_unique_constraint("uq_users_username", "users", ["username"])


def downgrade() -> None:
    op.drop_constraint("uq_users_username", "users", type_="unique")
    import sqlalchemy as sa

    op.add_column("users", sa.Column("access_token", sa.String(), nullable=True))
    op.add_column("users", sa.Column("github_id", sa.Integer(), nullable=True))
    op.create_unique_constraint("users_github_id_key", "users", ["github_id"])
