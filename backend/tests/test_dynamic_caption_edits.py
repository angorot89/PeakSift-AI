"""Dynamic (caption_v2) captions in edits: configuration, persistence, API, the render pipeline
and real end-to-end renders for every layout (captions fixed in output space)."""

import math
import subprocess
import uuid
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, get_settings
from app.models import CaptionTrack, CaptionTrackStatus, CaptionWord, ClipEdit, ClipEditStatus
from app.services.clip_edit.config import (
    CAPTION_RENDERER_V1,
    CAPTION_RENDERER_V2,
    CaptionTiming,
    DynamicPreset,
    EditConfig,
)
from app.services.clip_edit.pipeline import run_clip_edit
from app.services.storage import LocalStorageProvider
from tests.media_fixtures import FFMPEG, requires_ffmpeg, requires_libass
from tests.test_caption_track_model import make_track
from tests.test_clip_edit_api import ready_clip, sign_up
from tests.test_clip_edit_caption_render import plain_source
from tests.test_clip_edit_model import make_clip, make_edit
from tests.test_clip_edit_pipeline import SpyComposer, execute
from tests.test_clip_edit_pipeline import make_edit as make_pipeline_edit
from tests.test_smart_reframe_render import completed_analysis


@pytest.fixture
def settings() -> Settings:
    return Settings(**get_settings().model_dump())


@pytest.fixture
def storage() -> LocalStorageProvider:
    return LocalStorageProvider(Path(get_settings().media_root))


