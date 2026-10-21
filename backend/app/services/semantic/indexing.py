"""Semantic indexing of one visual asset: requesting it, running it, and its attempt ownership.

The ``visual_semantic_indexes`` row is the source of truth; these helpers are the only way the
API and the indexing job change it.

- **Requesting** (``request_index``): one row per asset and *current* model identity. A ready
  index is reused; a live one is not started twice; a failed (or stalled) one is reset for a
  new attempt only when retrying, and attempts are bounded. The task id is generated and
  committed on the row *before* the job is enqueued (the fencing token).
- **Running** (``run_semantic_index``): only ids travel through the broker. The job fetches the
  asset through the ``StorageProvider`` into this attempt's own workspace, decodes it safely,
  makes canonical pixels (``images.canonical_rgb``), embeds them in bounded batches and stores
  the validated unit vectors and ``ready`` in **one commit**. Progress is real: embeddings
  computed out of the frames selected.
- **Reuse:** when the same owner already has an identical file (same sha256) indexed by the
  same model, its vectors are copied instead of running the model (``reused``). Vectors never
  cross an ownership boundary.
- **Ownership:** every commit re-reads the token, so a stalled worker that a retry took over
  never writes again; an index or asset deleted mid-run stops the job.
- **Failure** never touches the asset: it stays fully usable by hand, and the index records a
  safe code and message (no paths, model locations or internals).
"""

import logging
import uuid
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError, StaleDataError

from app.core.config import Settings, get_settings
from app.models import (
    AssetEmbedding,
    Project,
    SemanticIndexStatus,
    VisualAsset,
    VisualAssetKind,
    VisualSemanticIndex,
)
from app.models.semantic import ERROR_MESSAGE_MAX_LENGTH
from app.services.semantic.contract import (
    EmbeddingFailure,
    EmbeddingUnavailable,
    VisualEmbeddingProvider,
)
from app.services.semantic.images import UnusableImage, canonical_rgb
from app.services.semantic.registry import configured_identity, get_provider
from app.services.semantic.sampling import SamplingError, sample_video
from app.services.semantic.state import EmbeddingIdentity
from app.services.semantic.vectors import InvalidVector, to_unit
from app.services.storage import (
    InvalidStorageKey,
    ObjectNotFound,
    StorageProvider,
    StorageUnavailable,
    media_storage,
)
from app.services.workspace import job_workspace

logger = logging.getLogger(__name__)


class IndexSuperseded(Exception):
    """A newer attempt owns this index (or the row is gone); stop without writing."""


class IndexingFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TooManyAttempts(Exception):
    """The index failed too often; it stays failed until an operator reindexes it."""


@dataclass(frozen=True)
class Frame:
    """Canonical pixels to embed: the whole image (``time`` None) or a video frame."""

    time: float | None
    image: Image.Image


def now() -> datetime:
    return datetime.now(UTC)


def index_config(settings: Settings) -> dict:
    """The server settings an indexing run uses (recorded on the row; never user input)."""
    return {
        "batch_size": settings.semantic_batch_size,
        "video_max_frames": settings.semantic_video_max_frames,
    }


def new_task_id() -> str:
    return str(uuid.uuid4())


# --- requesting ---------------------------------------------------------------------------------


def find_index(
    db: Session, asset: VisualAsset, identity: EmbeddingIdentity
) -> VisualSemanticIndex | None:
    return db.scalar(
        select(VisualSemanticIndex).where(
            VisualSemanticIndex.visual_asset_id == asset.id,
            VisualSemanticIndex.provider == identity.provider,
            VisualSemanticIndex.model == identity.model,
            VisualSemanticIndex.model_version == identity.model_version,
            VisualSemanticIndex.embedding_version == identity.embedding_version,
        )
    )


