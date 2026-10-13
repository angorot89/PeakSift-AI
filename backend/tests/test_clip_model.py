import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ACTIVE_CLIP_STATUSES,
    CLIP_CONTENT_TYPE,
    RENDER_PROFILE_SOURCE_MP4_V1,
    Clip,
    ClipCandidate,
    ClipDetectionRun,
    ClipStatus,
    Project,
    Transcription,
    TranscriptSegment,
    User,
    Video,
)


def make_candidate(db_session: Session, *, start: float = 30.0, end: float = 60.0) -> ClipCandidate:
    user = User(email=f"creator-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    project = Project(name="Stream", owner=user)
    video = Video(
        project=project,
        original_filename="stream.mp4",
        storage_key=f"videos/{uuid.uuid4().hex}.mp4",
        content_type="video/mp4",
        file_size=1234,
        status="ready",
        duration_seconds=600.0,
    )
    transcription = Transcription(video=video, provider="fake", model="fake-1", status="completed")
    transcription.segments.append(
        TranscriptSegment(sequence_index=0, start_time=0.0, end_time=4.0, text="hello")
    )
    run = ClipDetectionRun(
        video=video,
        transcription=transcription,
        transcript_fingerprint="f" * 64,
        provider="ollama",
        model="llama3.2:3b",
        config={},
        status="completed",
    )
    db_session.add_all([user, video, transcription, run])
    db_session.flush()  # the video needs an id before the candidate can reference it
    candidate = ClipCandidate(
        run=run,
        video_id=video.id,
        start_time=start,
        end_time=end,
        duration_seconds=end - start,
        title="The reveal",
        hook="Wait for it",
        rationale="Pays off.",
        category="story",
        transcript_excerpt="hello",
        overall_score=80,
        hook_score=80,
        entertainment_score=80,
        clarity_score=80,
        payoff_score=80,
        completeness_score=80,
        rank=1,
    )
    db_session.add(candidate)
    db_session.commit()
    return candidate


def make_clip(db_session: Session, candidate: ClipCandidate | None = None, **overrides) -> Clip:
    candidate = candidate or make_candidate(db_session)
    fields = {
        "candidate": candidate,
        "video_id": candidate.video_id,
        "start_time": candidate.start_time,
        "end_time": candidate.end_time,
        "duration_seconds": candidate.duration_seconds,
    }
    fields.update(overrides)
    clip = Clip(**fields)
    db_session.add(clip)
    db_session.commit()
    return clip


# --- defaults and state machine ---------------------------------------------------------------


def test_clip_defaults_snapshot_the_candidate_boundaries(db_session: Session):
    candidate = make_candidate(db_session, start=30.0, end=60.0)
    clip = make_clip(db_session, candidate)

    assert isinstance(clip.id, uuid.UUID)
    assert clip.status == ClipStatus.QUEUED == "queued"
    assert clip.progress_percent == 0 and clip.attempt == 1
    assert (clip.start_time, clip.end_time, clip.duration_seconds) == (30.0, 60.0, 30.0)
    assert clip.render_profile == RENDER_PROFILE_SOURCE_MP4_V1 == "source_mp4_v1"
    assert clip.content_type == CLIP_CONTENT_TYPE == "video/mp4"
    assert clip.storage_key is None and clip.file_size is None
    assert clip.width is None and clip.height is None and clip.fps is None
    assert clip.video_codec is None and clip.audio_codec is None
    assert clip.error_code is None and clip.error_message is None and clip.celery_task_id is None
    assert clip.started_at is None and clip.completed_at is None and clip.heartbeat_at is None
    assert clip.created_at.tzinfo is not None


def test_status_machine_values():
    assert [s.value for s in ClipStatus] == ["queued", "rendering", "validating", "ready", "failed"]
    assert ClipStatus.READY not in ACTIVE_CLIP_STATUSES
    assert ClipStatus.FAILED not in ACTIVE_CLIP_STATUSES
    assert len(ACTIVE_CLIP_STATUSES) == 3


def test_snapshot_is_independent_of_later_candidate_changes(db_session: Session):
    candidate = make_candidate(db_session, start=30.0, end=60.0)
    clip = make_clip(db_session, candidate)
    candidate.start_time, candidate.end_time, candidate.duration_seconds = 100.0, 140.0, 40.0
    candidate.title = "Renamed"
    db_session.commit()
    db_session.refresh(clip)
    assert (clip.start_time, clip.end_time, clip.duration_seconds) == (30.0, 60.0, 30.0)


# --- relationships and ownership traversal -----------------------------------------------------


def test_candidate_has_at_most_one_clip(db_session: Session):
    candidate = make_candidate(db_session)
    clip = make_clip(db_session, candidate)
    db_session.refresh(candidate)
    assert candidate.clip is clip
    assert clip.candidate is candidate

    with pytest.raises(IntegrityError):
        make_clip(db_session, candidate)
    db_session.rollback()


def test_ownership_chain_is_traversable(db_session: Session):
    clip = make_clip(db_session)
    owner = clip.candidate.run.video.project.owner
    assert owner.email.startswith("creator-")
    assert clip.video is clip.candidate.run.video
    db_session.refresh(clip.video)
    assert clip.video.clips == [clip]


def test_storage_key_is_unique_across_clips(db_session: Session):
    first = make_clip(db_session, storage_key="clips/a/clip.mp4")
    assert first.storage_key == "clips/a/clip.mp4"
    with pytest.raises(IntegrityError):
        make_clip(db_session, storage_key="clips/a/clip.mp4")
    db_session.rollback()


# --- constraints ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_time": -1.0},
        {"end_time": 30.0},  # equal to start
        {"end_time": 10.0},  # before start
        {"duration_seconds": 5.0},  # does not match end - start
        {"progress_percent": 101},
        {"progress_percent": -1},
        {"attempt": 0},
    ],
)
def test_constraints_reject_bad_rows(db_session: Session, overrides: dict):
    with pytest.raises(IntegrityError):
        make_clip(db_session, **overrides)
    db_session.rollback()


