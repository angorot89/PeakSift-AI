import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    ACTIVE_CAPTION_TRACK_STATUSES,
    CaptionTrack,
    CaptionTrackStatus,
    CaptionWord,
    Clip,
    Project,
    User,
    Video,
)
from app.services.caption_timing.config import ALIGNMENT_VERSION, CaptionTimingConfig
from tests.test_clip_edit_model import make_clip


def settings(**overrides) -> Settings:
    return Settings(**{**get_settings().model_dump(), **overrides})


def make_track(
    db: Session, clip: Clip, config: CaptionTimingConfig | None = None, **overrides
) -> CaptionTrack:
    config = config or CaptionTimingConfig.from_settings(settings(), language_hint="en")
    fields = {
        "clip": clip,
        "video_id": clip.video_id,
        "provider": config.provider,
        "model": config.model,
        "alignment_version": config.alignment_version,
        "config": config.snapshot(),
        "config_fingerprint": config.fingerprint(),
        "language_hint": config.language_hint,
        "celery_task_id": "task-1",
    }
    fields.update(overrides)
    track = CaptionTrack(**fields)
    db.add(track)
    db.commit()
    return track


def word(track: CaptionTrack, index: int, **overrides) -> CaptionWord:
    fields = {
        "track": track,
        "sequence_index": index,
        "start_time": index * 0.4,
        "end_time": index * 0.4 + 0.3,
        "text": f"word{index}",
        "confidence": 0.9,
    }
    fields.update(overrides)
    return CaptionWord(**fields)


# --- configuration snapshot -----


def test_snapshot_is_versioned_server_controlled_and_has_no_styling():
    config = CaptionTimingConfig.from_settings(settings(), language_hint="fr")
    snapshot = config.snapshot()
    assert snapshot["alignment_version"] == ALIGNMENT_VERSION == "caption_alignment_v1"
    assert set(snapshot) == {
        "alignment_version",
        "provider",
        "model",
        "compute_type",
        "beam_size",
        "language_hint",
    }
    assert snapshot["provider"] == "faster_whisper" and snapshot["language_hint"] == "fr"
    # Timing reuses the transcription model settings (one loaded model per worker).
    assert snapshot["model"] == get_settings().faster_whisper_model
    assert CaptionTimingConfig.from_snapshot(snapshot) == config


def test_fingerprint_is_deterministic_and_tracks_every_setting():
    base = CaptionTimingConfig.from_settings(settings(), language_hint="en")
    assert (
        base.fingerprint()
        == CaptionTimingConfig.from_settings(settings(), language_hint="en").fingerprint()
    )
    variants = [
        CaptionTimingConfig.from_settings(settings(), language_hint="fr"),
        CaptionTimingConfig.from_settings(settings(), language_hint=None),
        CaptionTimingConfig.from_settings(
            settings(faster_whisper_model="tiny"), language_hint="en"
        ),
        CaptionTimingConfig.from_settings(settings(faster_whisper_beam_size=1), language_hint="en"),
        CaptionTimingConfig.from_settings(
            settings(faster_whisper_compute_type="float32"), language_hint="en"
        ),
    ]
    assert len({base.fingerprint(), *(v.fingerprint() for v in variants)}) == 6
    # An empty hint is "no hint", not a different configuration.
    assert CaptionTimingConfig.from_settings(settings(), language_hint="").language_hint is None


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        {},
        {"alignment_version": "caption_alignment_v0"},
        {"alignment_version": ALIGNMENT_VERSION},
    ],
)
def test_unknown_or_incomplete_snapshots_are_refused(snapshot):
    with pytest.raises(ValueError):
        CaptionTimingConfig.from_snapshot(snapshot)


def test_only_allow_listed_providers_are_configurable():
    with pytest.raises(ValueError):
        settings(caption_timing_provider="some_cloud_service")


# --- tracks -----


def test_track_defaults_and_statuses(db_session: Session):
    track = make_track(db_session, make_clip(db_session))
    assert track.status == CaptionTrackStatus.QUEUED and track.progress_percent == 0
    assert track.attempt == 1 and track.word_count is None and track.words == []
    assert set(ACTIVE_CAPTION_TRACK_STATUSES) == {
        CaptionTrackStatus.QUEUED,
        CaptionTrackStatus.PREPARING_AUDIO,
        CaptionTrackStatus.ALIGNING,
        CaptionTrackStatus.VALIDATING,
    }