def request_index(
    db: Session, asset: VisualAsset, settings: Settings, *, retry: bool = False
) -> VisualSemanticIndex | None:
    """Make sure the asset has (or gets) an index by the current model.

    Returns the row when a job must be enqueued with its ``celery_task_id`` (already committed),
    or None when there is nothing to start: visual search is off, the index is ready, or one is
    already running. Raises TooManyAttempts when a retry would exceed the attempt budget.
    """
    identity = configured_identity(settings)
    if identity is None:
        return None
    index = find_index(db, asset, identity)
    if index is None:
        index = VisualSemanticIndex(
            visual_asset_id=asset.id,
            provider=identity.provider,
            model=identity.model,
            model_version=identity.model_version,
            embedding_version=identity.embedding_version,
            dimensions=identity.dimensions,
            source_sha256=asset.sha256,
            config=index_config(settings),
            status=SemanticIndexStatus.QUEUED,
            celery_task_id=new_task_id(),
        )
        try:
            db.add(index)
            db.commit()
        except IntegrityError:
            # Another request created it at the same moment (two uploads of one file, a double
            # click): that request starts the job; this one has nothing to do.
            db.rollback()
            return None
        return index
    if index.status == SemanticIndexStatus.READY:
        return None
    if index.status in (SemanticIndexStatus.QUEUED, SemanticIndexStatus.INDEXING):
        if not is_stale(index, settings):
            return None
    elif not retry:  # failed: only an explicit retry (or reindex) starts it again
        return None
    if index.attempt >= settings.semantic_max_attempts:
        raise TooManyAttempts()
    index.attempt += 1
    index.status = SemanticIndexStatus.QUEUED
    index.config = index_config(settings)
    index.error_code = index.error_message = None
    index.frames_total, index.frames_done = None, 0
    index.started_at = index.completed_at = index.heartbeat_at = None
    index.celery_task_id = new_task_id()
    db.commit()
    return index


def mark_enqueue_failed(db: Session, index: VisualSemanticIndex) -> None:
    """The broker was unreachable: the asset stays usable, the index can be retried."""
    db.rollback()
    index.status = SemanticIndexStatus.FAILED
    index.error_code = "queue_unavailable"
    index.error_message = "Visual analysis could not start; try again"
    index.completed_at = now()
    db.commit()


def is_stale(index: VisualSemanticIndex, settings: Settings, *, at: datetime | None = None) -> bool:
    """A queued or running index whose worker stopped reporting (a retry may take it over)."""
    if index.status not in (SemanticIndexStatus.QUEUED, SemanticIndexStatus.INDEXING):
        return False
    last = index.heartbeat_at or index.started_at or index.updated_at or index.created_at
    return ((at or now()) - last).total_seconds() > settings.semantic_stale_after_seconds


# --- ownership ----------------------------------------------------------------------------------


def key(index: VisualSemanticIndex) -> uuid.UUID:
    """The primary key without a database round trip (safe if the row was deleted)."""
    return sa_inspect(index).identity[0]


def still_owner(index: VisualSemanticIndex, db: Session, task_id: str | None) -> bool:
    with db.no_autoflush:  # read the committed token; never flush pending changes first
        row = db.execute(
            select(VisualSemanticIndex.celery_task_id).where(VisualSemanticIndex.id == key(index))
        ).first()
    if row is None:
        return False
    if task_id is None:
        return True
    return not row.celery_task_id or row.celery_task_id == task_id


def ensure_still_owner(index: VisualSemanticIndex, db: Session, task_id: str | None) -> None:
    if not still_owner(index, db, task_id):
        db.rollback()
        raise IndexSuperseded()


def heartbeat(index: VisualSemanticIndex, db: Session, task_id: str | None) -> None:
    ensure_still_owner(index, db, task_id)
    index.heartbeat_at = now()
    db.commit()


def claim(index: VisualSemanticIndex, db: Session, settings: Settings, task_id: str | None) -> bool:
    if task_id and index.celery_task_id and index.celery_task_id != task_id:
        logger.info("Semantic index %s belongs to a newer attempt; ignoring", index.id)
        return False
    if index.status == SemanticIndexStatus.READY:
        logger.info("Semantic index %s is already ready; ignoring duplicate task", index.id)
        return False
    if index.status == SemanticIndexStatus.FAILED:
        logger.info("Semantic index %s is failed; a retry must reset it first", index.id)
        return False
    if index.status == SemanticIndexStatus.INDEXING and not is_stale(index, settings):
        logger.info("Semantic index %s is already running elsewhere", index.id)
        return False
    db.execute(delete(AssetEmbedding).where(AssetEmbedding.index_id == index.id))
    index.status = SemanticIndexStatus.INDEXING
    index.started_at = index.heartbeat_at = now()
    index.completed_at = None
    index.error_code = index.error_message = None
    index.frames_total, index.frames_done = None, 0
    index.embedding_count = None
    index.reused = False
    db.commit()
    return True


