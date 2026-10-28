"""Brand Studio (V1.7): the creator's brands and the images they may use as a logo.

``/brand/profiles`` lists, creates, reads, changes and deletes the current creator's brands
(another creator's brand is a ``404``); ``is_default`` makes one brand the default (the
previous default is cleared). ``GET /brand/logo-candidates`` lists the creator's image visual
assets across their projects — logos reuse the private visual library, never a separate
upload or storage. Brands are preferences: no render reads them; a Short copies the values it
uses into its own configuration snapshot.
"""

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import BrandProfile, Project, VisualAsset
from app.schemas.brand import BrandCreate, BrandRead, BrandUpdate, LogoRead
from app.services.branding import profiles
from app.services.branding.colors import emphasis_readable
from app.services.branding.profiles import BrandProblem

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
