"""add market to short templates

Revision ID: d8e285e1683f
Revises: abea417ec2cf
Create Date: 2026-11-11 20:03:44.879403

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e285e1683f"
down_revision: str | Sequence[str] | None = "abea417ec2cf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Templates record the market they were made for (V1.8); existing ones are Global."""
    op.add_column(
        "short_templates",
        sa.Column("market", sa.String(length=8), server_default="global", nullable=False),
    )
    op.create_check_constraint(
        "ck_short_templates_market", "short_templates", "market IN ('global', 'ma')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_short_templates_market", "short_templates", type_="check")
    op.drop_column("short_templates", "market")