def fail(
    index: VisualSemanticIndex, db: Session, code: str, message: str, *, task_id: str | None
) -> None:
    """Record a failure — unless a newer attempt took the index over (then do nothing)."""
    db.rollback()
    index_id = key(index)
    if not still_owner(index, db, task_id):
        logger.info(
            "Semantic index %s failed (%s) after being taken over; ignoring", index_id, code
        )
        return
    db.execute(delete(AssetEmbedding).where(AssetEmbedding.index_id == index_id))
    index.status = SemanticIndexStatus.FAILED
    index.error_code = code[:64]
    index.error_message = message[:ERROR_MESSAGE_MAX_LENGTH]
    index.embedding_count = None
    index.completed_at = index.heartbeat_at = now()
    db.commit()
    logger.warning("Semantic index %s failed: %s", index_id, code)


def finish(
    index: VisualSemanticIndex,
    db: Session,
    vectors: list[tuple[float | None, list[float]]],
    *,
    reused: bool,
    task_id: str | None,
) -> None:
    """Store the vectors and ``ready`` in one commit (owners only), and drop the asset's
    stale indexes (other models): they can never be compared with these vectors."""
    ensure_still_owner(index, db, task_id)
    db.execute(delete(AssetEmbedding).where(AssetEmbedding.index_id == index.id))
    db.add_all(
        AssetEmbedding(index_id=index.id, frame_index=position, frame_time=time, embedding=vector)
        for position, (time, vector) in enumerate(vectors)
    )
    db.execute(
        delete(VisualSemanticIndex).where(
            VisualSemanticIndex.visual_asset_id == index.visual_asset_id,
            VisualSemanticIndex.id != index.id,
        )
    )
    index.status = SemanticIndexStatus.READY
    index.embedding_count = len(vectors)
    index.frames_total = index.frames_done = len(vectors)
    index.reused = reused
    index.completed_at = index.heartbeat_at = now()
    try:
        db.commit()
    except (IntegrityError, StaleDataError):
        # The asset (or its project) was deleted by another process in the instant between the
        # ownership check and this commit (the row update finds nothing, or the vectors' index
        # is gone): the vectors have nothing left to describe. Stop quietly.
        db.rollback()
        if not still_owner(index, db, task_id):
            raise IndexSuperseded() from None
        raise


# --- the work -------------------------------------------------------------------------------


def reusable_vectors(
    db: Session, index: VisualSemanticIndex, asset: VisualAsset
) -> list[tuple[float | None, list[float]]] | None:
    """Vectors of an identical file of the same owner, made by the same model."""
    owner = db.scalar(select(Project.user_id).where(Project.id == asset.project_id))
    donor = db.scalar(
        select(VisualSemanticIndex)
        .join(VisualAsset, VisualAsset.id == VisualSemanticIndex.visual_asset_id)
        .join(Project, Project.id == VisualAsset.project_id)
        .where(
            Project.user_id == owner,
            VisualAsset.id != asset.id,
            VisualAsset.sha256 == asset.sha256,
            VisualAsset.kind == asset.kind,
            VisualSemanticIndex.status == SemanticIndexStatus.READY,
            VisualSemanticIndex.provider == index.provider,
            VisualSemanticIndex.model == index.model,
            VisualSemanticIndex.model_version == index.model_version,
            VisualSemanticIndex.embedding_version == index.embedding_version,
            VisualSemanticIndex.dimensions == index.dimensions,
        )
        .limit(1)
    )
    if donor is None:
        return None
    try:
        return [
            (row.frame_time, to_unit(row.embedding, index.dimensions).tolist())
            for row in donor.embeddings
        ] or None
    except InvalidVector:
        return None  # never copy a damaged vector; compute afresh


