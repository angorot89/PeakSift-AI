"""add smart reframe edits

Revision ID: 6b919742ac69
Revises: b9ef0e231b3f
Create Date: 2026-10-13 23:40:14.480007

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b919742ac69"
down_revision: str | Sequence[str] | None = "b9ef0e231b3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clip_edits", sa.Column("reframe_analysis_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_clip_edits_reframe_analysis_id"),
        "clip_edits",
        ["reframe_analysis_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_clip_edits_reframe_analysis_id",
        "clip_edits",
        "reframe_analyses",
        ["reframe_analysis_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Existing rows are never smart reframes, so both checks hold for current data.
    op.drop_constraint("ck_clip_edits_layout", "clip_edits", type_="check")
    op.create_check_constraint(
        "ck_clip_edits_layout",
        "clip_edits",
        "layout IN ('center_crop', 'blur_background', 'fit', 'smart_reframe')",
    )
    op.create_check_constraint(
        "ck_clip_edits_reframe",
        "clip_edits",
        "(layout = 'smart_reframe') = (reframe_analysis_id IS NOT NULL)",
    )


def downgrade() -> None:
    # Smart-reframe edits cannot exist without the column: remove them before narrowing.
    op.execute("DELETE FROM clip_edits WHERE layout = 'smart_reframe'")
    op.drop_constraint("ck_clip_edits_reframe", "clip_edits", type_="check")
    op.drop_constraint("ck_clip_edits_layout", "clip_edits", type_="check")
    op.create_check_constraint(
        "ck_clip_edits_layout", "clip_edits", "layout IN ('center_crop', 'blur_background', 'fit')"
    )
    op.drop_constraint("fk_clip_edits_reframe_analysis_id", "clip_edits", type_="foreignkey")
    op.drop_index(op.f("ix_clip_edits_reframe_analysis_id"), table_name="clip_edits")
    op.drop_column("clip_edits", "reframe_analysis_id")