def test_ready_metadata_can_be_recorded(db_session: Session):
    clip = make_clip(db_session)
    clip.status = ClipStatus.READY
    clip.progress_percent = 100
    clip.storage_key = f"clips/{clip.id}/clip.mp4"
    clip.file_size = 123456
    clip.width, clip.height, clip.fps = 1920, 1080, 29.97
    clip.video_codec, clip.audio_codec = "h264", "aac"
    clip.started_at = clip.completed_at = clip.heartbeat_at = datetime.now(UTC)
    db_session.commit()
    db_session.refresh(clip)
    assert clip.status == "ready" and clip.file_size == 123456 and clip.fps == 29.97


# --- cascades --------------------------------------------------------------------------------


def test_deleting_the_candidate_deletes_its_clip(db_session: Session):
    clip = make_clip(db_session)
    clip_id, candidate = clip.id, clip.candidate
    db_session.delete(candidate)
    db_session.commit()
    db_session.expunge_all()
    assert db_session.get(Clip, clip_id) is None


def test_deleting_the_video_deletes_clips_but_not_other_videos(db_session: Session):
    clip = make_clip(db_session)
    other = make_clip(db_session)
    video_id, clip_id, other_id = clip.video_id, clip.id, other.id
    db_session.delete(db_session.get(Video, video_id))
    db_session.commit()
    db_session.expunge_all()
    assert db_session.get(Clip, clip_id) is None
    assert db_session.get(Clip, other_id) is not None
    assert db_session.scalars(select(Clip).where(Clip.video_id == video_id)).all() == []


def test_deleting_a_clip_leaves_candidate_video_and_run_untouched(db_session: Session):
    clip = make_clip(db_session)
    candidate_id, video_id, run_id = clip.candidate_id, clip.video_id, clip.candidate.run_id
    db_session.delete(clip)
    db_session.commit()
    db_session.expunge_all()
    assert db_session.get(ClipCandidate, candidate_id) is not None
    assert db_session.get(Video, video_id) is not None
    assert db_session.get(ClipDetectionRun, run_id) is not None
