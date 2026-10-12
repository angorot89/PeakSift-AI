import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Project, User, Video, VideoStatus


def make_project(db_session: Session) -> Project:
    user = User(email="creator@example.com", password_hash="not-a-real-hash")
    project = Project(name="Stream highlights", owner=user)
    db_session.add(user)
    db_session.commit()
    return project


def make_video(project: Project, key: str = "videos/abc.mp4") -> Video:
    return Video(
        project=project,
        original_filename="stream.mp4",
        storage_key=key,
        content_type="video/mp4",
        file_size=12_345,
    )


def test_video_defaults(db_session: Session):
    project = make_project(db_session)
    video = make_video(project)
    db_session.add(video)
    db_session.commit()

    assert isinstance(video.id, uuid.UUID)
    assert video.project_id == project.id
    assert video.status == VideoStatus.UPLOADED == "uploaded"
    assert video.error_message is None
    assert video.created_at.tzinfo is not None
    assert video.updated_at >= video.created_at


def test_metadata_fields_are_empty_until_probed_and_can_be_filled(db_session: Session):
    project = make_project(db_session)
    video = make_video(project)
    db_session.add(video)
    db_session.commit()

    assert (video.duration_seconds, video.width, video.height, video.fps) == (None,) * 4
    assert (video.video_codec, video.audio_codec) == (None, None)

    video.duration_seconds = 8040.5
    video.width, video.height, video.fps = 1920, 1080, 29.97
    video.video_codec, video.audio_codec = "h264", "aac"
    video.status = VideoStatus.READY
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.get(Video, video.id)
    assert reloaded is not None
    assert reloaded.duration_seconds == pytest.approx(8040.5)
    assert (reloaded.width, reloaded.height) == (1920, 1080)
    assert reloaded.fps == pytest.approx(29.97)
    assert (reloaded.video_codec, reloaded.audio_codec, reloaded.status) == ("h264", "aac", "ready")


def test_file_size_supports_multi_gigabyte_files(db_session: Session):
    project = make_project(db_session)
    video = make_video(project)
    video.file_size = 6 * 1024**3  # 6 GiB, beyond a 32-bit integer
    db_session.add(video)
    db_session.commit()
    db_session.expire_all()

    assert db_session.get(Video, video.id).file_size == 6 * 1024**3


def test_project_video_relationship(db_session: Session):
    project = make_project(db_session)
    project.videos.extend(
        [make_video(project, "videos/a.mp4"), make_video(project, "videos/b.mp4")]
    )
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.scalar(select(Project).where(Project.id == project.id))
    assert reloaded is not None
    assert sorted(v.storage_key for v in reloaded.videos) == ["videos/a.mp4", "videos/b.mp4"]
    assert all(v.project is reloaded for v in reloaded.videos)


def test_storage_key_must_be_unique(db_session: Session):
    project = make_project(db_session)
    db_session.add(make_video(project, "videos/same.mp4"))
    db_session.commit()

    db_session.add(make_video(project, "videos/same.mp4"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_deleting_project_deletes_its_videos(db_session: Session):
    project = make_project(db_session)
    video = make_video(project)
    db_session.add(video)
    db_session.commit()
    video_id = video.id

    db_session.delete(project)
    db_session.commit()

    assert db_session.get(Video, video_id) is None


def test_deleting_user_cascades_through_projects_to_videos(db_session: Session):
    project = make_project(db_session)
    video = make_video(project)
    db_session.add(video)
    db_session.commit()
    video_id, user = video.id, project.owner

    db_session.delete(user)
    db_session.commit()

    assert db_session.get(Video, video_id) is None
