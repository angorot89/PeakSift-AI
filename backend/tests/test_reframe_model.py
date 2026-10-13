import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    ACTIVE_REFRAME_STATUSES,
    Clip,
    KeyframeMode,
    Project,
    ReframeAnalysis,
    ReframeConfidence,
    ReframeKeyframe,
    ReframeStatus,
    User,
    Video,
)
from app.services.reframe.config import ALGORITHM_VERSION, TARGET_RATIO, ReframeConfig
from tests.test_clip_edit_model import make_clip


def settings(**overrides) -> Settings:
    return Settings(**{**get_settings().model_dump(), **overrides})


def make_analysis(db: Session, clip: Clip, config: ReframeConfig | None = None, **overrides):
    config = config or ReframeConfig.from_settings(settings())
    fields = {
        "clip": clip,
        "video_id": clip.video_id,
        "provider": config.detector,
        "algorithm_version": config.algorithm_version,
        "config": config.snapshot(),
        "config_fingerprint": config.fingerprint(),
        "sample_fps": config.sample_fps,
        "celery_task_id": "task-1",
    }
    fields.update(overrides)
    analysis = ReframeAnalysis(**fields)
    db.add(analysis)
    db.commit()
    return analysis


def keyframe(analysis: ReframeAnalysis, index: int, **overrides) -> ReframeKeyframe:
    fields = {
        "analysis": analysis,
        "sequence_index": index,
        "timestamp": index * 0.5,
        "center_x": 0.5,
        "center_y": 0.5,
        "crop_width": 0.3164,
        "crop_height": 1.0,
        "confidence": 0.9,
        "mode": KeyframeMode.TRACKED,
    }
    fields.update(overrides)
    return ReframeKeyframe(**fields)


# --- configuration snapshot -----


def test_snapshot_is_explicit_versioned_and_server_controlled():
    config = ReframeConfig.from_settings(settings())
    snapshot = config.snapshot()
    assert snapshot["algorithm_version"] == ALGORITHM_VERSION == "smart_reframe_v1"
    assert snapshot["target_aspect_ratio"] == "9:16" and TARGET_RATIO == 9 / 16
    assert set(snapshot) == {
        "algorithm_version",
        "target_aspect_ratio",
        "detector",
        "sample_fps",
        "analysis_width",
        "min_detection_confidence",
        "face_margin",
        "dead_zone",
        "smoothing_seconds",
        "max_pan_per_second",
        "max_gap_seconds",
    }
    assert ReframeConfig.from_snapshot(snapshot) == config


def test_fingerprint_is_deterministic_and_tracks_every_setting():
    base = ReframeConfig.from_settings(settings())
    assert base.fingerprint() == ReframeConfig.from_settings(settings()).fingerprint()
    assert len(base.fingerprint()) == 64
    for change in (
        {"reframe_sample_fps": 4},
        {"reframe_dead_zone": 0.2},
        {"reframe_max_pan_per_second": 0.5},
        {"reframe_min_detection_confidence": 0.7},
        {"reframe_smoothing_seconds": 1.0},
    ):
        assert ReframeConfig.from_settings(settings(**change)).fingerprint() != base.fingerprint()


@pytest.mark.parametrize(
    "snapshot",
    [{}, {"algorithm_version": "smart_reframe_v0"}, {"algorithm_version": ALGORITHM_VERSION}, None],
)
def test_unknown_or_incomplete_snapshots_are_refused(snapshot):
    with pytest.raises(ValueError):
        ReframeConfig.from_snapshot(snapshot)


@pytest.mark.parametrize(
    "bad",
    [
        {"reframe_detector": "../model.tflite"},
        {"reframe_sample_fps": 0},
        {"reframe_dead_zone": 0.9},
        {"reframe_min_detection_confidence": 2},
    ],
)
def test_settings_validate_reframe_values(bad):
    with pytest.raises(ValueError):
        settings(**bad)


# --- analysis rows -----


def test_analysis_defaults_and_statuses(db_session: Session):
    analysis = make_analysis(db_session, make_clip(db_session))
    assert analysis.status == ReframeStatus.QUEUED and analysis.progress_percent == 0
    assert analysis.attempt == 1 and analysis.target_aspect_ratio == "9:16"
    assert analysis.keyframes == [] and analysis.completed_at is None
    assert [s.value for s in ACTIVE_REFRAME_STATUSES] == [
        "queued",
        "sampling",
        "detecting",
        "tracking",
        "planning",
    ]
    assert {c.value for c in ReframeConfidence} == {"high", "mixed", "fallback"}


def test_identical_configuration_twice_is_refused(db_session: Session):
    clip = make_clip(db_session)
    make_analysis(db_session, clip)
    with pytest.raises(IntegrityError):
        make_analysis(db_session, clip)
    db_session.rollback()


