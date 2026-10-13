import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ACTIVE_TRANSCRIPTION_STATUSES,
    Project,
    Transcription,
    TranscriptionStatus,
    TranscriptSegment,
    User,
    Video,
)


def make_video(db_session: Session) -> Video:
    user = User(email="creator@example.com", password_hash="x")
    project = Project(name="Stream", owner=user)
    video = Video(
        project=project,
        original_filename="stream.mp4",
        storage_key=f"videos/{uuid.uuid4().hex}.mp4",
        content_type="video/mp4",
        file_size=1234,
        status="ready",
    )
    db_session.add_all([user, video])
    db_session.commit()
    return video


def make_transcription(db_session: Session, video: Video | None = None) -> Transcription:
    video = video or make_video(db_session)
    transcription = Transcription(video=video, provider="faster_whisper", model="small")
    db_session.add(transcription)
    db_session.commit()
    return transcription


def segment(index: int, start: float, end: float, text: str = "words") -> TranscriptSegment:
    return TranscriptSegment(sequence_index=index, start_time=start, end_time=end, text=text)


# --- transcription -----


def test_transcription_defaults(db_session: Session):
    transcription = make_transcription(db_session)

    assert isinstance(transcription.id, uuid.UUID)
    assert transcription.status == TranscriptionStatus.QUEUED == "queued"
    assert transcription.progress_percent == 0
    assert transcription.full_text is None
    assert transcription.language is None and transcription.language_probability is None
    assert transcription.error_code is None and transcription.error_message is None
    assert transcription.celery_task_id is None
    assert transcription.audio_storage_key is None
    assert transcription.created_at.tzinfo is not None
    assert transcription.started_at is None
    assert transcription.completed_at is None
    assert transcription.heartbeat_at is None


def test_status_state_machine_values():
    assert [s.value for s in TranscriptionStatus] == [
        "queued",
        "extracting_audio",
        "transcribing",
        "completed",
        "failed",
    ]
    assert set(ACTIVE_TRANSCRIPTION_STATUSES) == {"queued", "extracting_audio", "transcribing"}
    assert TranscriptionStatus.COMPLETED not in ACTIVE_TRANSCRIPTION_STATUSES


def test_video_has_one_current_transcription(db_session: Session):
    transcription = make_transcription(db_session)
    db_session.expire_all()

    video = db_session.get(Video, transcription.video_id)
    assert video.transcription is transcription
    assert transcription.video is video

    db_session.add(Transcription(video_id=video.id, provider="openai", model="whisper-1"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_progress_must_be_a_percentage(db_session: Session):
    transcription = make_transcription(db_session)

    transcription.progress_percent = 101
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- segments -----


def test_segments_are_ordered_by_sequence_index(db_session: Session):
    transcription = make_transcription(db_session)
    transcription.segments.extend(
        [
            segment(2, 20.0, 25.5, "third"),
            segment(0, 0.0, 4.2, "first"),
            segment(1, 4.2, 20.0, "second"),
        ]
    )
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.get(Transcription, transcription.id)
    assert [s.text for s in reloaded.segments] == ["first", "second", "third"]
    assert [s.start_time for s in reloaded.segments] == [0.0, 4.2, 20.0]
    assert all(s.speaker is None for s in reloaded.segments)
    assert reloaded.segments[0].created_at.tzinfo is not None


def test_segment_timestamps_must_be_valid(db_session: Session):
    transcription = make_transcription(db_session)

    transcription.segments.append(segment(0, -0.5, 2.0))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    transcription = db_session.get(Transcription, transcription.id)
    transcription.segments.append(segment(0, 5.0, 5.0))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    transcription = db_session.get(Transcription, transcription.id)
    transcription.segments.append(segment(0, 7.0, 6.0))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_sequence_index_is_unique_per_transcription(db_session: Session):
    transcription = make_transcription(db_session)
    transcription.segments.extend([segment(0, 0.0, 1.0), segment(0, 1.0, 2.0)])

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_same_sequence_index_allowed_across_transcriptions(db_session: Session):
    first = make_transcription(db_session)
    second_video = make_video_for_other_user(db_session)
    second = make_transcription(db_session, second_video)
    first.segments.append(segment(0, 0.0, 1.0))
    second.segments.append(segment(0, 0.0, 1.0))

    db_session.commit()

    assert db_session.scalar(select(TranscriptSegment).where(TranscriptSegment.sequence_index == 0))


def make_video_for_other_user(db_session: Session) -> Video:
    user = User(email="other@example.com", password_hash="x")
    project = Project(name="Other", owner=user)
    video = Video(
        project=project,
        original_filename="o.mp4",
        storage_key=f"videos/{uuid.uuid4().hex}.mp4",
        content_type="video/mp4",
        file_size=1,
        status="ready",
    )
    db_session.add_all([user, video])
    db_session.commit()
    return video


def test_long_video_timestamps_and_unicode_text(db_session: Session):
    transcription = make_transcription(db_session)
    transcription.segments.append(segment(0, 3 * 3600 + 5.25, 3 * 3600 + 9.75, "مرحبا — ça va? 🎬"))
    db_session.commit()
    db_session.expire_all()

    stored = db_session.get(Transcription, transcription.id).segments[0]
    assert stored.start_time == pytest.approx(10805.25)
    assert stored.end_time == pytest.approx(10809.75)
    assert stored.text == "مرحبا — ça va? 🎬"


# --- cascades -----


def test_deleting_video_deletes_transcription_and_segments(db_session: Session):
    transcription = make_transcription(db_session)
    transcription.segments.append(segment(0, 0.0, 1.0))
    db_session.commit()
    transcription_id, video = transcription.id, transcription.video

    db_session.delete(video)
    db_session.commit()

    assert db_session.get(Transcription, transcription_id) is None
    assert db_session.scalar(select(TranscriptSegment)) is None


def test_deleting_transcription_keeps_the_video(db_session: Session):
    transcription = make_transcription(db_session)
    transcription.segments.append(segment(0, 0.0, 1.0))
    db_session.commit()
    video_id = transcription.video_id

    db_session.delete(transcription)
    db_session.commit()
    db_session.expire_all()

    assert db_session.get(Video, video_id) is not None
    assert db_session.get(Video, video_id).transcription is None
    assert db_session.scalar(select(TranscriptSegment)) is None


def test_deleting_user_cascades_to_transcripts(db_session: Session):
    transcription = make_transcription(db_session)
    transcription.segments.append(segment(0, 0.0, 1.0))
    db_session.commit()
    transcription_id = transcription.id

    db_session.delete(transcription.video.project.owner)
    db_session.commit()

    assert db_session.get(Transcription, transcription_id) is None
    assert db_session.scalar(select(TranscriptSegment)) is None