@pytest.fixture(autouse=True)
def clean_media_root(storage: LocalStorageProvider):
    yield
    for path in sorted(storage.root.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            path.rmdir()


WORDS = [("ONE", 0.4, 0.9), ("TWO", 0.9, 1.4), ("THREE", 1.4, 1.9)]
YELLOW = np.array([0xFF, 0xD4, 0x3B])


def config(**kwargs) -> EditConfig:
    fields = {"layout": "center_crop", "captions_enabled": True, "caption_style": "focus"}
    fields.update(kwargs)
    return EditConfig.create(**fields)


def add_completed_track(db, clip, words=WORDS) -> CaptionTrack:
    track = make_track(db, clip)
    track.status, track.progress_percent, track.word_count = (
        CaptionTrackStatus.COMPLETED,
        100,
        len(words),
    )
    for i, (text, start, end) in enumerate(words):
        db.add(
            CaptionWord(
                track=track,
                sequence_index=i,
                start_time=start,
                end_time=end,
                text=text,
                confidence=0.9,
            )
        )
    db.commit()
    return track


def use_config(db, edit: ClipEdit, cfg: EditConfig) -> ClipEdit:
    """Point a test edit at a configuration, keeping the columns consistent."""
    edit.config, edit.config_fingerprint = cfg.snapshot(), cfg.fingerprint()
    edit.layout = cfg.layout.value
    edit.captions_enabled = cfg.captions_enabled
    edit.caption_style = cfg.caption_style.value if cfg.caption_style else None
    edit.caption_position = cfg.caption_position.value if cfg.caption_position else None
    edit.caption_renderer = cfg.caption_renderer
    edit.caption_timing = cfg.caption_timing.value if cfg.caption_timing else None
    edit.caption_track_id = uuid.UUID(cfg.caption_track_id) if cfg.caption_track_id else None
    edit.reframe_analysis_id = (
        uuid.UUID(cfg.reframe_analysis_id) if cfg.reframe_analysis_id else None
    )
    edit.focus_x, edit.focus_y = cfg.focus_x, cfg.focus_y
    if cfg.hook:
        edit.hook_enabled, edit.hook_text, edit.hook_style = (
            True,
            cfg.hook.text,
            cfg.hook.style.value,
        )
        edit.hook_position, edit.hook_duration_seconds = cfg.hook.position.value, cfg.hook.duration
    db.commit()
    return edit


# --- configuration -----


def test_dynamic_styles_select_the_dynamic_renderer_and_need_their_timing():
    track = uuid.uuid4()
    aligned = config(caption_track_id=track)
    assert (
        aligned.caption_renderer == CAPTION_RENDERER_V2
        and aligned.caption_style == DynamicPreset.FOCUS
    )
    assert aligned.caption_timing == CaptionTiming.ALIGNED_WORD and aligned.caption_track_id == str(
        track
    )
    captions = aligned.snapshot()["captions"]
    assert captions == {
        "enabled": True,
        "style": "focus",
        "position": "bottom",
        "renderer": "caption_v2",
        "timing": "aligned_word",
        "safe_area": "general_social_v1",
        "track_id": str(track),
    }
    assert EditConfig.from_snapshot(aligned.snapshot()) == aligned
    with pytest.raises(ValueError, match="word timing"):
        config()  # aligned (the default) without a track
    phrase = config(caption_timing="phrase_fallback", caption_track_id=track)
    assert phrase.caption_track_id is None and "track_id" not in phrase.snapshot()["captions"]


def test_v1_styles_keep_their_v06_snapshots_and_fingerprints():
    v1 = config(
        layout="blur_background",
        caption_style="bold",
        caption_timing="phrase_fallback",
        caption_track_id=uuid.uuid4(),
    )
    assert (
        v1.caption_renderer == CAPTION_RENDERER_V1
        and v1.caption_timing is None
        and v1.caption_track_id is None
    )
    assert set(v1.snapshot()["captions"]) == {"enabled", "style", "position"}
    assert v1.fingerprint().startswith("a8c24dde")


def test_everything_that_changes_the_picture_changes_the_fingerprint():
    a, b = uuid.uuid4(), uuid.uuid4()
    base = config(caption_track_id=a)
    variants = [
        config(caption_track_id=b),  # another track
        config(caption_track_id=a, caption_style="punch"),
        config(caption_track_id=a, caption_position="top"),
        config(caption_timing="phrase_fallback"),
        config(caption_track_id=a, hook_enabled=True, hook_text="Watch this"),
        config(caption_track_id=a, layout="blur_background"),
    ]
    assert len({base.fingerprint(), *(v.fingerprint() for v in variants)}) == 7
    assert config(caption_track_id=a).fingerprint() == base.fingerprint()  # idempotent


# --- persistence -----


@pytest.mark.parametrize(
    "overrides",
    [
        {"caption_style": "focus", "caption_renderer": "caption_v1"},  # v2 preset, v1 renderer
        {"caption_renderer": "caption_v2"},  # v1 style (bold), v2 renderer
        {"caption_renderer": None},  # captions on, no renderer
        {"caption_timing": "aligned_word"},  # v1 edit with a timing
    ],
)
def test_caption_columns_are_consistent(db_session, overrides):
    with pytest.raises(IntegrityError):
        make_edit(
            db_session, make_clip(db_session), **{"caption_renderer": "caption_v1", **overrides}
        )
    db_session.rollback()


def test_word_synced_edits_name_their_track_and_phrase_ones_do_not(db_session):
    clip = make_clip(db_session)
    track = add_completed_track(db_session, clip)
    good = make_edit(
        db_session,
        clip,
        config=config(caption_track_id=track.id),
        caption_style="focus",
        caption_renderer="caption_v2",
        caption_timing="aligned_word",
        caption_track_id=track.id,
    )
    assert good.caption_track_id == track.id
    for bad in (
        {"caption_timing": "aligned_word", "caption_track_id": None},
        {"caption_timing": "phrase_fallback", "caption_track_id": track.id},
        {"caption_timing": None, "caption_track_id": None},
    ):
        with pytest.raises(IntegrityError):
            make_edit(
                db_session,
                clip,
                config=config(caption_timing="phrase_fallback"),
                caption_style="focus",
                caption_renderer="caption_v2",
                **bad,
            )
        db_session.rollback()


# --- API -----


def test_api_creates_word_synced_edits_only_from_this_clips_completed_track(client, db_session):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    other = ready_clip(db_session, "owner@example.com")
    track = add_completed_track(db_session, ctx["clip"])
    foreign = add_completed_track(db_session, other["clip"])
    body = {
        "layout": "center_crop",
        "captions_enabled": True,
        "caption_style": "focus",
        "caption_track_id": str(track.id),
    }
    created = client.post(ctx["base"], json=body)
    assert created.status_code == 201
    data = created.json()
    assert (data["caption_renderer"], data["caption_timing"], data["caption_track_id"]) == (
        "caption_v2",
        "aligned_word",
        str(track.id),
    )
    assert client.post(ctx["base"], json=body).status_code == 200
    # Another clip's track is indistinguishable from a missing one.
    for track_id in (str(foreign.id), str(uuid.uuid4())):
        response = client.post(ctx["base"], json={**body, "caption_track_id": track_id})
        assert response.status_code == 409 and "word timing" in response.json()["detail"]
    track.status = CaptionTrackStatus.ALIGNING
    db_session.commit()
    assert client.post(ctx["base"], json={**body, "caption_style": "punch"}).status_code == 409
    assert client.post(ctx["base"], json={**body, "caption_track_id": None}).status_code == 422


def test_word_synced_captions_do_not_need_the_transcript_but_phrase_timing_does(client, db_session):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com", transcript=False)
    track = add_completed_track(db_session, ctx["clip"])
    word = {
        "layout": "fit",
        "captions_enabled": True,
        "caption_style": "minimal",
        "caption_track_id": str(track.id),
    }
    assert client.post(ctx["base"], json=word).status_code == 201
    phrase = {
        "layout": "fit",
        "captions_enabled": True,
        "caption_style": "minimal",
        "caption_timing": "phrase_fallback",
    }
    response = client.post(ctx["base"], json=phrase)
    assert response.status_code == 409 and "transcript" in response.json()["detail"]


# --- pipeline (fake composer) -----


def dynamic_pipeline_edit(db, storage, **kwargs):
    edit = make_pipeline_edit(db, storage, captions=False)
    track = add_completed_track(db, edit.clip)
    return use_config(db, edit, config(caption_track_id=track.id, **kwargs)), track


def test_word_synced_edits_render_the_tracks_words_with_the_dynamic_renderer(
    db_session, settings, storage
):
    edit, _ = dynamic_pipeline_edit(db_session, storage)
    composer = SpyComposer(db_session, edit)
    result = execute(edit, db_session, settings, storage, composer)
    assert result.status == ClipEditStatus.READY and result.caption_cue_count == 1
    text = composer.captions_text
    assert "Style: Dynamic,Noto Sans,112," in text and "Style: Caption," not in text
    events = [line for line in text.splitlines() if line.startswith("Dialogue: 0,")]
    assert len(events) == 3 and all(
        "ONE" in e and "THREE" in e for e in events
    )  # one per active word
    assert events[0].split(",")[1] == "0:00:00.40"  # timed by the track, clip-local


def test_phrase_timed_dynamic_edits_never_highlight_words(db_session, settings, storage):
    edit = make_pipeline_edit(db_session, storage, captions=False)
    use_config(db_session, edit, config(caption_timing="phrase_fallback", caption_style="boxed"))
    composer = SpyComposer(db_session, edit)
    execute(edit, db_session, settings, storage, composer)
    text = composer.captions_text
    assert "Style: Dynamic," in text and "\\1c" not in text and "Dialogue: 0," in text


def test_an_unusable_track_fails_the_render_safely(db_session, settings, storage):
    edit, track = dynamic_pipeline_edit(db_session, storage)
    track.status = CaptionTrackStatus.FAILED
    db_session.commit()
    result = execute(edit, db_session, settings, storage, SpyComposer(db_session, edit))
    assert (
        result.status == ClipEditStatus.FAILED and result.error_code == "caption_track_unavailable"
    )


def test_invalid_persisted_words_are_refused_before_ffmpeg(db_session, settings, storage):
    edit, track = dynamic_pipeline_edit(db_session, storage)
    # PostgreSQL sorts NaN above every number, so "end > start" accepts it; the pipeline must not.
    db_session.add(
        CaptionWord(track=track, sequence_index=9, start_time=2.0, end_time=math.nan, text="bad")
    )
    db_session.commit()
    composer = SpyComposer(db_session, edit)
    result = execute(edit, db_session, settings, storage, composer)
    assert result.status == ClipEditStatus.FAILED and result.error_code == "caption_track_invalid"
    assert composer.calls == []


def test_v1_edits_still_render_with_the_v06_renderer(db_session, settings, storage):
    edit = make_pipeline_edit(db_session, storage, captions=True)
    composer = SpyComposer(db_session, edit)
    execute(edit, db_session, settings, storage, composer)
    assert (
        "Style: Caption,Noto Sans,80," in composer.captions_text
        and "Dynamic" not in composer.captions_text
    )


# --- real end-to-end renders -----


def frame(path: Path, t: float) -> np.ndarray:
    raw = subprocess.run(
        [
            FFMPEG, "-v", "error", "-ss", f"{t:.2f}", "-i", str(path),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        capture_output=True, check=True, timeout=60,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, np.uint8).reshape(1920, 1080, 3).astype(int)


@requires_ffmpeg
@requires_libass
@pytest.mark.parametrize(
    "layout", ["center_crop", "blur_background", "smart_reframe", "manual_crop"]
)
@pytest.mark.parametrize("audio", [True, False])
def test_real_word_synced_render_for_every_layout(db_session, settings, storage, layout, audio):
    edit = make_pipeline_edit(db_session, storage, captions=False)
    clip_file = storage.path_for(edit.clip.storage_key)
    plain_source(
        clip_file, seconds=3.0, audio=audio
    )  # a plain picture: the highlight colour stands out
    edit.clip.audio_codec = "aac" if audio else None
    track = add_completed_track(db_session, edit.clip)
    extra = {}
    if layout == "smart_reframe":
        extra["reframe_analysis_id"] = completed_analysis(db_session, edit.clip).id
    if layout == "manual_crop":
        extra.update(focus_x=0.3, focus_y=0.5)
    use_config(
        db_session,
        edit,
        config(
            layout=layout,
            caption_track_id=track.id,
            hook_enabled=True,
            hook_text="Watch this",
            **extra,
        ),
    )

    result = run_clip_edit(
        edit.id, db_session, settings=settings, storage=storage, task_id="task-1"
    )
    assert result.status == ClipEditStatus.READY, result.error_message
    assert (result.width, result.height, result.video_codec) == (1080, 1920, "h264")
    assert (
        result.audio_codec == ("aac" if audio else None)
        and abs(result.duration_seconds - 3.0) <= 0.5
    )
    path = storage.path_for(result.storage_key)
    assert sorted(p.name for p in path.parent.iterdir()) == [
        "edited.mp4"
    ]  # no ASS or temp files left
    centres, boxes = [], []
    for t in (0.7, 1.2, 1.7):  # ONE, TWO, THREE active
        f = frame(path, t)
        active = np.abs(f - YELLOW).max(axis=2) < 50
        bottom = active[1000:1600]
        assert bottom.sum() > 300, (layout, t)
        centres.append(np.nonzero(bottom)[1].mean())
        rows = np.nonzero(active)[0]
        boxes.append((rows.min(), rows.max()))
        top = f[150:450]
        assert (top.max(axis=2) > 230).sum() > 500, "the hook is drawn at the top during its time"
    assert centres[0] < centres[1] < centres[2], (layout, centres)  # the emphasis follows the words
    # Captions live in output space: same rows in every frame, whatever the layout does.
    assert max(b[0] for b in boxes) - min(b[0] for b in boxes) <= 6, boxes


@pytest.mark.parametrize(
    "overrides",
    [
        # A CHECK that evaluates to NULL accepts the row: every one of these used to slip through.
        {"captions_enabled": True, "caption_style": "bold", "caption_renderer": None},
        {"caption_style": "focus", "caption_renderer": "caption_v2", "caption_timing": None},
        {
            "hook_enabled": True,
            "hook_text": "Hi",
            "hook_style": None,
            "hook_position": "top",
            "hook_duration_seconds": 2.0,
        },
        {
            "hook_enabled": True,
            "hook_text": "Hi",
            "hook_style": "boxed",
            "hook_position": None,
            "hook_duration_seconds": 2.0,
        },
        {
            "hook_enabled": True,
            "hook_text": "Hi",
            "hook_style": "boxed",
            "hook_position": "top",
            "hook_duration_seconds": None,
        },
    ],
)
def test_constraints_have_no_null_loopholes(db_session, overrides):
    with pytest.raises(IntegrityError):
        make_edit(
            db_session, make_clip(db_session), **{"caption_renderer": "caption_v1", **overrides}
        )
    db_session.rollback()