def test_new_configuration_or_another_clip_is_a_separate_analysis(db_session: Session):
    clip = make_clip(db_session)
    make_analysis(db_session, clip)
    make_analysis(db_session, clip, ReframeConfig.from_settings(settings(reframe_sample_fps=4)))
    make_analysis(db_session, make_clip(db_session))
    assert (
        len(
            db_session.scalars(
                select(ReframeAnalysis).where(ReframeAnalysis.clip_id == clip.id)
            ).all()
        )
        == 2
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "zooming"},
        {"progress_percent": 101},
        {"progress_percent": -1},
        {"attempt": 0},
        {"sample_fps": 0},
        {"target_aspect_ratio": "16:9"},
        {"source_width": 1920, "source_height": None},
        {"source_width": 0, "source_height": 1080},
        {"overall_confidence": 1.5},
        {"confidence_level": "excellent"},
        {"fallback_fraction": -0.1},
        {"frames_sampled": -1},
        {"subject_switches": -2},
    ],
)
def test_analysis_constraints(db_session: Session, overrides: dict):
    clip = make_clip(db_session)
    with pytest.raises(IntegrityError):
        make_analysis(db_session, clip, **overrides)
    db_session.rollback()


# --- keyframes -----


def test_keyframes_are_ordered_and_unique_per_sequence(db_session: Session):
    analysis = make_analysis(db_session, make_clip(db_session))
    db_session.add_all([keyframe(analysis, 2), keyframe(analysis, 0), keyframe(analysis, 1)])
    db_session.commit()
    db_session.expire_all()
    assert [k.sequence_index for k in analysis.keyframes] == [0, 1, 2]
    db_session.add(keyframe(analysis, 1))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        {"timestamp": -0.1},
        {"sequence_index": -1},
        {"center_x": 1.2},
        {"center_y": -0.01},
        {"crop_width": 0},
        {"crop_height": 1.5},
        {"center_x": 0.1, "crop_width": 0.5},  # left edge outside the source
        {"center_x": 0.95, "crop_width": 0.3164},  # right edge outside the source
        {"center_y": 0.4, "crop_height": 1.0},  # vertical overflow
        {"confidence": 1.01},
        {"mode": "zoom"},
    ],
)
def test_keyframe_constraints_keep_the_crop_inside_the_source(db_session: Session, overrides: dict):
    analysis = make_analysis(db_session, make_clip(db_session))
    db_session.add(keyframe(analysis, 0, **overrides))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_crop_touching_the_source_edges_is_valid(db_session: Session):
    analysis = make_analysis(db_session, make_clip(db_session))
    width = 0.31640625
    db_session.add_all(
        [
            keyframe(analysis, 0, center_x=width / 2),
            keyframe(analysis, 1, center_x=1 - width / 2),
            keyframe(analysis, 2, mode=KeyframeMode.FALLBACK, confidence=0.0),
        ]
    )
    db_session.commit()


# --- ownership and lifecycle -----


def test_ownership_traversal_reaches_the_user(db_session: Session):
    clip = make_clip(db_session)
    analysis = make_analysis(db_session, clip)
    owner = db_session.scalar(
        select(User)
        .join(Project, Project.user_id == User.id)
        .join(Video, Video.project_id == Project.id)
        .join(Clip, Clip.video_id == Video.id)
        .join(ReframeAnalysis, ReframeAnalysis.clip_id == Clip.id)
        .where(ReframeAnalysis.id == analysis.id)
    )
    assert owner is not None and owner.id == clip.video.project.user_id
    assert clip.reframe_analyses == [analysis]


def test_deleting_a_clip_deletes_its_analyses_and_keyframes(db_session: Session):
    clip = make_clip(db_session)
    analysis = make_analysis(db_session, clip)
    db_session.add(keyframe(analysis, 0))
    db_session.commit()
    analysis_id, video_id = analysis.id, clip.video_id
    db_session.delete(clip)
    db_session.commit()
    assert db_session.get(ReframeAnalysis, analysis_id) is None
    assert db_session.scalars(select(ReframeKeyframe)).all() == []
    assert db_session.get(Video, video_id) is not None


def test_deleting_an_analysis_keeps_the_clip(db_session: Session):
    clip = make_clip(db_session)
    analysis = make_analysis(db_session, clip)
    db_session.add(keyframe(analysis, 0))
    db_session.commit()
    db_session.delete(analysis)
    db_session.commit()
    assert db_session.get(Clip, clip.id) is not None
    assert db_session.scalars(select(ReframeKeyframe)).all() == []


def test_attempt_token_is_stored_and_can_be_superseded(db_session: Session):
    analysis = make_analysis(db_session, make_clip(db_session))
    token = str(uuid.uuid4())
    analysis.attempt, analysis.celery_task_id = 2, token
    db_session.commit()
    db_session.expire_all()
    assert analysis.attempt == 2 and analysis.celery_task_id == token
