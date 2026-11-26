"""instagram as a publishing platform

Revision ID: b3a396425b66
Revises: d737b1867417
Create Date: 2026-11-26 23:25:38.668770

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3a396425b66"
down_revision: str | Sequence[str] | None = "d737b1867417"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_PROVIDERS = "provider IN ('youtube', 'tiktok')"
NEW_PROVIDERS = "provider IN ('youtube', 'tiktok', 'instagram')"
TABLES = (
    ("publishing_connections", "ck_publishing_connections_provider"),
    ("oauth_states", "ck_oauth_states_provider"),
    ("publish_jobs", "ck_publish_jobs_provider"),
)


def upgrade() -> None:
    for table, name in TABLES:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, NEW_PROVIDERS)


def downgrade() -> None:
    # Rows of a platform the old schema does not know cannot stay (their tokens go with them).
    for table, _ in reversed(TABLES):
        op.execute(f"DELETE FROM {table} WHERE provider = 'instagram'")
    for table, name in TABLES:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, OLD_PROVIDERS)
