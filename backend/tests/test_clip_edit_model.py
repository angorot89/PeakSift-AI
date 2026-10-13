import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ACTIVE_CLIP_EDIT_STATUSES,
    Clip,
    ClipCandidate,
    ClipDetectionRun,
    ClipEdit,
    ClipEditStatus,
    Project,
    Transcription,
    User,
    Video,
)
from app.services.clip_edit.config import (
    CONFIG_VERSION,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    RENDER_PROFILE_VERTICAL_V1,
    CaptionPosition,
    CaptionStyle,
    EditConfig,
    Layout,
)


def make_clip(db_session: Session) -> Clip:
    user = User(email=f"creator-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    project = Project(name="Stream", owner=user)
    video = Video(
        project=project,
        original_filename="stream.mp4",
        storage_key=f"videos/{uuid.uuid4().hex}.mp4",
        content_type="video/mp4",
        file_size=1,
        status="ready",
        duration_seconds=300.0,
    )
    transcription = Transcription(video=video, provider="fake", model="fake-1", status="completed")
    run = ClipDetectionRun(
        video=video,
        transcription=transcription,
        transcript_fingerprint="f" * 64,
        provider="ollama",
        model="m",
        config={},
        status="completed",
    )
    db_session.add_all([user, video, transcription, run])
    db_session.flush()
    candidate = ClipCandidate(
        run=run,
        video_id=video.id,
        start_time=30.0,
        end_time=50.0,
        duration_seconds=20.0,
        title="Moment",
        hook="h",
        rationale="r",
        category="story",
        transcript_excerpt="x",
        overall_score=80,
        hook_score=80,
        entertainment_score=80,
        clarity_score=80,
        payoff_score=80,
        completeness_score=80,
        rank=1,
    )
    clip = Clip(
        candidate=candidate,
        video_id=video.id,
        start_time=30.0,
        end_time=50.0,
        duration_seconds=20.0,
        status="ready",
    )
    db_session.add_all([candidate, clip])
    db_session.commit()
    return clip


def make_edit(
    db_session: Session, clip: Clip, config: EditConfig | None = None, **overrides
) -> ClipEdit:
    config = config or EditConfig.create(
        layout="blur_background",
        captions_enabled=True,
        caption_style="bold",
        caption_position="bottom",
    )
    fields = {
        "clip": clip,
        "video_id": clip.video_id,
        "config": config.snapshot(),
        "config_fingerprint": config.fingerprint(),
        "aspect_ratio": config.aspect_ratio.value,
        "layout": config.layout.value,
        "captions_enabled": config.captions_enabled,
        "caption_style": config.caption_style.value if config.caption_style else None,
        "caption_position": config.caption_position.value if config.caption_position else None,
        "output_width": OUTPUT_WIDTH,
        "output_height": OUTPUT_HEIGHT,
        "render_profile": RENDER_PROFILE_VERTICAL_V1,
    }
    fields.update(overrides)
    edit = ClipEdit(**fields)
    db_session.add(edit)
    db_session.commit()
    return edit


# --- configuration -----


def test_config_snapshot_is_explicit_and_versioned():
    config = EditConfig.create(
        layout="blur_background",
        captions_enabled=True,
        caption_style="bold",
        caption_position="bottom",
    )
    assert config.snapshot() == {
        "version": CONFIG_VERSION,
        "aspect_ratio": "9:16",
        "layout": "blur_background",
        "output": {"width": 1080, "height": 1920},
        "captions": {"enabled": True, "style": "bold", "position": "bottom"},
    }
    assert EditConfig.from_snapshot(config.snapshot()) == config


def test_captions_off_drops_style_and_position_so_equivalent_requests_match():
    a = EditConfig.create(
        layout="center_crop", captions_enabled=False, caption_style="bold", caption_position="top"
    )
    b = EditConfig.create(layout="center_crop", captions_enabled=False)
    assert a == b and a.fingerprint() == b.fingerprint()
    assert a.caption_style is None and a.caption_position is None


def test_caption_defaults_are_explicit_in_the_snapshot():
    config = EditConfig.create(layout="center_crop", captions_enabled=True)
    assert (
        config.caption_style == CaptionStyle.BOLD
        and config.caption_position == CaptionPosition.BOTTOM
    )
    explicit = EditConfig.create(
        layout="center_crop", captions_enabled=True, caption_style="bold", caption_position="bottom"
    )
    assert config.fingerprint() == explicit.fingerprint()


def test_different_configurations_have_different_fingerprints():
    configs = {
        EditConfig.create(
            layout=layout, captions_enabled=enabled, caption_style=style, caption_position=position
        ).fingerprint()
        for layout in Layout
        for enabled in (True, False)
        for style in CaptionStyle
        for position in CaptionPosition
    }
    # 3 layouts × (9 caption combinations + 1 captions-off) = 30 distinct configurations
    assert len(configs) == 30
    assert all(len(f) == 64 for f in configs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"layout": "stretch", "captions_enabled": False},
        {"layout": "center_crop", "captions_enabled": False, "aspect_ratio": "16:9"},
        {"layout": "center_crop", "captions_enabled": True, "caption_style": "comic-sans"},
        {"layout": "center_crop", "captions_enabled": True, "caption_position": "left"},
        {"layout": "scale=iw*2:ih*2,drawtext=text=x", "captions_enabled": False},
        {"layout": "center_crop", "captions_enabled": "yes"},
        {"layout": "center_crop", "captions_enabled": True, "caption_style": "{\\fnArial}"},
    ],
)
def test_anything_outside_the_allow_lists_is_refused(kwargs):
    with pytest.raises(ValueError):
        EditConfig.create(**kwargs)


