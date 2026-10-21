"""The semantic index domain: model identity, typed vectors (pgvector), constraints, cascades
and the derived visual-search state (including stale indexes after a model change)."""

import math
import uuid
from datetime import UTC, datetime

import numpy as np
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DataError, IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.models import (
    EMBEDDING_DIMENSIONS,
    AssetEmbedding,
    SemanticIndexStatus,
    VisualAsset,
    VisualSemanticIndex,
)
from app.services.semantic.state import EmbeddingIdentity, SemanticState, semantic_state
from tests.test_visual_asset_model import image_fields, make_asset, make_project, video_fields

IDENTITY = EmbeddingIdentity("clip_onnx", "clip-vit-b-32", "rev-a", "semantic_v1", 512)


def unit(seed: int) -> list[float]:
    vector = np.random.default_rng(seed).standard_normal(EMBEDDING_DIMENSIONS)
    return (vector / np.linalg.norm(vector)).astype(np.float32).tolist()


def make_index(db: Session, asset: VisualAsset, **overrides) -> VisualSemanticIndex:
    fields = {
        "asset": asset,
        "provider": IDENTITY.provider,
        "model": IDENTITY.model,
        "model_version": IDENTITY.model_version,
        "embedding_version": IDENTITY.embedding_version,
        "dimensions": IDENTITY.dimensions,
        "source_sha256": asset.sha256,
        "config": {"video_max_frames": 8},
    }
    fields.update(overrides)
    index = VisualSemanticIndex(**fields)
    db.add(index)
    db.flush()
    return index


def make_ready(db: Session, asset: VisualAsset, vectors: list[list[float]], **overrides):
    index = make_index(db, asset, **overrides)
    for position, vector in enumerate(vectors):
        frame_time = None if asset.kind == "image" else 0.5 + position
        db.add(
            AssetEmbedding(
                index=index, frame_index=position, frame_time=frame_time, embedding=vector
            )
        )
    index.status = SemanticIndexStatus.READY
    index.embedding_count = len(vectors)
    index.frames_total = index.frames_done = len(vectors)
    index.completed_at = datetime.now(UTC)
    db.flush()
    return index


def test_dimension_matches_the_column_type(db_session):
    column = db_session.execute(
        text(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'visual_asset_embeddings'::regclass AND attname = 'embedding'"
        )
    ).scalar_one()
    assert column == f"vector({EMBEDDING_DIMENSIONS})"


def test_a_ready_index_stores_unit_vectors_and_cosine_works_in_sql(db_session):
    project = make_project(db_session)
    asset = make_asset(db_session, image_fields(project))
    index = make_ready(db_session, asset, [unit(1)])
    db_session.expire_all()
    stored = db_session.get(VisualSemanticIndex, index.id)
    assert stored.status == "ready" and stored.embedding_count == 1 and not stored.reused
    vector = np.asarray(stored.embeddings[0].embedding)
    assert vector.shape == (EMBEDDING_DIMENSIONS,)
    assert math.isclose(float(np.linalg.norm(vector)), 1.0, rel_tol=1e-5)
    assert stored.embeddings[0].frame_time is None
    # pgvector's cosine distance: identical vector → 0, its opposite → 2.
    distance = db_session.scalar(
        select(AssetEmbedding.embedding.cosine_distance(unit(1))).where(
            AssetEmbedding.index_id == index.id
        )
    )
    assert distance == pytest.approx(0.0, abs=1e-5)
    opposite = (-np.asarray(unit(1))).tolist()
    assert db_session.scalar(
        select(AssetEmbedding.embedding.cosine_distance(opposite)).where(
            AssetEmbedding.index_id == index.id
        )
    ) == pytest.approx(2.0, abs=1e-5)


def test_video_frames_keep_their_times(db_session):
    project = make_project(db_session)
    asset = make_asset(db_session, video_fields(project))
    index = make_ready(db_session, asset, [unit(2), unit(3), unit(4)])
    db_session.expire_all()
    frames = db_session.get(VisualSemanticIndex, index.id).embeddings
    assert [(f.frame_index, f.frame_time) for f in frames] == [(0, 0.5), (1, 1.5), (2, 2.5)]


@pytest.mark.parametrize(
    "vector",
    [
        [0.1] * (EMBEDDING_DIMENSIONS - 1),  # wrong dimension
        [0.1] * (EMBEDDING_DIMENSIONS + 1),
        [float("nan")] + [0.1] * (EMBEDDING_DIMENSIONS - 1),  # not finite
        [float("inf")] + [0.1] * (EMBEDDING_DIMENSIONS - 1),
    ],
    ids=["short", "long", "nan", "inf"],
)
def test_the_database_refuses_malformed_vectors(db_session, vector):
    project = make_project(db_session)
    index = make_index(db_session, make_asset(db_session, image_fields(project)))
    db_session.add(AssetEmbedding(index=index, frame_index=0, embedding=vector))
    with pytest.raises((DataError, StatementError, ValueError)):
        db_session.flush()


