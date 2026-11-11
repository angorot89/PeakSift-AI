"""add labels to visual and audio assets

Revision ID: e74b14c298a8
Revises: d8e285e1683f
Create Date: 2026-11-11 20:12:13.671816

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e74b14c298a8"
down_revision: str | Sequence[str] | None = "d8e285e1683f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES = ("visual_assets", "audio_assets")


def upgrade() -> None:
    """Asset labels (V1.8): origin, licence note, market, category, location. Existing assets
    are the creator's own uploads, Global, without category or location."""
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "origin", sa.String(length=16), server_default="creator_upload", nullable=False
            ),
        )
        op.add_column(table, sa.Column("license_note", sa.String(length=300), nullable=True))
        op.add_column(
            table,
            sa.Column("market", sa.String(length=8), server_default="global", nullable=False),
        )
        op.add_column(table, sa.Column("category", sa.String(length=32), nullable=True))
        op.add_column(table, sa.Column("location", sa.String(length=32), nullable=True))
        op.create_check_constraint(
            f"ck_{table}_origin",
            table,
            "origin IN ('creator_upload', 'company_owned', 'licensed', 'public_domain', 'cc0')",
        )
        op.create_check_constraint(
            f"ck_{table}_license_note",
            table,
            "origin <> 'licensed' OR (license_note IS NOT NULL AND length(license_note) > 0)",
        )
        op.create_check_constraint(f"ck_{table}_market", table, "market IN ('global', 'ma')")


def downgrade() -> None:
    for table in TABLES:
        for name in ("market", "license_note", "origin"):
            op.drop_constraint(f"ck_{table}_{name}", table, type_="check")
        for column in ("location", "category", "market", "license_note", "origin"):
            op.drop_column(table, column)
