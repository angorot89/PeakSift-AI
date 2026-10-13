"""add manual crop edits

Revision ID: 991eade4cb42
Revises: 6b919742ac69
Create Date: 2026-10-14 00:01:56.903023

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "991eade4cb42"
down_revision: str | Sequence[str] | None = "6b919742ac69"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clip_edits", sa.Column("focus_x", sa.Float(), nullable=True))
    op.add_column("clip_edits", sa.Column("focus_y", sa.Float(), nullable=True))
    op.drop_constraint("ck_clip_edits_layout", "clip_edits", type_="check")
    op.create_check_constraint(
        "ck_clip_edits_layout",
        "clip_edits",
        "layout IN ('center_crop', 'blur_background', 'fit', 'smart_reframe', 'manual_crop')",
    )
    # Existing rows are never manual crops and have no focal point: the check holds.
    op.create_check_constraint(
        "ck_clip_edits_focus",
        "clip_edits",
        "(layout = 'manual_crop' AND focus_x IS NOT NULL AND focus_y IS NOT NULL "
        "AND focus_x >= 0 AND focus_x <= 1 AND focus_y >= 0 AND focus_y <= 1) "
        "OR (layout <> 'manual_crop' AND focus_x IS NULL AND focus_y IS NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM clip_edits WHERE layout = 'manual_crop'")
    op.drop_constraint("ck_clip_edits_focus", "clip_edits", type_="check")
    op.drop_constraint("ck_clip_edits_layout", "clip_edits", type_="check")
    op.create_check_constraint(
        "ck_clip_edits_layout",
        "clip_edits",
        "layout IN ('center_crop', 'blur_background', 'fit', 'smart_reframe')",
    )
    op.drop_column("clip_edits", "focus_y")
    op.drop_column("clip_edits", "focus_x")
