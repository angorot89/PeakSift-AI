"""add dynamic caption fields to clip edits

Revision ID: 74ae696aa9c9
Revises: b456f3fe948d
Create Date: 2026-10-14 15:25:09.707690

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "74ae696aa9c9"
down_revision: str | Sequence[str] | None = "b456f3fe948d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_CAPTIONS = (
    "(captions_enabled AND caption_style IS NOT NULL AND caption_position IS NOT NULL "
    "AND caption_style IN ('clean', 'bold', 'creator') "
    "AND caption_position IN ('top', 'center', 'bottom')) "
    "OR (NOT captions_enabled AND caption_style IS NULL AND caption_position IS NULL)"
)
NEW_CAPTIONS = (
    "(captions_enabled AND caption_style IS NOT NULL AND caption_position IS NOT NULL "
    "AND caption_position IN ('top', 'center', 'bottom') AND caption_renderer IS NOT NULL "
    "AND ((caption_renderer = 'caption_v1' "
    "AND caption_style IN ('clean', 'bold', 'creator')) "
    "OR (caption_renderer = 'caption_v2' "
    "AND caption_style IN ('focus', 'punch', 'minimal', 'boxed')))) "
    "OR (NOT captions_enabled AND caption_style IS NULL AND caption_position IS NULL "
    "AND caption_renderer IS NULL)"
)
CAPTION_TIMING = (
    "(caption_renderer = 'caption_v2' AND caption_timing IS NOT NULL "
    "AND caption_timing IN ('aligned_word', 'phrase_fallback') "
    "AND (caption_timing = 'aligned_word') = (caption_track_id IS NOT NULL)) "
    "OR (caption_renderer IS DISTINCT FROM 'caption_v2' "
    "AND caption_timing IS NULL AND caption_track_id IS NULL)"
)


OLD_HOOK = (
    "(hook_enabled AND hook_text IS NOT NULL AND length(hook_text) BETWEEN 1 AND 60 "
    "AND hook_style IN ('headline', 'boxed', 'minimal') "
    "AND hook_position IN ('top', 'center') "
    "AND hook_duration_seconds >= 0.5 AND hook_duration_seconds <= 5) "
    "OR (NOT hook_enabled AND hook_text IS NULL AND hook_style IS NULL "
    "AND hook_position IS NULL AND hook_duration_seconds IS NULL)"
)
# The previous hook check let a NULL style/position/duration through (a CHECK that evaluates
# to NULL accepts the row); every term is now explicit.
NEW_HOOK = (
    "(hook_enabled AND hook_text IS NOT NULL AND length(hook_text) BETWEEN 1 AND 60 "
    "AND hook_style IS NOT NULL AND hook_style IN ('headline', 'boxed', 'minimal') "
    "AND hook_position IS NOT NULL AND hook_position IN ('top', 'center') "
    "AND hook_duration_seconds IS NOT NULL "
    "AND hook_duration_seconds >= 0.5 AND hook_duration_seconds <= 5) "
    "OR (NOT hook_enabled AND hook_text IS NULL AND hook_style IS NULL "
    "AND hook_position IS NULL AND hook_duration_seconds IS NULL)"
)


def upgrade() -> None:
    op.add_column("clip_edits", sa.Column("caption_renderer", sa.String(length=16), nullable=True))
    op.add_column("clip_edits", sa.Column("caption_timing", sa.String(length=16), nullable=True))
    op.add_column("clip_edits", sa.Column("caption_track_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_clip_edits_caption_track_id"), "clip_edits", ["caption_track_id"], unique=False
    )
    op.create_foreign_key(
        "clip_edits_caption_track_id_fkey",
        "clip_edits",
        "caption_tracks",
        ["caption_track_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Every existing captioned edit was rendered by the V0.6 phrase renderer: say so explicitly.
    op.execute("UPDATE clip_edits SET caption_renderer = 'caption_v1' WHERE captions_enabled")
    op.drop_constraint("ck_clip_edits_captions", "clip_edits", type_="check")
    op.create_check_constraint("ck_clip_edits_captions", "clip_edits", NEW_CAPTIONS)
    op.create_check_constraint("ck_clip_edits_caption_timing", "clip_edits", CAPTION_TIMING)
    op.drop_constraint("ck_clip_edits_hook", "clip_edits", type_="check")
    op.create_check_constraint("ck_clip_edits_hook", "clip_edits", NEW_HOOK)


def downgrade() -> None:
    # Dynamic-caption edits cannot be represented by the V0.6 schema; they are removed.
    op.execute("DELETE FROM clip_edits WHERE caption_renderer = 'caption_v2'")
    op.drop_constraint("ck_clip_edits_hook", "clip_edits", type_="check")
    op.create_check_constraint("ck_clip_edits_hook", "clip_edits", OLD_HOOK)
    op.drop_constraint("ck_clip_edits_caption_timing", "clip_edits", type_="check")
    op.drop_constraint("ck_clip_edits_captions", "clip_edits", type_="check")
    op.create_check_constraint("ck_clip_edits_captions", "clip_edits", OLD_CAPTIONS)
    op.drop_constraint("clip_edits_caption_track_id_fkey", "clip_edits", type_="foreignkey")
    op.drop_index(op.f("ix_clip_edits_caption_track_id"), table_name="clip_edits")
    op.drop_column("clip_edits", "caption_track_id")
    op.drop_column("clip_edits", "caption_timing")
    op.drop_column("clip_edits", "caption_renderer")
