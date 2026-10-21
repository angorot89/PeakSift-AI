"""Searching a project's visuals by what they show, combined with their names, descriptions
and tags (hybrid), with honest strength tiers instead of probabilities.

1. **Query.** The text is cleaned (control characters removed, whitespace collapsed, at most
   ``MAX_QUERY_CHARS``) and embedded once by the current model's text encoder, inside the
   model's prompt template ("a photo of …"); vectors are cached per process (bounded LRU).
2. **Visual similarity.** One exact SQL scan over *this project's* ready vectors of the
   *current* model (pgvector cosine distance), keeping each asset's best frame:
   ``DISTINCT ON (asset) … ORDER BY asset, distance``. The asset's score is the **maximum**
   similarity over its frames, so a short relevant scene of a longer video is not averaged
   away; that frame's time is ``best_frame_time``. Vectors never leave the database.
3. **Metadata.** The V1.1 word matcher (``broll.matching.match_score``: tags, then the name,
   then the description) still counts — an exact tag remains useful even without a model.
4. **Tiers.** Each signal has two cut-offs: visual similarity against the model's calibrated
   ``Thresholds`` (versioned per model; see docs/semantic-assets.md for the benchmark), and
   metadata coverage against the V1.1 levels (0.9 strong, 0.5 possible). An asset's strength is
   the better of the two; below both it is not a match at all. **Strong** may be placed
   automatically (Auto Edit); **possible** is only offered to the creator.
5. **Order.** Strong before possible; within a tier by a combined score — the better signal,
   scaled to 0.5–1 between its cut-offs, plus a small bonus when both signals agree — then raw
   similarity, then the newest asset.

Scores are ranking signals only. They are not probabilities and are never shown as
percentages.
"""

import logging
import re
import threading
import unicodedata
import uuid
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.models import AssetEmbedding, SemanticIndexStatus, VisualAsset, VisualSemanticIndex
from app.services.broll.matching import MIN_SCORE, AssetTerms, match_score
from app.services.semantic.contract import VisualEmbeddingProvider
from app.services.semantic.state import EmbeddingIdentity

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 100
METADATA_STRONG = 0.9
METADATA_POSSIBLE = MIN_SCORE
AGREEMENT_BONUS = 0.1
QUERY_CACHE_SIZE = 512


class Strength(StrEnum):
    STRONG = "strong"
    POSSIBLE = "possible"


class MatchMethod(StrEnum):
    VISUAL = "visual"  # what the image or video shows
    METADATA = "metadata"  # its name, description or tags
    BOTH = "visual_and_metadata"


_RANK = {Strength.STRONG: 2, Strength.POSSIBLE: 1}


@dataclass(frozen=True)
class Thresholds:
    """Calibrated cut-offs of one model's cosine similarity (text query ↔ picture)."""

    strong: float
    possible: float
    prompt: str  # how a query is phrased for the text encoder
    version: str


@dataclass(frozen=True)
class VisualScore:
    similarity: float
    best_frame_time: float | None


@dataclass(frozen=True)
class AssetMatch:
    asset: VisualAsset
    strength: Strength
    method: MatchMethod
    similarity: float | None  # internal ranking signal; never shown as a percentage
    metadata_score: float
    combined_score: float
    best_frame_time: float | None


def clean_query(text: str) -> str:
    """Printable text, single spaces, bounded. Empty when nothing searchable remains."""
    text = unicodedata.normalize("NFC", text or "")
    text = "".join(ch if unicodedata.category(ch)[0] != "C" else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()[:MAX_QUERY_CHARS].strip()


class QueryCache:
    """A bounded per-process LRU of query vectors, keyed by model identity and prompt text."""

    def __init__(self, size: int = QUERY_CACHE_SIZE) -> None:
        self.size = size
        self._items: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()

    def vector(self, provider: VisualEmbeddingProvider, prompt: str) -> np.ndarray:
        key = (provider.identity.key, prompt)
        with self._lock:
            cached = self._items.get(key)
            if cached is not None:
                self._items.move_to_end(key)
                return cached
        vector = provider.embed_text(prompt)  # outside the lock: may load the text encoder
        with self._lock:
            self._items[key] = vector
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)
        return vector

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


