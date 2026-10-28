"""Brand profiles (V1.7): how a creator's Shorts look.

A ``BrandProfile`` is a creator-level identity: a name, a primary colour and optional
secondary / accent colours, an optional caption emphasis colour (the colour of the word being
spoken), an optional logo — one of the creator's own private image visual assets, placed in a
corner at a fixed size — and an optional short end-card line the creator writes
("Follow for more"). Colours are stored normalized as ``#RRGGBB``.

At most one brand per creator is the default (a partial unique index). Brands are
*preferences*: a render never reads them. When a Short uses a brand, the values it uses are
copied into the edit's configuration snapshot (``clip_edit/config.py``), so changing or
deleting a brand later never changes an earlier Short. Deleting the creator deletes their
brands; deleting the logo's project only clears the logo (``ON DELETE SET NULL``).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.visual_asset import VisualAsset

NAME_MAX_LENGTH = 60
END_CARD_TEXT_MAX_LENGTH = 40
COLOR_PATTERN = "^#[0-9A-F]{6}$"
LOGO_POSITIONS = ("top_left", "top_right", "bottom_left", "bottom_right")
LOGO_SIZES = ("small", "medium", "large")


def _colour_check(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IS NULL OR {column} ~ '{COLOR_PATTERN}'", name=f"ck_brand_profiles_{column}"
    )


class BrandProfile(Base):
    __tablename__ = "brand_profiles"
    __table_args__ = (
        Index(
            "uq_brand_profiles_default", "user_id", unique=True,
            postgresql_where=text("is_default"),
        ),
        Index("uq_brand_profiles_name", "user_id", "name", unique=True),
        CheckConstraint(
            f"length(name) BETWEEN 1 AND {NAME_MAX_LENGTH}", name="ck_brand_profiles_name"
        ),
        CheckConstraint(f"primary_color ~ '{COLOR_PATTERN}'", name="ck_brand_profiles_primary"),
        _colour_check("secondary_color"),
        _colour_check("accent_color"),
        _colour_check("caption_emphasis_color"),
        CheckConstraint(
            f"logo_position IN {LOGO_POSITIONS}", name="ck_brand_profiles_logo_position"
        ),
        CheckConstraint(f"logo_size IN {LOGO_SIZES}", name="ck_brand_profiles_logo_size"),
        CheckConstraint(
            f"end_card_text IS NULL OR length(end_card_text) BETWEEN 1 AND "
            f"{END_CARD_TEXT_MAX_LENGTH}",
            name="ck_brand_profiles_end_card_text",
        ),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    primary_color: Mapped[str] = mapped_column(String(7))
    secondary_color: Mapped[str | None] = mapped_column(String(7))
    accent_color: Mapped[str | None] = mapped_column(String(7))
    caption_emphasis_color: Mapped[str | None] = mapped_column(String(7))

    logo_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("visual_assets.id", ondelete="SET NULL"), index=True
    )
    logo_position: Mapped[str] = mapped_column(
        String(16), default="top_right", server_default="top_right"
    )
    logo_size: Mapped[str] = mapped_column(String(8), default="small", server_default="small")
    end_card_text: Mapped[str | None] = mapped_column(String(END_CARD_TEXT_MAX_LENGTH))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    logo: Mapped["VisualAsset | None"] = relationship()

    def __repr__(self) -> str:
        return f"BrandProfile(id={self.id!r}, name={self.name!r})"
