"""Semantic indexing of visual assets: local embeddings of what an image or video shows.

A ``VisualSemanticIndex`` is one indexing of one ``VisualAsset`` by one embedding model. Its
*identity* is the model that produced the vectors — ``provider``, ``model``, ``model_version``
and ``embedding_version`` (PeakSift's own preprocessing/representation version) — and
``(visual_asset_id, identity)`` is unique. Vectors made by different models are never
compared: search only reads indexes whose identity equals the server's *current* one, so when
the configured model changes, every older index is recognisably **stale** (still stored,
never mixed in) until the asset is indexed again.

The index row is also the indexing job (status, attempt, fencing token, heartbeat, honest
progress: ``frames_done`` of ``frames_total`` embeddings computed). It is separate from the
asset on purpose: an asset is usable the moment its upload is validated, whether or not visual
search is ready, and a failed indexing never makes it unusable.

An ``AssetEmbedding`` is one unit-length vector of a ready index: the whole image (one row,
``frame_time`` empty) or one sampled video frame (``frame_time`` in asset seconds), so a query
can match a single scene of a longer video. Vectors live in PostgreSQL (pgvector), typed with
the model's real output dimension; they are never returned by the API or written to logs.

Search is always scoped to one project and one identity, so it is an exact scan of that
project's few vectors (btree-indexed by index and asset) rather than an approximate
nearest-neighbour index over every project: exact, isolated per project, and fast at library
sizes (see docs/semantic-assets.md for the measured latency).

Deleting an asset deletes its indexes and their embeddings (``ON DELETE CASCADE``); deleting a
project deletes its assets.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.visual_asset import VisualAsset

# The output dimension of the server's embedding model (CLIP ViT-B/32's joint image–text
# space, read from the ONNX models' output shapes; see app/services/semantic/clip_onnx.py).
# The column is typed with it, so a vector of any other length cannot be stored. A model with
# another dimension needs a migration.
EMBEDDING_DIMENSIONS = 512


class SemanticIndexStatus(StrEnum):
    QUEUED = "queued"
    INDEXING = "indexing"  # decoding the asset / sampling frames and computing embeddings
    READY = "ready"
    FAILED = "failed"


ACTIVE_SEMANTIC_INDEX_STATUSES = (SemanticIndexStatus.QUEUED, SemanticIndexStatus.INDEXING)

ERROR_MESSAGE_MAX_LENGTH = 500


class VisualSemanticIndex(Base):
    __tablename__ = "visual_semantic_indexes"
    __table_args__ = (
        UniqueConstraint(
            "visual_asset_id",
            "provider",
            "model",
            "model_version",
            "embedding_version",
            name="uq_visual_semantic_indexes_identity",
        ),
        CheckConstraint(
            "status IN ('queued', 'indexing', 'ready', 'failed')",
            name="ck_visual_semantic_indexes_status",
        ),
        CheckConstraint("attempt >= 1", name="ck_visual_semantic_indexes_attempt"),
        CheckConstraint("dimensions > 0", name="ck_visual_semantic_indexes_dimensions"),
        CheckConstraint("length(source_sha256) = 64", name="ck_visual_semantic_indexes_sha256"),
        CheckConstraint(
            "frames_done >= 0 AND (frames_total IS NULL OR "
            "(frames_total >= 0 AND frames_done <= frames_total))",
            name="ck_visual_semantic_indexes_progress",
        ),
        # A ready index has vectors and a completion time; a failed one says why.
        CheckConstraint(
            "status <> 'ready' OR (embedding_count >= 1 AND completed_at IS NOT NULL)",
            name="ck_visual_semantic_indexes_ready",
        ),
        CheckConstraint(
            "status <> 'failed' OR error_code IS NOT NULL",
            name="ck_visual_semantic_indexes_failed",
        ),
        CheckConstraint(
            "embedding_count IS NULL OR embedding_count >= 0",
            name="ck_visual_semantic_indexes_count",
        ),
        # Maintenance (stale / failed scans) looks indexes up by identity and status.
        Index(
            "ix_visual_semantic_indexes_identity_status",
            "provider",
            "model",
            "model_version",
            "embedding_version",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Indexed by the identity constraint (asset first).
    visual_asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("visual_assets.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(16), default=SemanticIndexStatus.QUEUED)
    attempt: Mapped[int] = mapped_column(Integer, default=1)

    # The embedding identity: which model made (or will make) these vectors.
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    model_version: Mapped[str] = mapped_column(String(128))
    embedding_version: Mapped[str] = mapped_column(String(32))
    dimensions: Mapped[int] = mapped_column(Integer)
    # The asset file this index describes (assets never change; recorded for reuse checks).
    source_sha256: Mapped[str] = mapped_column(String(64))
    # The server's indexing settings snapshot (frame sampling bounds); never user input.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)

    # Honest progress: embeddings computed so far, of the frames selected (images: 1).
    frames_total: Mapped[int | None] = mapped_column(Integer)
    frames_done: Mapped[int] = mapped_column(Integer, default=0)
    embedding_count: Mapped[int | None] = mapped_column(Integer)
    # True when the vectors were copied from an identical file of the same owner, indexed by
    # the same model (no model run).
    reused: Mapped[bool] = mapped_column(Boolean, default=False)

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))
    # Attempt-ownership token (fencing), committed before the job is enqueued. Internal.
    celery_task_id: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    asset: Mapped["VisualAsset"] = relationship(back_populates="semantic_indexes")
    embeddings: Mapped[list["AssetEmbedding"]] = relationship(
        back_populates="index",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AssetEmbedding.frame_index",
    )

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (self.provider, self.model, self.model_version, self.embedding_version)

    def __repr__(self) -> str:
        return (
            f"VisualSemanticIndex(id={self.id!r}, asset={self.visual_asset_id!r}, "
            f"model={self.model!r}, status={self.status!r})"
        )


class AssetEmbedding(Base):
    """One unit-length embedding of a ready index: the image, or one sampled video frame."""

    __tablename__ = "visual_asset_embeddings"
    __table_args__ = (
        UniqueConstraint("index_id", "frame_index", name="uq_visual_asset_embeddings_frame"),
        CheckConstraint("frame_index >= 0", name="ck_visual_asset_embeddings_frame_index"),
        CheckConstraint(
            "frame_time IS NULL OR frame_time >= 0", name="ck_visual_asset_embeddings_frame_time"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Indexed by the frame constraint (index first).
    index_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("visual_semantic_indexes.id", ondelete="CASCADE")
    )
    frame_index: Mapped[int] = mapped_column(Integer)
    frame_time: Mapped[float | None] = mapped_column(Float)  # videos: seconds into the asset
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    index: Mapped[VisualSemanticIndex] = relationship(back_populates="embeddings")

    def __repr__(self) -> str:
        return f"AssetEmbedding(index={self.index_id!r}, frame={self.frame_index})"
