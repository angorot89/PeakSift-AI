"""Creating, changing, duplicating and choosing a creator's Short templates.

Owner-scoped like brands (another creator's template or brand is "not found"). Settings go
through ``TemplateConfig.create`` before they are stored. ``version`` goes up whenever the
settings, the recipe or the brand change — renaming or describing a template does not change
how Shorts are edited, so it does not. Making a template the default clears the previous
default in the same transaction (a race ends in a conflict, never two defaults).
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ShortTemplate, User
from app.models.short_template import (
    TEMPLATE_DESCRIPTION_MAX_LENGTH,
    TEMPLATE_NAME_MAX_LENGTH,
    TEMPLATE_RECIPES,
)
from app.services.auto_edit.recipes import current_recipe
from app.services.branding.profiles import BrandProblem, owned_brand
from app.services.branding.template_config import TemplateConfig

MAX_TEMPLATES = 30
STARTERS = TEMPLATE_RECIPES  # Clean, Punchy, Story, Minimal


def _name(value: object) -> str:
    name = " ".join(str(value or "").split())
    if not 1 <= len(name) <= TEMPLATE_NAME_MAX_LENGTH:
        raise BrandProblem(
            422, f"Give the template a name of 1–{TEMPLATE_NAME_MAX_LENGTH} characters"
        )
    return name


def _description(value: object) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > TEMPLATE_DESCRIPTION_MAX_LENGTH:
        raise BrandProblem(
            422, f"The description can be at most {TEMPLATE_DESCRIPTION_MAX_LENGTH} characters"
        )
    return text


def _recipe(value: object) -> str | None:
    if value is None:
        return None
    if value not in TEMPLATE_RECIPES:
        raise BrandProblem(422, "Unknown starting style")
    return str(value)


def config_of(data: object) -> dict:
    try:
        return TemplateConfig.create(data if isinstance(data, dict) else None).snapshot()
    except ValueError as error:
        raise BrandProblem(422, str(error)) from None


def starter_config(recipe: str) -> dict:
    """A template's starting settings from a recipe's own defaults."""
    return TemplateConfig.from_recipe(current_recipe(recipe)).snapshot()


def templates(db: Session, user: User) -> list[ShortTemplate]:
    """The default first, then the most recently changed."""
    return list(
        db.scalars(
            select(ShortTemplate)
            .where(ShortTemplate.user_id == user.id)
            .order_by(ShortTemplate.is_default.desc(), ShortTemplate.updated_at.desc())
        )
    )


def owned_template(db: Session, user: User, template_id: uuid.UUID) -> ShortTemplate:
    template = db.scalar(
        select(ShortTemplate).where(
            ShortTemplate.id == template_id, ShortTemplate.user_id == user.id
        )
    )
    if template is None:
        raise BrandProblem(404, "Template not found")
    return template


def default_template(db: Session, user: User) -> ShortTemplate | None:
    return db.scalar(
        select(ShortTemplate).where(ShortTemplate.user_id == user.id, ShortTemplate.is_default)
    )


def _brand_id(db: Session, user: User, value: object) -> uuid.UUID | None:
    if value is None:
        return None
    return owned_brand(db, user, uuid.UUID(str(value))).id


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if "uq_short_templates_name" in str(error.orig):
            raise BrandProblem(409, "You already have a template with that name") from None
        raise BrandProblem(
            409, "Another change to your templates happened at the same time"
        ) from None


def _clear_default(db: Session, user: User, keep: uuid.UUID | None) -> None:
    db.execute(
        update(ShortTemplate)
        .where(ShortTemplate.user_id == user.id, ShortTemplate.is_default, ShortTemplate.id != keep)
        .values(is_default=False)
    )
    db.flush()


def _count(db: Session, user: User) -> int:
    return db.scalar(select(func.count()).where(ShortTemplate.user_id == user.id)) or 0


def create_template(db: Session, user: User, data: dict) -> ShortTemplate:
    """``data``: name, description, recipe, brand_profile_id, config (or ``start_from`` a
    recipe's defaults when no config is given), is_default."""
    if _count(db, user) >= MAX_TEMPLATES:
        raise BrandProblem(409, f"You can have up to {MAX_TEMPLATES} templates")
    recipe = _recipe(data.get("recipe"))
    config = data.get("config")
    if config is None and recipe is not None:
        snapshot = starter_config(recipe)
    else:
        snapshot = config_of(config)
    template = ShortTemplate(
        user_id=user.id,
        name=_name(data.get("name")),
        description=_description(data.get("description")),
        recipe=recipe,
        brand_profile_id=_brand_id(db, user, data.get("brand_profile_id")),
        config=snapshot,
        version=1,
    )
    if data.get("is_default"):
        _clear_default(db, user, None)
        template.is_default = True
    db.add(template)
    _commit(db)
    return template


def update_template(db: Session, user: User, template: ShortTemplate, data: dict) -> ShortTemplate:
    """Only the fields sent change. Settings, recipe or brand changes make a new version."""
    changed = False
    if "name" in data:
        template.name = _name(data["name"])
    if "description" in data:
        template.description = _description(data["description"])
    if "recipe" in data:
        recipe = _recipe(data["recipe"])
        changed |= recipe != template.recipe
        template.recipe = recipe
    if "brand_profile_id" in data:
        brand = _brand_id(db, user, data["brand_profile_id"])
        changed |= brand != template.brand_profile_id
        template.brand_profile_id = brand
    if "config" in data:
        config = config_of(data["config"])
        changed |= config != template.config
        template.config = config
    if changed:
        template.version += 1
    if data.get("is_default") is True:
        _clear_default(db, user, template.id)
        template.is_default = True
    elif data.get("is_default") is False:
        template.is_default = False
    _commit(db)
    return template


def duplicate_template(db: Session, user: User, template: ShortTemplate) -> ShortTemplate:
    """A copy to experiment with ("Punchy Gaming copy"), never the default, version 1."""
    names = set(db.scalars(select(ShortTemplate.name).where(ShortTemplate.user_id == user.id)))
    base = template.name[: TEMPLATE_NAME_MAX_LENGTH - 8]
    name, n = f"{base} copy", 2
    while name in names:
        name, n = f"{base} copy {n}", n + 1
    return create_template(
        db,
        user,
        {
            "name": name,
            "description": template.description,
            "recipe": template.recipe,
            "brand_profile_id": template.brand_profile_id,
            "config": template.config,
        },
    )


def delete_template(db: Session, template: ShortTemplate) -> None:
    """Delete one template. Plans and Shorts made with it keep their settings (snapshots)."""
    db.delete(template)
    db.commit()


def brand_for_edit(brand, config: TemplateConfig) -> dict | None:
    """The brand section a Short made with ``config`` uses (``clip_edit/brand.py`` validates
    it again and drops colours that would not be readable): the logo only when the template
    shows it, the accent for a Boxed hook's label, and the end card only when turned on."""
    if brand is None:
        return None
    section: dict = {"name": brand.name}
    if config.logo and brand.logo_asset_id is not None:
        section["logo"] = {
            "asset_id": str(brand.logo_asset_id),
            "corner": brand.logo_position,
            "size": brand.logo_size,
        }
    if brand.caption_emphasis_color:
        section["caption_emphasis"] = brand.caption_emphasis_color
    section["hook_accent"] = brand.accent_color or brand.primary_color
    if config.end_card:
        section["end_card"] = {
            "seconds": config.end_card_seconds,
            "background": brand.primary_color,
            "text": brand.end_card_text,
            "show_logo": config.logo and brand.logo_asset_id is not None,
        }
    return section


def readable_config(template: ShortTemplate) -> TemplateConfig:
    """The template's settings, or a 409 asking the creator to open and save it again."""
    try:
        return TemplateConfig.from_snapshot(template.config)
    except ValueError:
        raise BrandProblem(
            409,
            f"“{template.name}” can't be used as it is; open it in Brand Studio and save it again",
        ) from None


def plan_snapshot(template: ShortTemplate) -> dict:
    """What an Auto Edit plan stores about its template: frozen at planning time, so editing
    or deleting the template (or its brand) later never changes the plan. A template whose stored
    settings this server cannot read is refused (409), never planned with half its settings."""
    config = readable_config(template)
    return {
        "id": str(template.id),
        "name": template.name,
        "version": template.version,
        "recipe": template.recipe,
        "config": config.snapshot(),
        "brand": brand_for_edit(template.brand, config),
    }
