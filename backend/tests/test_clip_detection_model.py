import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ACTIVE_CLIP_DETECTION_STATUSES,
    CANDIDATE_CATEGORIES,
    CandidateDecision,
    ClipCandidate,
    ClipDetectionRun,
    ClipDetectionStatus,
    Project,
    Transcription,
    TranscriptSegment,
    User,
    Video,
)


def make_video(db_session: Session) -> Video:
    user = User(email=f"creator-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    project = Project(name="Stream", owner=user)
    video = Video(
        project=project,
        original_filename="stream.mp4",
        storage_key=f"videos/{uuid.uuid4().hex}.mp4",
        content_type="video/mp4",
        file_size=1234,
        status="ready",
        duration_seconds=3600.0,
    )
    db_session.add_all([user, video])
    db_session.commit()
    return video


def make_transcription(db_session: Session, video: Video) -> Transcription:
    transcription = Transcription(
        video=video, provider="faster_whisper", model="small", status="completed"
    )
    transcription.segments.append(
        TranscriptSegment(sequence_index=0, start_time=0.0, end_time=4.0, text="hello")
    )
    db_session.add(transcription)
    db_session.commit()
    return transcription


def make_run(db_session: Session, video: Video | None = None, **overrides) -> ClipDetectionRun:
    video = video or make_video(db_session)
    transcription = video.transcription or make_transcription(db_session, video)
    fields = {
        "video": video,
        "transcription": transcription,
        "transcript_fingerprint": "f" * 64,
        "provider": "ollama",
        "model": "llama3.2:3b",
        "config": {"window_seconds": 300, "target_candidates": 10},
    }
    fields.update(overrides)
    run = ClipDetectionRun(**fields)
    db_session.add(run)
    db_session.commit()
    return run


def candidate(rank: int, start: float, end: float, **overrides) -> ClipCandidate:
    fields = {
        "start_time": start,
        "end_time": end,
        "duration_seconds": end - start,
        "title": f"Moment {rank}",
        "hook": "You will not believe this",
        "rationale": "A self-contained story with a clear payoff.",
        "category": "story",
        "transcript_excerpt": "hello",
        "overall_score": 80,
        "hook_score": 85,
        "entertainment_score": 80,
        "clarity_score": 75,
        "payoff_score": 80,
        "completeness_score": 78,
        "rank": rank,
    }
    fields.update(overrides)
    return ClipCandidate(**fields)


def attach(db_session: Session, run: ClipDetectionRun, *candidates: ClipCandidate) -> None:
    for item in candidates:
        item.video_id = run.video_id
        run.candidates.append(item)
    db_session.commit()


# --- run -----


def test_run_defaults(db_session: Session):
    run = make_run(db_session)

    assert isinstance(run.id, uuid.UUID)
    assert run.status == ClipDetectionStatus.QUEUED == "queued"
    assert run.progress_percent == 0
    assert run.attempt == 1
    assert run.windows_total is None and run.windows_done == 0
    assert run.error_code is None and run.error_message is None
    assert run.celery_task_id is None
    assert run.started_at is None and run.completed_at is None and run.heartbeat_at is None
    assert run.created_at is not None and run.updated_at is not None
    assert run.config == {"window_seconds": 300, "target_candidates": 10}
    assert run.candidates == []


def test_status_machine_values():
    assert [s.value for s in ClipDetectionStatus] == [
        "queued",
        "preparing_transcript",
        "analyzing",
        "validating",
        "ranking",
        "completed",
        "failed",
    ]
    assert ClipDetectionStatus.COMPLETED not in ACTIVE_CLIP_DETECTION_STATUSES
    assert ClipDetectionStatus.FAILED not in ACTIVE_CLIP_DETECTION_STATUSES
    assert len(ACTIVE_CLIP_DETECTION_STATUSES) == 5
    assert "other" in CANDIDATE_CATEGORIES
    assert [d.value for d in CandidateDecision] == ["undecided", "saved", "dismissed"]


def test_run_links_video_and_transcript_snapshot(db_session: Session):
    video = make_video(db_session)
    transcription = make_transcription(db_session, video)
    run = make_run(db_session, video)

    assert run.video is video
    assert run.transcription is transcription
    assert len(run.transcript_fingerprint) == 64
    db_session.refresh(video)
    assert video.clip_detection_runs == [run]


def test_a_video_may_have_many_finished_runs(db_session: Session):
    video = make_video(db_session)
    make_run(db_session, video, status="completed")
    make_run(db_session, video, status="failed")
    make_run(db_session, video, status="completed")

    db_session.refresh(video)
    assert len(video.clip_detection_runs) == 3


@pytest.mark.parametrize("active_status", [s.value for s in ACTIVE_CLIP_DETECTION_STATUSES])
def test_only_one_active_run_per_video(db_session: Session, active_status: str):
    video = make_video(db_session)
    make_run(db_session, video, status=active_status)

    with pytest.raises(IntegrityError):
        make_run(db_session, video, status="queued")
    db_session.rollback()


def test_a_completed_run_does_not_block_a_new_active_one(db_session: Session):
    video = make_video(db_session)
    make_run(db_session, video, status="completed")
    make_run(db_session, video, status="failed")

    run = make_run(db_session, video, status="queued")  # must not raise
    assert run.status == "queued"


def test_active_runs_on_different_videos_are_independent(db_session: Session):
    make_run(db_session, status="analyzing")
    make_run(db_session, status="analyzing")  # another video


@pytest.mark.parametrize("progress", [-1, 101])
def test_progress_is_bounded(db_session: Session, progress: int):
    with pytest.raises(IntegrityError):
        make_run(db_session, progress_percent=progress)
    db_session.rollback()


def test_attempt_must_be_positive(db_session: Session):
    with pytest.raises(IntegrityError):
        make_run(db_session, attempt=0)
    db_session.rollback()


def test_timestamps_are_timezone_aware(db_session: Session):
    run = make_run(db_session)
    run.started_at = datetime.now(UTC)
    db_session.commit()
    db_session.refresh(run)

    assert run.created_at.tzinfo is not None
    assert run.started_at.tzinfo is not None


# --- candidates -----


def test_candidates_are_ordered_by_rank(db_session: Session):
    run = make_run(db_session)
    attach(
        db_session,
        run,
        candidate(3, 300.0, 340.0),
        candidate(1, 10.0, 50.0),
        candidate(2, 100.0, 160.0),
    )

    db_session.expire(run)
    assert [c.rank for c in run.candidates] == [1, 2, 3]
    assert [c.start_time for c in run.candidates] == [10.0, 100.0, 300.0]
    assert run.candidates[0].video_id == run.video_id


def test_candidate_defaults(db_session: Session):
    run = make_run(db_session)
    attach(db_session, run, candidate(1, 10.0, 50.0))
    item = run.candidates[0]

    assert item.decision == CandidateDecision.UNDECIDED == "undecided"
    assert item.decided_at is None
    assert item.duration_seconds == 40.0
    assert item.created_at is not None


def test_rank_is_unique_within_a_run_but_not_across_runs(db_session: Session):
    video = make_video(db_session)
    first = make_run(db_session, video, status="completed")
    second = make_run(db_session, video, status="completed")
    attach(db_session, first, candidate(1, 10.0, 50.0))
    attach(db_session, second, candidate(1, 10.0, 50.0))  # fine: another run

    with pytest.raises(IntegrityError):
        attach(db_session, first, candidate(1, 70.0, 100.0))
    db_session.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_time": -0.5},
        {"end_time": 10.0},  # end == start
        {"end_time": 5.0},  # end < start
        {"duration_seconds": 1.0},  # does not match end - start
        {"rank": 0},
        {"overall_score": 101},
        {"hook_score": -1},
        {"entertainment_score": 150},
        {"clarity_score": -5},
        {"payoff_score": 1000},
        {"completeness_score": -100},
    ],
)
def test_candidate_constraints(db_session: Session, overrides: dict):
    run = make_run(db_session)
    rank = overrides.pop("rank", 1)
    with pytest.raises(IntegrityError):
        attach(db_session, run, candidate(rank, 10.0, 50.0, **overrides))
    db_session.rollback()


