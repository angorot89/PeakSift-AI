"""Matching B-roll suggestions to the creator's own visuals: what the asset shows + its words.

V1.1 matched a suggestion's query ("toothpick bridge model") to asset names, descriptions and
tags only. V1.3 uses the same hybrid ranking as library search (``search.rank_assets``): the
current model's similarity between the query and each asset's best frame, combined with the
V1.1 word match, in **strong / possible** tiers.

- Every suggestion's query is embedded once (bounded per-process cache) and compared with this
  project's ready vectors only; vectors of another model are never compared.
- At most ``MAX_SUGGESTION_MATCHES`` matches per suggestion, strongest first; anything below
  both cut-offs is not a match.
- Without the model (turned off, preparing, unavailable) words still match, as in V1.1.
- **Strong** matches may be placed automatically by Auto Edit; **possible** ones are only
  offered. The creator can always choose any other asset.

``asset_offset`` turns a video's best matching scene into a safe playback start for a B-roll
element of a given length: centred on the scene, never before the start, never past the end
(no black tail).
"""

import logging
import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import VisualAsset
from app.services.semantic.contract import EmbeddingFailure, EmbeddingUnavailable
from app.services.semantic.registry import configured_identity, get_provider
from app.services.semantic.search import (
    AssetMatch,
    VisualScore,
    clean_query,
    query_vector,
    rank_assets,
    thresholds_for,
    visual_scores,
)

logger = logging.getLogger(__name__)

MAX_SUGGESTION_MATCHES = 3
OFFSET_DECIMALS = 2


@dataclass(frozen=True)
class QueryMatches:
    by_query: dict[str, list[AssetMatch]]  # keyed by the query as given
    visual_used: bool  # visual similarity took part (else names, descriptions, tags only)

    def get(self, query: str) -> list[AssetMatch]:
        return self.by_query.get(query, [])


def match_queries(
    db: Session,
    project_id: uuid.UUID,
    queries: Iterable[str],
    assets: Sequence[VisualAsset],
    settings: Settings,
    *,
    limit: int = MAX_SUGGESTION_MATCHES,
) -> QueryMatches:
    """Hybrid matches of each query among ``assets`` (all of one project)."""
    queries = list(dict.fromkeys(queries))
    identity = configured_identity(settings)
    thresholds = thresholds_for(identity)
    asset_ids = [asset.id for asset in assets]
    visual: dict[str, dict[uuid.UUID, VisualScore]] = {}
    used = False
    if identity is not None and thresholds is not None and assets and queries:
        try:
            provider = get_provider(settings)
            if provider.identity.key == identity.key:
                for query in queries:
                    text = clean_query(query)
                    if not text:
                        continue
                    vector = query_vector(provider, thresholds, text)
                    visual[query] = visual_scores(
                        db, project_id, identity, vector, asset_ids=asset_ids
                    )
                used = True
        except (EmbeddingUnavailable, EmbeddingFailure) as error:
            logger.warning("B-roll matching fell back to names and tags: %s", error.code)
            visual = {}
    return QueryMatches(
        {
            query: rank_assets(query, assets, visual.get(query, {}), thresholds if used else None)[
                :limit
            ]
            for query in queries
        },
        used,
    )


def asset_offset(
    best_frame_time: float | None, element_seconds: float, video_seconds: float | None
) -> float:
    """Where a B-roll element of ``element_seconds`` should start inside a video so that the
    matched scene is in the middle — clamped to ``[0, video_seconds - element_seconds]``.

    Without a usable scene time (an image, a match by words, missing numbers) or when the video
    is not longer than the element, playback starts at 0 (the element validation then decides
    whether the video can fill it at all).
    """
    values = (best_frame_time, element_seconds, video_seconds)
    if any(v is None or not math.isfinite(v) for v in values):
        return 0.0
    if element_seconds <= 0 or video_seconds <= element_seconds:
        return 0.0
    start = best_frame_time - element_seconds / 2
    latest = video_seconds - element_seconds
    scale = 10**OFFSET_DECIMALS
    # Rounded down, so rounding can never push the element past the video's end.
    return math.floor(min(max(0.0, start), latest) * scale) / scale