def test_unknown_snapshot_versions_are_refused():
    with pytest.raises(ValueError):
        EditConfig.from_snapshot({"version": 99, "layout": "fit"})


# --- model -----


def test_edit_defaults(db_session: Session):
    clip = make_clip(db_session)
    edit = make_edit(db_session, clip)

    assert isinstance(edit.id, uuid.UUID)
    assert edit.status == ClipEditStatus.QUEUED == "queued"
    assert edit.progress_percent == 0 and edit.attempt == 1
    assert (edit.output_width, edit.output_height) == (1080, 1920)
    assert edit.render_profile == "vertical_1080x1920_v1" and edit.content_type == "video/mp4"
    assert edit.storage_key is None and edit.file_size is None and edit.celery_task_id is None
    assert edit.config["captions"] == {"enabled": True, "style": "bold", "position": "bottom"}
    assert edit.created_at.tzinfo is not None


def test_status_values():
    assert [s.value for s in ClipEditStatus] == [
        "queued",
        "rendering",
        "validating",
        "ready",
        "failed",
    ]
    assert ClipEditStatus.READY not in ACTIVE_CLIP_EDIT_STATUSES
    assert ClipEditStatus.FAILED not in ACTIVE_CLIP_EDIT_STATUSES


def test_same_configuration_twice_is_refused_by_the_database(db_session: Session):
    clip = make_clip(db_session)
    make_edit(db_session, clip)
    with pytest.raises(IntegrityError):
        make_edit(db_session, clip)
    db_session.rollback()


def test_a_clip_can_have_several_variants(db_session: Session):
    clip = make_clip(db_session)
    make_edit(db_session, clip)
    make_edit(
        db_session,
        clip,
        EditConfig.create(
            layout="center_crop",
            captions_enabled=True,
            caption_style="clean",
            caption_position="center",
        ),
    )
    make_edit(db_session, clip, EditConfig.create(layout="fit", captions_enabled=False))
    db_session.refresh(clip)
    assert len(clip.edits) == 3
    assert {e.layout for e in clip.edits} == {"blur_background", "center_crop", "fit"}


def test_same_configuration_on_another_clip_is_independent(db_session: Session):
    make_edit(db_session, make_clip(db_session))
    make_edit(db_session, make_clip(db_session))  # must not raise


@pytest.mark.parametrize(
    "overrides",
    [
        {"layout": "stretch"},
        {"aspect_ratio": "16:9"},
        {"caption_style": "comic"},
        {"captions_enabled": False},  # style/position must then be NULL
        {"caption_position": None},  # enabled captions need a position
        {"progress_percent": 101},
        {"attempt": 0},
        {"output_width": 0},
    ],
)
def test_database_constraints_back_the_allow_lists(db_session: Session, overrides: dict):
    clip = make_clip(db_session)
    with pytest.raises(IntegrityError):
        make_edit(db_session, clip, **overrides)
    db_session.rollback()


def test_deleting_a_clip_deletes_its_edits_but_not_the_video(db_session: Session):
    clip = make_clip(db_session)
    edit = make_edit(db_session, clip)
    clip_id, edit_id, video_id = clip.id, edit.id, clip.video_id
    db_session.delete(clip)
    db_session.commit()
    db_session.expunge_all()
    assert db_session.get(ClipEdit, edit_id) is None
    assert db_session.get(Video, video_id) is not None
    assert db_session.scalars(select(ClipEdit).where(ClipEdit.clip_id == clip_id)).all() == []


def test_deleting_an_edit_never_touches_the_source_clip(db_session: Session):
    clip = make_clip(db_session)
    edit = make_edit(db_session, clip)
    clip_id = clip.id
    db_session.delete(edit)
    db_session.commit()
    db_session.expunge_all()
    source = db_session.get(Clip, clip_id)
    assert source is not None and source.status == "ready"
