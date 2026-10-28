"""Brand Studio (V1.7): the creator's brands, Short templates and the images a logo may use.

``/brand/profiles`` lists, creates, reads, changes and deletes the current creator's brands
(another creator's brand is a ``404``); ``is_default`` makes one brand the default (the
previous default is cleared). ``GET /brand/logo-candidates`` lists the creator's image visual
assets across their projects — logos reuse the private visual library, never a separate
upload or storage. ``/brand/templates`` does the same for Short templates (plus
``duplicate``); ``GET /brand/template-starters`` gives Clean, Punchy, Story and Minimal as
starting settings. Brands and templates are preferences: no render reads them; a Short copies
the values it uses into its own configuration snapshot.
"""

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import BrandProfile, Project, ShortTemplate, VisualAsset
from app.schemas.brand import (
    BrandCreate,
    BrandRead,
    BrandUpdate,
    LogoRead,
    TemplateBrandRead,
    TemplateCreate,
    TemplateRead,
    TemplateStarterRead,
    TemplateUpdate,
)
from app.services.auto_edit.recipes import current_recipe
from app.services.branding import profiles, templates
from app.services.branding.colors import emphasis_readable
from app.services.branding.profiles import BrandProblem
from app.services.branding.template_config import TemplateConfig
from app.services.clip_edit.brand import layout_summary
from app.services.clip_edit.safe_area import GENERAL_SOCIAL

router = APIRouter(prefix="/brand", tags=["brand"])


def _http(problem: BrandProblem) -> HTTPException:
    return HTTPException(status_code=problem.status, detail=problem.message)


def logo_read(asset: VisualAsset | None, project_name: str | None = None) -> LogoRead | None:
    if asset is None:
        return None
    return LogoRead(
        id=asset.id,
        project_id=asset.project_id,
        project_name=project_name or asset.project.name,
        name=asset.display_name,
        width=asset.width,
        height=asset.height,
        transparent=asset.has_alpha,
        has_thumbnail=asset.has_thumbnail,
    )


def brand_read(brand: BrandProfile) -> BrandRead:
    emphasis = brand.caption_emphasis_color
    return BrandRead(
        id=brand.id,
        name=brand.name,
        is_default=brand.is_default,
        primary_color=brand.primary_color,
        secondary_color=brand.secondary_color,
        accent_color=brand.accent_color,
        caption_emphasis_color=emphasis,
        caption_emphasis_readable=emphasis_readable(emphasis) if emphasis else None,
        logo=logo_read(brand.logo),
        logo_position=brand.logo_position,
        logo_size=brand.logo_size,
        end_card_text=brand.end_card_text,
        created_at=brand.created_at,
        updated_at=brand.updated_at,
    )


@router.get("/profiles", response_model=list[BrandRead])
def list_brands(current_user: CurrentUser, db: DbSession) -> list[BrandRead]:
    return [brand_read(b) for b in profiles.brands(db, current_user)]


@router.post("/profiles", status_code=status.HTTP_201_CREATED, response_model=BrandRead)
def create_brand(body: BrandCreate, current_user: CurrentUser, db: DbSession) -> BrandRead:
    data = body.model_dump(exclude={"is_default"})
    try:
        brand = profiles.create_brand(db, current_user, data, make_default=body.is_default)
    except BrandProblem as problem:
        raise _http(problem) from None
    return brand_read(brand)


def _owned(db, user, brand_id: uuid.UUID) -> BrandProfile:
    try:
        return profiles.owned_brand(db, user, brand_id)
    except BrandProblem as problem:
        raise _http(problem) from None