QUERY_CACHE = QueryCache()


def query_vector(
    provider: VisualEmbeddingProvider, thresholds: Thresholds, query: str
) -> np.ndarray:
    return QUERY_CACHE.vector(provider, thresholds.prompt.format(query=query))


def visual_scores(
    db: Session,
    project_id: uuid.UUID,
    identity: EmbeddingIdentity,
    vector: np.ndarray,
    *,
    asset_ids: Sequence[uuid.UUID] | None = None,
) -> dict[uuid.UUID, VisualScore]:
    """Each indexed asset's best frame similarity (current model, this project only)."""
    distance = AssetEmbedding.embedding.cosine_distance(vector.astype(np.float32).tolist())
    statement = (
        select(VisualSemanticIndex.visual_asset_id, AssetEmbedding.frame_time, distance)
        .join(AssetEmbedding, AssetEmbedding.index_id == VisualSemanticIndex.id)
        .join(VisualAsset, VisualAsset.id == VisualSemanticIndex.visual_asset_id)
        .where(
            VisualAsset.project_id == project_id,
            VisualSemanticIndex.status == SemanticIndexStatus.READY,
            VisualSemanticIndex.provider == identity.provider,
            VisualSemanticIndex.model == identity.model,
            VisualSemanticIndex.model_version == identity.model_version,
            VisualSemanticIndex.embedding_version == identity.embedding_version,
            VisualSemanticIndex.dimensions == identity.dimensions,
        )
        .order_by(VisualSemanticIndex.visual_asset_id, distance, AssetEmbedding.frame_index)
        .ext(distinct_on(VisualSemanticIndex.visual_asset_id))
    )
    if asset_ids is not None:
        statement = statement.where(VisualAsset.id.in_(list(asset_ids)))
    scores: dict[uuid.UUID, VisualScore] = {}
    for asset_id, frame_time, value in db.execute(statement):
        similarity = 1.0 - float(value)
        if np.isfinite(similarity):
            scores[asset_id] = VisualScore(round(similarity, 6), frame_time)
    return scores


def _visual_tier(similarity: float | None, thresholds: Thresholds) -> Strength | None:
    if similarity is None:
        return None
    if similarity >= thresholds.strong:
        return Strength.STRONG
    if similarity >= thresholds.possible:
        return Strength.POSSIBLE
    return None


def _metadata_tier(score: float) -> Strength | None:
    if score >= METADATA_STRONG:
        return Strength.STRONG
    if score >= METADATA_POSSIBLE:
        return Strength.POSSIBLE
    return None


def _scaled(value: float, low: float, high: float) -> float:
    """0 below ``low``; 0.5 at ``low`` rising to 1 at ``high`` and above."""
    if value < low:
        return 0.0
    return 0.5 + 0.5 * min(1.0, (value - low) / max(high - low, 1e-9))


def rank_assets(
    query: str,
    assets: Iterable[VisualAsset],
    visual: dict[uuid.UUID, VisualScore],
    thresholds: Thresholds | None,
) -> list[AssetMatch]:
    """Hybrid matches for ``query`` among ``assets``, strongest first (non-matches left out)."""
    matches: list[AssetMatch] = []
    for asset in assets:
        score = visual.get(asset.id) if thresholds is not None else None
        similarity = score.similarity if score else None
        metadata = match_score(query, AssetTerms.of(asset))
        visual_tier = _visual_tier(similarity, thresholds) if thresholds else None
        metadata_tier = _metadata_tier(metadata)
        tiers = [t for t in (visual_tier, metadata_tier) if t is not None]
        if not tiers:
            continue
        strength = max(tiers, key=_RANK.__getitem__)
        if visual_tier and metadata_tier:
            method = MatchMethod.BOTH
        else:
            method = MatchMethod.VISUAL if visual_tier else MatchMethod.METADATA
        v = (
            _scaled(similarity, thresholds.possible, thresholds.strong)
            if similarity is not None and thresholds
            else 0.0
        )
        m = _scaled(metadata, METADATA_POSSIBLE, METADATA_STRONG)
        combined = round(max(v, m) + AGREEMENT_BONUS * min(v, m), 4)
        best = score.best_frame_time if visual_tier and score else None
        matches.append(AssetMatch(asset, strength, method, similarity, metadata, combined, best))
    matches.sort(
        key=lambda match: (
            -_RANK[match.strength],
            -match.combined_score,
            -(match.similarity or 0.0),
            -(match.asset.created_at.timestamp() if match.asset.created_at else 0.0),
            str(match.asset.id),
        )
    )
    return matches


