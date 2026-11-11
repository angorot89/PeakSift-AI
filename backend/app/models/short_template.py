"""Short templates (V1.7): how a creator's Shorts are edited.

A ``ShortTemplate`` is a named, reusable set of editing preferences (``config``, normalized by
``branding/template_config.py``): framing, captions, the opening hook, how much B-roll, sound
levels and how the brand is used (logo, end card). It may start from an Auto Edit recipe
(``recipe``) and may use one of the creator's brands (``brand_profile_id``; deleting the brand
leaves the template without one).

``version`` increases every time the template's settings, recipe or brand change. Templates
are *preferences*: an Auto Edit plan records the template, its version and the effective
settings it used, and a rendered Short keeps the exact values in its own snapshot — so editing
or deleting a template never changes an earlier plan or Short. At most one template per
creator is the default (partial unique index).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.brand import BrandProfile

TEMPLATE_NAME_MAX_LENGTH = 60
TEMPLATE_DESCRIPTION_MAX_LENGTH = 200
TEMPLATE_RECIPES = ("clean", "punchy", "story", "minimal")


class ShortTemplate(Base):
    __tablename__ = "short_templates"
    __table_args__ = (
        Index(
            "uq_short_templates_default", "user_id", unique=True,
            postgresql_where=text("is_default"),
        ),
        Index("uq_short_templates_name", "user_id", "name", unique=True),
        CheckConstraint(
            f"length(name) BETWEEN 1 AND {TEMPLATE_NAME_MAX_LENGTH}",
            name="ck_short_templates_name",
        ),
        CheckConstraint(
            f"length(description) <= {TEMPLATE_DESCRIPTION_MAX_LENGTH}",
            name="ck_short_templates_description",
        ),
        CheckConstraint(
            f"recipe IS NULL OR recipe IN {TEMPLATE_RECIPES}", name="ck_short_templates_recipe"
        ),
        CheckConstraint("version >= 1", name="ck_short_templates_version"),
        CheckConstraint("jsonb_typeof(config) = 'object'", name="ck_short_templates_config"),
        CheckConstraint("market IN ('global', 'ma')", name="ck_short_templates_market"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    brand_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("brand_profiles.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(TEMPLATE_NAME_MAX_LENGTH))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    recipe: Mapped[str | None] = mapped_column(String(16))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # The market a template was made for (a curated Morocco format, or "global"). A label for
    # ordering and display only: every template works in every market.
    market: Mapped[str] = mapped_column(String(8), default="global", server_default="global")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    brand: Mapped["BrandProfile | None"] = relationship()

    def __repr__(self) -> str:
        return f"ShortTemplate(id={self.id!r}, name={self.name!r}, version={self.version})"
