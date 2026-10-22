"""add oauth state purpose

Revision ID: 8f09d8c38851
Revises: bfcd25b63775
Create Date: 2026-10-22 10:35:32.555515

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f09d8c38851"
down_revision: str | Sequence[str] | None = "bfcd25b63775"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pending states from before the upgrade were all publishing connections.
    op.add_column(
        "oauth_states",
        sa.Column("purpose", sa.String(length=16), server_default="publishing", nullable=False),
    )
    op.create_check_constraint(
        "ck_oauth_states_purpose", "oauth_states", "purpose IN ('publishing', 'analytics')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_oauth_states_purpose", "oauth_states", type_="check")
    op.drop_column("oauth_states", "purpose")