# --- thresholds (versioned per model) ------------------------------------------------------------

# Calibrated on the semantic benchmark (scripts/semantic_benchmark.py; docs/semantic-assets.md).
# They belong to one model identity: a different model gets its own entry, never these numbers.
THRESHOLDS: dict[tuple[str, str, str, str], Thresholds] = {}


def register_thresholds(identity: EmbeddingIdentity, thresholds: Thresholds) -> None:
    THRESHOLDS[identity.key] = thresholds


def thresholds_for(identity: EmbeddingIdentity | None) -> Thresholds | None:
    return THRESHOLDS.get(identity.key) if identity is not None else None


def _register_known() -> None:
    from app.services.semantic.clip_onnx import CLIP_IDENTITY
    from app.services.semantic.fake import FAKE_IDENTITY

    register_thresholds(
        CLIP_IDENTITY,
        Thresholds(strong=0.26, possible=0.225, prompt="a photo of {query}", version="clip-b32-v1"),
    )
    register_thresholds(
        FAKE_IDENTITY, Thresholds(strong=0.6, possible=0.4, prompt="{query}", version="fake-v1")
    )


_register_known()


# --- searching a project -----------------------------------------------------------------------


@dataclass(frozen=True)
class SearchOutcome:
    matches: list[AssetMatch]
    visual_used: bool  # visual similarity took part (else names, descriptions and tags only)
    preparing: int  # assets not yet searchable by what they show (queued, indexing, stale…)


PREPARING_STATES = ("not_indexed", "queued", "indexing", "stale")


def search_project(
    db: Session,
    project_id: uuid.UUID,
    query: str,
    settings: "Settings",
    *,
    kind: str | None = None,
    limit: int = 20,
) -> SearchOutcome:
    """Hybrid search of one project's visuals. Never raises for the model: without it, names,
    descriptions and tags still match (``visual_used`` False)."""
    from sqlalchemy.orm import selectinload

    from app.services.semantic.contract import EmbeddingFailure, EmbeddingUnavailable
    from app.services.semantic.registry import configured_identity, get_provider
    from app.services.semantic.state import semantic_state

    statement = (
        select(VisualAsset)
        .options(selectinload(VisualAsset.semantic_indexes))
        .where(VisualAsset.project_id == project_id)
        .order_by(VisualAsset.created_at.desc(), VisualAsset.id)
    )
    if kind is not None:
        statement = statement.where(VisualAsset.kind == kind)
    assets = list(db.scalars(statement))
    identity = configured_identity(settings)
    thresholds = thresholds_for(identity)
    states = [semantic_state(asset.semantic_indexes, identity).value for asset in assets]
    preparing = sum(state in PREPARING_STATES for state in states) if identity else 0
    visual: dict[uuid.UUID, VisualScore] = {}
    used = False
    if identity is not None and thresholds is not None and "ready" in states:
        try:
            provider = get_provider(settings)
            if provider.identity.key == identity.key:
                vector = query_vector(provider, thresholds, query)
                visual = visual_scores(db, project_id, identity, vector)
                used = True
        except (EmbeddingUnavailable, EmbeddingFailure) as error:
            logger.warning("Visual search query fell back to metadata: %s", error.code)
    matches = rank_assets(query, assets, visual, thresholds if used else None)
    return SearchOutcome(matches[:limit], used, preparing)
