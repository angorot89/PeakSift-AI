"""Markets (V1.8).

- ``GET /markets`` — the markets PeakSift offers, the content languages a project can be in,
  and the labels an asset can carry (origins, categories). The same for every signed-in creator.
- ``GET /markets/{code}/assets?kind=visual|audio`` — the creator's own assets marked local to
  that market, across their projects (the Creator Kit). Owner-scoped: never another creator's.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import AudioAsset, Project, VisualAsset
from app.services import asset_labels, markets

router = APIRouter(prefix="/markets", tags=["markets"])
KIT_LIMIT = 200


def _labels(mapping: dict[str, str]) -> list[dict[str, str]]:
    return [{"code": code, "label": label} for code, label in mapping.items()]


@router.get("")
def list_markets(current_user: CurrentUser) -> dict:
    return {
        "markets": [profile.read() for profile in markets.MARKETS.values()],
        "content_languages": _labels(markets.CONTENT_LANGUAGES),
        "asset_origins": _labels(asset_labels.ORIGINS),
        "visual_categories": _labels(asset_labels.VISUAL_CATEGORIES),
        "audio_categories": _labels(asset_labels.AUDIO_CATEGORIES),
    }


@router.get("/{code}/assets")
def local_assets(
    code: str,
    current_user: CurrentUser,
    db: DbSession,
    kind: Annotated[Literal["visual", "audio"], Query()] = "visual",
) -> dict:
    try:
        profile = markets.market(code)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown market"
        ) from None
    model = VisualAsset if kind == "visual" else AudioAsset
    rows = db.execute(
        select(model, Project.name)
        .join(Project, Project.id == model.project_id)
        .where(Project.user_id == current_user.id, model.market == profile.code)
        .order_by(model.created_at.desc(), model.id)
        .limit(KIT_LIMIT)
    ).all()
    items = []
    for asset, project_name in rows:
        item = {
            "id": asset.id, "project": {"id": asset.project_id, "name": project_name},
            "kind": asset.kind, "display_name": asset.display_name,
            "duration_seconds": asset.duration_seconds, **asset_labels.read(asset),
        }  # fmt: skip
        if kind == "visual":
            item |= {"has_thumbnail": asset.thumbnail_storage_key is not None,
                     "description": asset.description, "tags": list(asset.tags or [])}  # fmt: skip
        items.append(item)
    return {"market": profile.code, "kind": kind, "assets": items}