def test_one_index_per_asset_and_model_identity(db_session):
    project = make_project(db_session)
    asset = make_asset(db_session, image_fields(project))
    make_index(db_session, asset)
    make_index(db_session, asset, model_version="rev-b")  # another model version: allowed
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            make_index(db_session, asset)


def test_one_embedding_per_frame(db_session):
    project = make_project(db_session)
    index = make_index(db_session, make_asset(db_session, video_fields(project)))
    db_session.add(AssetEmbedding(index=index, frame_index=0, frame_time=0.5, embedding=unit(5)))
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                AssetEmbedding(index=index, frame_index=0, frame_time=1.0, embedding=unit(6))
            )
            db_session.flush()


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "done"},
        {"attempt": 0},
        {"dimensions": 0},
        {"source_sha256": "abc"},
        {"frames_total": 2, "frames_done": 3},
        {"frames_done": -1},
        {"status": "ready"},  # no vectors, no completion time
        {"status": "ready", "embedding_count": 0, "completed_at": datetime.now(UTC)},
        {"status": "failed"},  # without an error code
    ],
)
def test_index_constraints(db_session, changes):
    project = make_project(db_session)
    asset = make_asset(db_session, image_fields(project))
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            make_index(db_session, asset, **changes)


@pytest.mark.parametrize("changes", [{"frame_index": -1}, {"frame_time": -0.5}])
def test_embedding_constraints(db_session, changes):
    project = make_project(db_session)
    index = make_index(db_session, make_asset(db_session, video_fields(project)))
    fields = {"index": index, "frame_index": 0, "frame_time": 0.0, "embedding": unit(7)}
    fields.update(changes)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(AssetEmbedding(**fields))
            db_session.flush()


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_deleting_an_asset_deletes_its_indexes_and_embeddings_in_the_database(db_session):
    project = make_project(db_session)
    asset = make_asset(db_session, video_fields(project))
    keep = make_asset(db_session, image_fields(project))
    make_ready(db_session, asset, [unit(8), unit(9)])
    make_index(db_session, asset, model_version="rev-old")
    make_ready(db_session, keep, [unit(10)])
    before = (_count(db_session, VisualSemanticIndex), _count(db_session, AssetEmbedding))
    # A raw DELETE: the database cascade alone removes the derived rows.
    db_session.execute(text("DELETE FROM visual_assets WHERE id = :id"), {"id": asset.id})
    db_session.expire_all()
    after = (_count(db_session, VisualSemanticIndex), _count(db_session, AssetEmbedding))
    assert (before[0] - after[0], before[1] - after[1]) == (2, 2)
    assert db_session.scalars(
        select(VisualSemanticIndex).where(VisualSemanticIndex.visual_asset_id == keep.id)
    ).one()


def test_deleting_an_asset_through_the_orm_and_its_project_cascade(db_session):
    project = make_project(db_session)
    first = make_asset(db_session, image_fields(project))
    second = make_asset(db_session, image_fields(project))
    make_ready(db_session, first, [unit(11)])
    make_ready(db_session, second, [unit(12)])
    db_session.delete(first)
    db_session.flush()
    first_id, second_id = first.id, second.id
    remaining = db_session.scalars(select(VisualSemanticIndex.visual_asset_id)).all()
    assert first_id not in remaining and second_id in remaining
    db_session.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project.id})
    db_session.expire_all()
    assert second_id not in db_session.scalars(select(VisualSemanticIndex.visual_asset_id)).all()


def _row(status: str, **identity) -> VisualSemanticIndex:
    fields = {
        "provider": IDENTITY.provider,
        "model": IDENTITY.model,
        "model_version": IDENTITY.model_version,
        "embedding_version": IDENTITY.embedding_version,
        "dimensions": IDENTITY.dimensions,
    }
    fields.update(identity)
    return VisualSemanticIndex(id=uuid.uuid4(), status=status, **fields)


@pytest.mark.parametrize("status", ["queued", "indexing", "ready", "failed"])
def test_the_state_of_the_current_index(status):
    assert semantic_state([_row(status)], IDENTITY) == SemanticState(status)


def test_state_without_an_index_with_only_another_model_and_when_turned_off():
    assert semantic_state([], IDENTITY) == SemanticState.NOT_INDEXED
    old = _row("ready", model_version="rev-old")
    assert semantic_state([old], IDENTITY) == SemanticState.STALE
    reprocessed = _row("ready", embedding_version="semantic_v0")
    assert semantic_state([reprocessed], IDENTITY) == SemanticState.STALE
    other_size = _row("ready", dimensions=768)
    assert semantic_state([other_size], IDENTITY) == SemanticState.STALE
    # The current model wins over stale leftovers.
    assert semantic_state([old, _row("indexing")], IDENTITY) == SemanticState.INDEXING
    assert semantic_state([old], None) == SemanticState.UNAVAILABLE
    assert semantic_state([], None) == SemanticState.UNAVAILABLE
