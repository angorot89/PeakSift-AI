"""publish job privacy levels of other platforms

Revision ID: d737b1867417
Revises: 8c220f9fbbe3
Create Date: 2026-11-26 21:57:24.939729

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d737b1867417"
down_revision: str | Sequence[str] | None = "8c220f9fbbe3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_PRIVACY = "privacy IN ('private', 'unlisted', 'public')"
NEW_PRIVACY = "privacy IN ('private', 'unlisted', 'public', 'followers', 'friends')"


def upgrade() -> None:
    op.drop_constraint("ck_publish_jobs_privacy", "publish_jobs", type_="check")
    op.create_check_constraint("ck_publish_jobs_privacy", "publish_jobs", NEW_PRIVACY)


def downgrade() -> None:
    # Posts with a visibility only TikTok has cannot be described by the old schema.
    op.execute("DELETE FROM publish_jobs WHERE privacy IN ('followers', 'friends')")
    op.drop_constraint("ck_publish_jobs_privacy", "publish_jobs", type_="check")
    op.create_check_constraint("ck_publish_jobs_privacy", "publish_jobs", OLD_PRIVACY)
