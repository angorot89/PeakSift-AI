"""add markets to users and projects

Revision ID: abea417ec2cf
Revises: b19e475f5c92
Create Date: 2026-11-11 17:48:54.368098

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "abea417ec2cf"
down_revision: str | Sequence[str] | None = "b19e475f5c92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Markets (V1.8): a creator's default market, and each project's market and content
    language. Existing rows become Global, language detected — nothing changes for them."""
    op.add_column(
        "projects",
        sa.Column("market", sa.String(length=8), server_default="global", nullable=False),
    )
    op.add_column(
        "projects",
        sa.Column("content_language", sa.String(length=16), server_default="auto", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("default_market", sa.String(length=8), server_default="global", nullable=False),
    )
    op.create_check_constraint("ck_projects_market", "projects", "market IN ('global', 'ma')")
    op.create_check_constraint(
        "ck_projects_content_language",
        "projects",
        "content_language IN ('auto', 'darija', 'arabic', 'french', 'english', 'mixed')",
    )
    op.create_check_constraint(
        "ck_users_default_market", "users", "default_market IN ('global', 'ma')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_default_market", "users", type_="check")
    op.drop_constraint("ck_projects_content_language", "projects", type_="check")
    op.drop_constraint("ck_projects_market", "projects", type_="check")
    op.drop_column("users", "default_market")
    op.drop_column("projects", "content_language")
    op.drop_column("projects", "market")