def test_candidate_text_lengths_are_bounded(db_session: Session):
    run = make_run(db_session)
    with pytest.raises(DataError):  # value too long for character varying(120)
        attach(db_session, run, candidate(1, 10.0, 50.0, title="x" * 121))
    db_session.rollback()


def test_decision_can_be_recorded(db_session: Session):
    run = make_run(db_session)
    attach(db_session, run, candidate(1, 10.0, 50.0))
    item = run.candidates[0]
    item.decision = CandidateDecision.SAVED
    item.decided_at = datetime.now(UTC)
    db_session.commit()
    db_session.refresh(item)

    assert item.decision == "saved" and item.decided_at is not None


# --- cascades -----


def test_deleting_a_run_deletes_its_candidates(db_session: Session):
    run = make_run(db_session)
    attach(db_session, run, candidate(1, 10.0, 50.0), candidate(2, 60.0, 90.0))
    run_id = run.id

    db_session.delete(run)
    db_session.commit()

    assert (
        db_session.scalars(select(ClipCandidate).where(ClipCandidate.run_id == run_id)).all() == []
    )


def test_deleting_a_video_deletes_runs_and_candidates_but_not_other_videos(db_session: Session):
    video = make_video(db_session)
    run = make_run(db_session, video)
    attach(db_session, run, candidate(1, 10.0, 50.0))
    other = make_run(db_session)
    attach(db_session, other, candidate(1, 10.0, 50.0))

    video_id, run_id, other_id = video.id, run.id, other.id
    db_session.delete(video)
    db_session.commit()
    db_session.expunge_all()  # read back from the database, not the identity map

    assert db_session.get(ClipDetectionRun, run_id) is None
    assert (
        db_session.scalars(select(ClipCandidate).where(ClipCandidate.video_id == video_id)).all()
        == []
    )
    assert db_session.get(ClipDetectionRun, other_id) is not None
    assert len(db_session.get(ClipDetectionRun, other_id).candidates) == 1


def test_deleting_the_transcript_removes_runs_derived_from_it(db_session: Session):
    """Candidates are derived from a transcript snapshot; without it they have no provenance."""
    video = make_video(db_session)
    transcription = make_transcription(db_session, video)
    run = make_run(db_session, video)

    video_id, run_id = video.id, run.id
    db_session.delete(transcription)
    db_session.commit()
    db_session.expunge_all()

    assert db_session.get(ClipDetectionRun, run_id) is None
    assert db_session.get(Video, video_id) is not None  # the source video is untouched


def test_run_failure_fields_are_bounded_and_safe(db_session: Session):
    run = make_run(
        db_session, status="failed", error_code="provider_unreachable", error_message="x" * 500
    )
    db_session.refresh(run)
    assert run.error_message == "x" * 500
    assert run.status == ClipDetectionStatus.FAILED
