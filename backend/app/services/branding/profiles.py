"""Creating, changing and choosing a creator's brands (``models/brand.py``).

Everything is scoped to the creator: another creator's brand or logo is "not found". A logo is
one of the creator's own **image** visual assets (any of their projects); uploads are
normalized by ``visual_assets.py`` (PNG when transparent, otherwise JPEG; CMYK and other modes
converted), so every image asset is a usable logo. Making a brand the default clears the
previous default in the same transaction; the partial unique index settles a race between two
requests (the loser gets a conflict). A changed brand affects only Shorts made afterwards.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BrandProfile, Project, User, VisualAsset
from app.models.brand import (
    END_CARD_TEXT_MAX_LENGTH,
    LOGO_POSITIONS,
    LOGO_SIZES,
    NAME_MAX_LENGTH,
)
from app.services.branding.colors import normalize_color, optional_color

MAX_BRANDS = 10
FIELDS = (
    "name", "primary_color", "secondary_color", "accent_color", "caption_emphasis_color",
    "logo_asset_id", "logo_position", "logo_size", "end_card_text",
)  # fmt: skip


class BrandProblem(Exception):
    """A request PeakSift refuses, with the HTTP status and a creator-facing message."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class BrandValues:
    """Validated, normalized values for a brand (``None`` clears an optional field)."""

    name: str
    primary_color: str
    secondary_color: str | None
    accent_color: str | None
    caption_emphasis_color: str | None
    logo_asset_id: uuid.UUID | None
    logo_position: str
    logo_size: str
    end_card_text: str | None


def _name(value: object) -> str:
    name = " ".join(str(value or "").split())
    if not 1 <= len(name) <= NAME_MAX_LENGTH:
        raise BrandProblem(422, f"Give the brand a name of 1–{NAME_MAX_LENGTH} characters")
    return name


def _end_card_text(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) > END_CARD_TEXT_MAX_LENGTH:
        raise BrandProblem(
            422, f"The end-card line can be at most {END_CARD_TEXT_MAX_LENGTH} characters"
        )
    return text


def owned_image(db: Session, user: User, asset_id: uuid.UUID) -> VisualAsset:
    """One of the creator's image visual assets, or 404 (another creator's is not found)."""
    asset = db.scalar(
        select(VisualAsset)
        .join(Project, VisualAsset.project_id == Project.id)
        .where(VisualAsset.id == asset_id, Project.user_id == user.id)
    )
    if asset is None:
        raise BrandProblem(404, "That logo image was not found")
    if asset.kind != "image":
        raise BrandProblem(422, "A logo must be an image (PNG, WebP or JPEG), not a video")
    return asset


def values(db: Session, user: User, data: dict, current: BrandProfile | None = None) -> BrandValues:
    """Merge ``data`` (only the fields sent) over ``current`` and validate everything."""
    merged = {f: getattr(current, f) for f in FIELDS} if current is not None else {}
    merged.update({k: v for k, v in data.items() if k in FIELDS})
    try:
        primary = normalize_color(merged.get("primary_color"))
        secondary = optional_color(merged.get("secondary_color"))
        accent = optional_color(merged.get("accent_color"))
        emphasis = optional_color(merged.get("caption_emphasis_color"))
    except ValueError as error:
        raise BrandProblem(422, str(error)) from None
    position = merged.get("logo_position") or "top_right"
    size = merged.get("logo_size") or "small"
    if position not in LOGO_POSITIONS:
        raise BrandProblem(422, "The logo goes in one of the four corners")
    if size not in LOGO_SIZES:
        raise BrandProblem(422, "The logo size is small, medium or large")
    logo = merged.get("logo_asset_id")
    if logo is not None:
        logo = owned_image(db, user, uuid.UUID(str(logo))).id
    return BrandValues(
        name=_name(merged.get("name")),
        primary_color=primary,
        secondary_color=secondary,
        accent_color=accent,
        caption_emphasis_color=emphasis,
        logo_asset_id=logo,
        logo_position=position,
        logo_size=size,
        end_card_text=_end_card_text(merged.get("end_card_text")),
    )


def brands(db: Session, user: User) -> list[BrandProfile]:
    """The creator's brands: the default first, then the most recently changed."""
    return list(
        db.scalars(
            select(BrandProfile)
            .where(BrandProfile.user_id == user.id)
            .order_by(BrandProfile.is_default.desc(), BrandProfile.updated_at.desc())
        )
    )


def owned_brand(db: Session, user: User, brand_id: uuid.UUID) -> BrandProfile:
    brand = db.scalar(
        select(BrandProfile).where(BrandProfile.id == brand_id, BrandProfile.user_id == user.id)
    )
    if brand is None:
        raise BrandProblem(404, "Brand not found")
    return brand


def default_brand(db: Session, user: User) -> BrandProfile | None:
    return db.scalar(
        select(BrandProfile).where(BrandProfile.user_id == user.id, BrandProfile.is_default)
    )


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if "uq_brand_profiles_name" in str(error.orig):
            raise BrandProblem(409, "You already have a brand with that name") from None
        raise BrandProblem(409, "Another change to your brands happened at the same time") from None


def _clear_default(db: Session, user: User, keep: uuid.UUID | None) -> None:
    db.execute(
        update(BrandProfile)
        .where(BrandProfile.user_id == user.id, BrandProfile.is_default, BrandProfile.id != keep)
        .values(is_default=False)
    )
    db.flush()


def create_brand(db: Session, user: User, data: dict, *, make_default: bool) -> BrandProfile:
    count = db.scalar(select(func.count()).where(BrandProfile.user_id == user.id)) or 0
    if count >= MAX_BRANDS:
        raise BrandProblem(409, f"You can have up to {MAX_BRANDS} brands")
    checked = values(db, user, data)
    brand = BrandProfile(user_id=user.id, **checked.__dict__)
    # The creator's first brand becomes the default unless they said otherwise.
    if make_default or count == 0:
        _clear_default(db, user, None)
        brand.is_default = True
    db.add(brand)
    _commit(db)
    return brand


def update_brand(db: Session, user: User, brand: BrandProfile, data: dict) -> BrandProfile:
    checked = values(db, user, data, current=brand)
    for field, value in checked.__dict__.items():
        setattr(brand, field, value)
    _commit(db)
    return brand


def set_default(db: Session, user: User, brand: BrandProfile, default: bool) -> BrandProfile:
    if default:
        _clear_default(db, user, brand.id)
    brand.is_default = default
    _commit(db)
    return brand


def delete_brand(db: Session, brand: BrandProfile) -> None:
    """Delete one brand. Shorts made with it keep their look (their snapshot has the values)."""
    db.delete(brand)
    db.commit()


def brands_using_logo(db: Session, asset: VisualAsset) -> list[str]:
    """Names of the brands whose logo is ``asset``."""
    return list(db.scalars(select(BrandProfile.name).where(BrandProfile.logo_asset_id == asset.id)))