@router.get("/profiles/{brand_id}", response_model=BrandRead)
def get_brand(brand_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> BrandRead:
    return brand_read(_owned(db, current_user, brand_id))


@router.patch("/profiles/{brand_id}", response_model=BrandRead)
def update_brand(
    brand_id: uuid.UUID, body: BrandUpdate, current_user: CurrentUser, db: DbSession
) -> BrandRead:
    brand = _owned(db, current_user, brand_id)
    sent = body.model_dump(exclude_unset=True)
    default = sent.pop("is_default", None)
    if "name" in sent and sent["name"] is None:
        raise HTTPException(status_code=422, detail="A brand needs a name")
    if "primary_color" in sent and sent["primary_color"] is None:
        raise HTTPException(status_code=422, detail="A brand needs a primary colour")
    try:
        if sent:
            brand = profiles.update_brand(db, current_user, brand, sent)
        if default is not None:
            brand = profiles.set_default(db, current_user, brand, default)
    except BrandProblem as problem:
        raise _http(problem) from None
    db.refresh(brand)
    return brand_read(brand)


@router.delete("/profiles/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_brand(brand_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> Response:
    profiles.delete_brand(db, _owned(db, current_user, brand_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/layout")
def brand_layout(current_user: CurrentUser) -> dict:
    """The numbers previews need to place a logo and an end card exactly like the renderer."""
    return {**layout_summary(), "margins": GENERAL_SOCIAL.px()}


@router.get("/edit-section")
def edit_section(
    current_user: CurrentUser, db: DbSession, template_id: uuid.UUID | None = None
) -> dict:
    """The brand section a Short would use now — from ``template_id``, else the default
    template, else the default brand (logo on, no end card) — and where it came from. The
    editor sends it with the edit, where it is validated again like everything else."""
    template = None
    try:
        if template_id is not None:
            template = templates.owned_template(db, current_user, template_id)
        else:
            template = templates.default_template(db, current_user)
    except BrandProblem as problem:
        raise _http(problem) from None
    if template is not None and template.brand is not None:
        config = TemplateConfig.from_snapshot(template.config)
        return {
            "brand": templates.brand_for_edit(template.brand, config),
            "template": {
                "id": str(template.id),
                "name": template.name,
                "version": template.version,
            },
        }
    brand = profiles.default_brand(db, current_user)
    return {
        "brand": templates.brand_for_edit(brand, TemplateConfig()) if brand else None,
        "template": None,
    }


@router.get("/logo-candidates", response_model=list[LogoRead])
def logo_candidates(current_user: CurrentUser, db: DbSession) -> list[LogoRead]:
    """The creator's images (any project), newest first: the logos a brand may use."""
    rows = db.execute(
        select(VisualAsset, Project.name)
        .join(Project, VisualAsset.project_id == Project.id)
        .where(Project.user_id == current_user.id, VisualAsset.kind == "image")
        .order_by(VisualAsset.created_at.desc())
        .limit(200)
    ).all()
    return [logo_read(asset, name) for asset, name in rows]


# --- Short templates -----------------------------------------------------------------------------


def template_read(template: ShortTemplate) -> TemplateRead:
    brand = template.brand
    return TemplateRead(
        id=template.id,
        name=template.name,
        description=template.description,
        recipe=template.recipe,
        brand=TemplateBrandRead(
            id=brand.id,
            name=brand.name,
            primary_color=brand.primary_color,
            has_logo=brand.logo_asset_id is not None,
        )
        if brand
        else None,
        config=template.config,
        version=template.version,
        is_default=template.is_default,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _owned_template(db, user, template_id: uuid.UUID) -> ShortTemplate:
    try:
        return templates.owned_template(db, user, template_id)
    except BrandProblem as problem:
        raise _http(problem) from None


@router.get("/template-starters", response_model=list[TemplateStarterRead])
def template_starters(current_user: CurrentUser) -> list[TemplateStarterRead]:
    """Clean, Punchy, Story and Minimal as starting points (each recipe's own defaults)."""
    out = []
    for name in templates.STARTERS:
        recipe = current_recipe(name)
        out.append(
            TemplateStarterRead(
                recipe=name,
                label=recipe.label,
                description=recipe.description,
                config=templates.starter_config(name),
            )
        )
    return out


@router.get("/templates", response_model=list[TemplateRead])
def list_templates(current_user: CurrentUser, db: DbSession) -> list[TemplateRead]:
    return [template_read(t) for t in templates.templates(db, current_user)]


@router.post("/templates", status_code=status.HTTP_201_CREATED, response_model=TemplateRead)
def create_template(body: TemplateCreate, current_user: CurrentUser, db: DbSession) -> TemplateRead:
    try:
        template = templates.create_template(db, current_user, body.model_dump())
    except BrandProblem as problem:
        raise _http(problem) from None
    return template_read(template)


@router.get("/templates/{template_id}", response_model=TemplateRead)
def get_template(template_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> TemplateRead:
    return template_read(_owned_template(db, current_user, template_id))


@router.patch("/templates/{template_id}", response_model=TemplateRead)
def update_template(
    template_id: uuid.UUID, body: TemplateUpdate, current_user: CurrentUser, db: DbSession
) -> TemplateRead:
    template = _owned_template(db, current_user, template_id)
    sent = body.model_dump(exclude_unset=True)
    if "name" in sent and sent["name"] is None:
        raise HTTPException(status_code=422, detail="A template needs a name")
    try:
        template = templates.update_template(db, current_user, template, sent)
    except BrandProblem as problem:
        raise _http(problem) from None
    db.refresh(template)
    return template_read(template)


@router.post(
    "/templates/{template_id}/duplicate",
    status_code=status.HTTP_201_CREATED,
    response_model=TemplateRead,
)
def duplicate_template(
    template_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> TemplateRead:
    template = _owned_template(db, current_user, template_id)
    try:
        return template_read(templates.duplicate_template(db, current_user, template))
    except BrandProblem as problem:
        raise _http(problem) from None


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> Response:
    templates.delete_template(db, _owned_template(db, current_user, template_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
