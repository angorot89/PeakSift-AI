"""allow transparent video assets

Revision ID: 30fe737ec12c
Revises: 67c10e35281d
Create Date: 2026-11-28

A VP8/VP9 WebM may carry an alpha channel (the starter library's animated overlays, or a
creator's own): such a video asset records ``has_alpha``. Every other video stays opaque.
Downgrading is refused while a transparent video exists (it would break the old check).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "30fe737ec12c"
down_revision: str | Sequence[str] | None = "67c10e35281d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMAGE = "(kind = 'image' AND duration_seconds IS NULL AND fps IS NULL AND NOT has_audio) "
VIDEO = (
    "OR (kind = 'video' AND duration_seconds IS NOT NULL AND duration_seconds > 0 "
    "AND (fps IS NULL OR fps > 0) "
)


def upgrade() -> None:
    op.drop_constraint("ck_visual_assets_kind_metadata", "visual_assets", type_="check")
    op.create_check_constraint(
        "ck_visual_assets_kind_metadata",
        "visual_assets",
        IMAGE + VIDEO + "AND (NOT has_alpha OR codec IN ('vp8', 'vp9')))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_visual_assets_kind_metadata", "visual_assets", type_="check")
    op.create_check_constraint(
        "ck_visual_assets_kind_metadata", "visual_assets", IMAGE + VIDEO + "AND NOT has_alpha)"
    )
