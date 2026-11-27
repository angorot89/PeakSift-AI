"""allow creator caption styles

Revision ID: 67c10e35281d
Revises: d94fe67e5719
Create Date: 2026-11-28 01:39:28.935829

The dynamic renderer gains ten creator caption styles (V2.0). The check on ``clip_edits``
widens to accept their names; earlier rows are untouched. Downgrading is refused while any
edit uses one of the new styles (it would no longer satisfy the old check).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "67c10e35281d"
down_revision: str | Sequence[str] | None = "d94fe67e5719"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORIGINAL = "'focus', 'punch', 'minimal', 'boxed'"
CREATOR = (
    "'pop', 'comic', 'bubble', 'one_word', 'neon', 'underline', 'reveal', 'headline', "
    "'marker', 'bold_arabic'"
)


def captions_check(dynamic: str) -> str:
    return (
        "(captions_enabled AND caption_style IS NOT NULL AND caption_position IS NOT NULL "
        "AND caption_position IN ('top', 'center', 'bottom') AND caption_renderer IS NOT NULL "
        "AND ((caption_renderer = 'caption_v1' "
        "AND caption_style IN ('clean', 'bold', 'creator')) "
        "OR (caption_renderer = 'caption_v2' "
        f"AND caption_style IN ({dynamic})))) "
        "OR (NOT captions_enabled AND caption_style IS NULL AND caption_position IS NULL "
        "AND caption_renderer IS NULL)"
    )


def upgrade() -> None:
    op.drop_constraint("ck_clip_edits_captions", "clip_edits", type_="check")
    op.create_check_constraint(
        "ck_clip_edits_captions", "clip_edits", captions_check(f"{ORIGINAL}, {CREATOR}")
    )


def downgrade() -> None:
    op.drop_constraint("ck_clip_edits_captions", "clip_edits", type_="check")
    op.create_check_constraint("ck_clip_edits_captions", "clip_edits", captions_check(ORIGINAL))