def image_frames(path: Path, settings: Settings) -> list[Frame]:
    """The stored rendition (always JPEG or PNG, already upright) as canonical pixels."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path, formats=["JPEG", "PNG"]) as opened:
                width, height = opened.size
                if width * height > settings.visual_asset_max_pixel_count:
                    raise IndexingFailure("unreadable_image", "The image is too large to analyse")
                opened.load()
                image = canonical_rgb(opened)
    except IndexingFailure:
        raise
    except UnusableImage as error:
        raise IndexingFailure("unusable_image", str(error)) from None
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
        SyntaxError,
    ):
        raise IndexingFailure("unreadable_image", "The image could not be read") from None
    return [Frame(None, image)]


def video_frames(asset: VisualAsset, path: Path, settings: Settings, work: Path) -> list[Frame]:
    """Representative frames (``sampling.sample_video``: bounded, deterministic, black and
    duplicate frames skipped), each as canonical pixels with its time in the asset."""
    try:
        sampled = sample_video(
            path,
            float(asset.duration_seconds or 0.0),
            work,
            ffmpeg_path=settings.ffmpeg_path,
            max_frames=settings.semantic_video_max_frames,
            timeout=settings.semantic_frame_timeout_seconds,
        )
        return [Frame(frame.time, canonical_rgb(frame.image)) for frame in sampled]
    except SamplingError as error:
        raise IndexingFailure(error.code, error.message) from None
    except UnusableImage as error:
        raise IndexingFailure("unusable_image", str(error)) from None


def asset_frames(asset: VisualAsset, path: Path, settings: Settings, work: Path) -> list[Frame]:
    if asset.kind == VisualAssetKind.IMAGE:
        return image_frames(path, settings)
    if asset.kind == VisualAssetKind.VIDEO:
        return video_frames(asset, path, settings, work)
    raise IndexingFailure("unsupported_kind", "Visual search does not analyse this kind")


def _execute(
    index: VisualSemanticIndex,
    db: Session,
    settings: Settings,
    storage: StorageProvider,
    provider: VisualEmbeddingProvider | None,
    task_id: str | None,
) -> None:
    asset = db.get(VisualAsset, index.visual_asset_id)
    if asset is None:
        raise IndexSuperseded()
    reused = reusable_vectors(db, index, asset)
    if reused is not None:
        finish(index, db, reused, reused=True, task_id=task_id)
        logger.info("Semantic index %s reused %d vectors", index.id, len(reused))
        return
    model = provider or get_provider(settings)
    if model.identity.key != index.identity or model.identity.dimensions != index.dimensions:
        raise IndexingFailure("model_changed", "The visual search model changed; analyse again")
    with job_workspace(settings, "semantic", index.id, task_id) as work:
        try:
            path = storage.fetch(asset.storage_key, work)
        except (ObjectNotFound, InvalidStorageKey):
            raise IndexingFailure("asset_missing", "The visual's file is missing") from None
        frames = asset_frames(asset, path, settings, work)
        if not frames:
            raise IndexingFailure("no_frames", "No usable picture was found in this visual")
        index.frames_total = len(frames)
        heartbeat(index, db, task_id)
        vectors: list[tuple[float | None, list[float]]] = []
        for start in range(0, len(frames), model.batch_size):
            batch = frames[start : start + model.batch_size]
            embedded = model.embed_images([frame.image for frame in batch])
            if len(embedded) != len(batch):
                raise EmbeddingFailure("The visual search model returned an invalid result")
            for frame, vector in zip(batch, embedded, strict=True):
                try:
                    unit = to_unit(vector, index.dimensions)
                except InvalidVector:
                    raise EmbeddingFailure(
                        "The visual search model returned an invalid result"
                    ) from None
                vectors.append((frame.time, unit.tolist()))
            index.frames_done = len(vectors)
            heartbeat(index, db, task_id)
    finish(index, db, vectors, reused=False, task_id=task_id)
    logger.info("Semantic index %s ready: %d vectors", index.id, len(vectors))


def run_semantic_index(
    index_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    storage: StorageProvider | None = None,
    provider: VisualEmbeddingProvider | None = None,
    task_id: str | None = None,
) -> VisualSemanticIndex | None:
    """Index one ``VisualSemanticIndex`` row. Problems are recorded, never raised."""
    settings = settings or get_settings()
    storage = storage or media_storage(settings)
    index = db.get(VisualSemanticIndex, index_id)
    if index is None:
        logger.info("Semantic index %s no longer exists; nothing to do", index_id)
        return None
    if not claim(index, db, settings, task_id):
        return index

    def record(code: str, message: str) -> None:
        try:
            fail(index, db, code, message, task_id=task_id)
        except Exception:
            # The database itself is failing: leave the row to go stale; a retry recovers it.
            logger.exception("Could not record the failure of semantic index %s", index_id)
            db.rollback()

    try:
        _execute(index, db, settings, storage, provider, task_id)
    except (IndexSuperseded, ObjectDeletedError):
        # ObjectDeletedError: the row vanished (asset or project deleted by another process)
        # and an expired attribute could not be reloaded — the same as being removed.
        db.rollback()
        logger.info("Semantic index %s was taken over or removed; stopping", index_id)
    except IndexingFailure as error:
        record(error.code, error.message)
    except (EmbeddingUnavailable, EmbeddingFailure) as error:
        record(error.code, error.message)
    except StorageUnavailable:
        record("storage_unavailable", "Media storage is unavailable; try again")
    except SoftTimeLimitExceeded:
        record("time_limit", "Visual analysis ran longer than the worker allows; try again")
    except Exception:
        logger.exception("Unexpected error indexing semantic index %s", index_id)
        record("internal_error", "Unexpected error while analysing the visual")
    return index