def test_identical_configuration_twice_is_refused(db_session: Session):
    clip = make_clip(db_session)
    make_track(db_session, clip)
    with pytest.raises(IntegrityError):
        make_track(db_session, clip)
    db_session.rollback()


def test_new_configuration_or_another_clip_is_a_separate_track(db_session: Session):
    clip = make_clip(db_session)
    make_track(db_session, clip)
    other = CaptionTimingConfig.from_settings(
        settings(faster_whisper_model="tiny"), language_hint="en"
    )
    make_track(db_session, clip, other)
    make_track(db_session, make_clip(db_session))
    assert (
        len(db_session.scalars(select(CaptionTrack).where(CaptionTrack.clip_id == clip.id)).all())
        == 2
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "done"},
        {"progress_percent": 101},
        {"progress_percent": -1},
        {"attempt": 0},
        {"word_count": -1},
        {"rejected_word_count": -1},
        {"average_confidence": 1.5},
        {"language_probability": -0.1},
        {"audio_duration_seconds": -1.0},
    ],
)
def test_track_constraints(db_session: Session, overrides: dict):
    clip = make_clip(db_session)
    with pytest.raises(IntegrityError):
        make_track(db_session, clip, **overrides)
    db_session.rollback()


# --- words -----


def test_words_are_ordered_and_unique_per_sequence(db_session: Session):
    track = make_track(db_session, make_clip(db_session))
    db_session.add_all([word(track, 2), word(track, 0), word(track, 1)])
    db_session.commit()
    db_session.expire_all()
    assert [w.sequence_index for w in track.words] == [0, 1, 2]
    db_session.add(word(track, 1))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        {"sequence_index": -1},
        {"start_time": -0.01},
        {"end_time": 0.0},  # end must be strictly after start (start is 0 for word 0)
        {"text": ""},
        {"confidence": 1.01},
        {"confidence": -0.5},
    ],
)
def test_word_constraints(db_session: Session, overrides: dict):
    track = make_track(db_session, make_clip(db_session))
    db_session.add(word(track, 0, **overrides))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_words_keep_unicode_text_exactly(db_session: Session):
    track = make_track(db_session, make_clip(db_session))
    texts = ["C'était", "مرحبا", "naïve", "don't", "🔥", "12,5%"]
    db_session.add_all([word(track, i, text=t, confidence=None) for i, t in enumerate(texts)])
    db_session.commit()
    db_session.expire_all()
    assert [w.text for w in track.words] == texts
    assert track.words[0].confidence is None


# --- ownership and lifecycle -----


def test_ownership_traversal_reaches_the_user(db_session: Session):
    clip = make_clip(db_session)
    track = make_track(db_session, clip)
    owner = db_session.scalar(
        select(User)
        .join(Project, Project.user_id == User.id)
        .join(Video, Video.project_id == Project.id)
        .join(Clip, Clip.video_id == Video.id)
        .join(CaptionTrack, CaptionTrack.clip_id == Clip.id)
        .where(CaptionTrack.id == track.id)
    )
    assert owner is not None and owner.id == clip.video.project.user_id
    assert clip.caption_tracks == [track]


def test_deleting_a_clip_deletes_its_tracks_and_words(db_session: Session):
    clip = make_clip(db_session)
    track = make_track(db_session, clip)
    db_session.add(word(track, 0))
    db_session.commit()
    track_id, video_id = track.id, clip.video_id
    db_session.delete(clip)
    db_session.commit()
    assert db_session.get(CaptionTrack, track_id) is None
    assert db_session.scalars(select(CaptionWord)).all() == []
    assert db_session.get(Video, video_id) is not None


def test_deleting_a_track_keeps_the_clip(db_session: Session):
    clip = make_clip(db_session)
    track = make_track(db_session, clip)
    db_session.add(word(track, 0))
    db_session.commit()
    db_session.delete(track)
    db_session.commit()
    assert db_session.get(Clip, clip.id) is not None
    assert db_session.scalars(select(CaptionWord)).all() == []


def test_attempt_token_is_stored_and_can_be_superseded(db_session: Session):
    track = make_track(db_session, make_clip(db_session))
    token = str(uuid.uuid4())
    track.attempt, track.celery_task_id = 2, token
    db_session.commit()
    db_session.expire_all()
    assert track.attempt == 2 and track.celery_task_id == token
