"""An asset's visual-search state, derived from its index rows and the server's current model.

The state is never stored on the asset (an upload's status is not overloaded): it is read
from the asset's ``VisualSemanticIndex`` rows against the *current* embedding identity —

- ``unavailable``: visual search is turned off on this server (metadata search still works);
- ``not_indexed``: no index exists for any model;
- ``queued`` / ``indexing`` / ``ready`` / ``failed``: the index made with the current model;
- ``stale``: only indexes made with another model (or representation version) exist. Their
  vectors are kept until the asset is indexed again but are never compared with new ones.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from app.models import VisualSemanticIndex


class SemanticState(StrEnum):
    UNAVAILABLE = "unavailable"
    NOT_INDEXED = "not_indexed"
    QUEUED = "queued"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"


@dataclass(frozen=True)
class EmbeddingIdentity:
    """Which model makes the vectors; vectors of different identities are never compared."""

    provider: str
    model: str
    model_version: str
    embedding_version: str
    dimensions: int

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.provider, self.model, self.model_version, self.embedding_version)

    def matches(self, index: VisualSemanticIndex) -> bool:
        return index.identity == self.key and index.dimensions == self.dimensions


def current_index(
    indexes: Iterable[VisualSemanticIndex], identity: EmbeddingIdentity | None
) -> VisualSemanticIndex | None:
    if identity is None:
        return None
    return next((index for index in indexes if identity.matches(index)), None)


def semantic_state(
    indexes: Iterable[VisualSemanticIndex], identity: EmbeddingIdentity | None
) -> SemanticState:
    rows = list(indexes)
    if identity is None:
        return SemanticState.UNAVAILABLE
    current = current_index(rows, identity)
    if current is not None:
        return SemanticState(current.status)
    return SemanticState.STALE if rows else SemanticState.NOT_INDEXED
