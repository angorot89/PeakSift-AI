"""Checking an edit's visuals against the assets they name and the clip they decorate.

Used by the API when an edit is requested and again by the render job before anything is
drawn (an asset could have been deleted, or a snapshot written by an older version): every
referenced asset must belong to the edit's project; overlays need images; images take no
video start or loop; a video's start must lie inside it, and without loop the video must
last as long as the element; and no element may end after the clip. Messages are safe to
show and never echo values.
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import VisualAsset, VisualAssetKind
from app.services.visuals.config import VisualMode, VisualsConfig

# Rounding slack: element times are rounded to 10 ms, video durations to 1 ms.
END_TOLERANCE_SECONDS = 0.01
VIDEO_TOLERANCE_SECONDS = 0.05


class VisualsProblem(Exception):
    """An edit's visuals cannot be rendered as configured. ``status`` is the HTTP answer
    (409: an asset is not available here; 422: the configuration does not fit the asset)."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def load_visual_assets(
    db: Session, project_id: uuid.UUID, asset_ids: Iterable[str]
) -> dict[str, VisualAsset]:
    """The project's assets among ``asset_ids`` (another project's are simply absent)."""
    wanted = {uuid.UUID(asset_id) for asset_id in asset_ids}
    if not wanted:
        return {}
    rows = db.scalars(
        select(VisualAsset).where(VisualAsset.id.in_(wanted), VisualAsset.project_id == project_id)
    )
    return {str(row.id): row for row in rows}


def check_visuals(
    visuals: VisualsConfig, assets: dict[str, VisualAsset], clip_duration: float
) -> None:
    for element in visuals.elements:
        asset = assets.get(element.asset_id)
        if asset is None:
            raise VisualsProblem(
                "visual_asset_unavailable",
                "Choose visuals from this project's visual assets",
                409,
            )
        if element.end > clip_duration + END_TOLERANCE_SECONDS:
            raise VisualsProblem(
                "visual_outside_clip", "A visual ends after the end of the clip", 422
            )
        if asset.kind == VisualAssetKind.IMAGE:
            if element.asset_offset_seconds > 0 or element.loop:
                raise VisualsProblem(
                    "visual_image_options", "Images have no video start or loop", 422
                )
            continue
        if element.mode == VisualMode.OVERLAY:
            raise VisualsProblem(
                "visual_overlay_video",
                "Overlays use images; use picture-in-picture for a video",
                422,
            )
        duration = float(asset.duration_seconds or 0.0)
        if element.asset_offset_seconds >= duration:
            raise VisualsProblem(
                "visual_offset_outside", "The video start is after the end of the video", 422
            )
        if (
            not element.loop
            and element.asset_offset_seconds + element.duration > duration + VIDEO_TOLERANCE_SECONDS
        ):
            raise VisualsProblem(
                "visual_video_too_short",
                "This video is shorter than the visual: shorten the visual, start earlier in "
                "the video, or turn on loop",
                422,
            )
