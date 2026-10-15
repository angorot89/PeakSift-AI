"""Edits with an audio section, rendered end to end through the real pipeline (FFmpeg, libass)
and measured on the encoded short: music, ducking, effects, loudness, silent clips, failures,
attempt ownership, and the full audiovisual combination with smart reframe and captions."""

import subprocess
import uuid
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import AudioAsset, ClipEdit, ClipEditStatus
from app.services.audio_mix.loudness import TARGET_I, measure_loudness
from app.services.clip_edit import pipeline as pipeline_module
from app.services.clip_edit.config import EditConfig
from app.services.clip_edit.pipeline import run_clip_edit
from app.services.clip_render.pipeline import render_options_from
from app.services.storage import LocalMediaStorage
from tests.audio_fixtures import RATE, amplitude, db, decode, ffmpeg
from tests.media_fixtures import requires_ffmpeg, requires_libass
from tests.test_clip_edit_pipeline import make_edit as make_pipeline_edit
from tests.test_dynamic_caption_edits import YELLOW, add_completed_track, frame, use_config
from tests.test_smart_reframe_render import completed_analysis

pytestmark = requires_ffmpeg

SPEECH = "0.2*sin(2*PI*1000*t)*lt(mod(t\\,3)\\,1.5)"  # 1.5 s on, 1.5 s off
MUSIC = "0.5*sin(2*PI*200*t)"
BEEP = "0.6*sin(2*PI*3000*t)"


@pytest.fixture
def settings() -> Settings:
    return Settings(**get_settings().model_dump())


@pytest.fixture
def storage() -> LocalMediaStorage:
    return LocalMediaStorage(Path(get_settings().media_root))


@pytest.fixture(autouse=True)
def clean_media_root(storage: LocalMediaStorage):
    yield
    for path in sorted(storage.root.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            path.rmdir()


def clip_file(path: Path, seconds: float, audio: str | None) -> Path:
    command = [ffmpeg(), "-v", "error", "-y", "-f", "lavfi",
               "-i", f"color=c=0x203040:s=640x360:r=25:d={seconds}"]  # fmt: skip
    if audio:
        command += ["-f", "lavfi", "-i", f"aevalsrc={audio}:s=48000:d={seconds}", "-c:a", "aac"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-shortest",
                str(path)]  # fmt: skip
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return path


def add_asset(db: Session, storage: LocalMediaStorage, project_id, kind: str, expression: str,
              seconds: float) -> AudioAsset:  # fmt: skip
    key = storage.generate_key("wav", category="audio")
    path = storage.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
         f"aevalsrc={expression}:s=44100:d={seconds}", "-c:a", "pcm_s16le", str(path)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    asset = AudioAsset(
        project_id=project_id, kind=kind, display_name=f"{kind}.wav", storage_key=key,
        content_type="audio/wav", file_size=path.stat().st_size, sha256=uuid.uuid4().hex * 2,
        container="wav", codec="pcm_s16le", duration_seconds=seconds, sample_rate=44100,
        channels=1, waveform_peaks=[50],
    )  # fmt: skip
    db.add(asset)
    db.commit()
    return asset


def audio_edit(db, storage, *, seconds=6.0, source=SPEECH, audio=None, layout="center_crop",
               music=True, effects=(2.0, 4.5), **visual):  # fmt: skip
    edit = make_pipeline_edit(db, storage, captions=False)
    clip_file(storage.path_for(edit.clip.storage_key), seconds, source)
    edit.clip.end_time = edit.clip.start_time + seconds  # duration = end - start (checked)
    edit.clip.duration_seconds = seconds
    project = edit.clip.video.project_id
    section = {"sfx": []}
    if music:
        track = add_asset(db, storage, project, "music", MUSIC, 20)
        section["music"] = {"asset_id": str(track.id), "gain_db": -12, "fade_in_seconds": 0,
                            "fade_out_seconds": 0, "ducking": "medium"}  # fmt: skip
    if effects:
        hit = add_asset(db, storage, project, "sfx", BEEP, 0.25)
        section["sfx"] = [{"asset_id": str(hit.id), "at_seconds": t, "gain_db": 0} for t in effects]
    section.update(audio or {})
    config = EditConfig.create(layout=layout, captions_enabled=False, audio=section, **visual)
    return use_config(db, edit, config)


def run(edit, db, settings, storage, task_id="task-1") -> ClipEdit:
    return run_clip_edit(edit.id, db, settings=settings, storage=storage, task_id=task_id)


def onsets(samples: np.ndarray, frequency: float, step: float = 0.01) -> list[float]:
    """Times where ``frequency`` appears (10 ms resolution)."""
    times, active = [], False
    for i in range(int((len(samples) / RATE - 0.05) / step)):  # full 20 ms windows only
        level = amplitude(samples, i * step, i * step + 0.02, frequency)
        if level > 0.05 and not active:
            times.append(round(i * step, 2))
        active = level > 0.05
    return times


def test_music_ducking_effects_and_loudness_in_the_finished_short(db_session, settings, storage):
    result = run(audio_edit(db_session, storage), db_session, settings, storage)
    assert result.status == ClipEditStatus.READY, result.error_message
    assert result.audio_codec == "aac" and abs(result.duration_seconds - 6.0) <= 0.1
    path = storage.path_for(result.storage_key)
    assert sorted(p.name for p in path.parent.iterdir()) == ["edited.mp4"]  # no temp audio left
    out = decode(path)
    assert onsets(out, 3000) == pytest.approx([2.0, 4.5], abs=0.03)
    # The music dips while the clip's audio is active (0-1.5 s, 3-4.5 s) and recovers.
    ducked = db(amplitude(out, 0.6, 1.4, 200) / amplitude(out, 2.3, 2.9, 200))
    assert ducked < -6, ducked
    # Normalized to the PeakSift target, measured on the encoded short and recorded.
    assert result.audio_loudness_lufs == pytest.approx(TARGET_I, abs=1.0)
    assert result.audio_true_peak_dbtp <= -1.0
    measured = measure_loudness(path, render_options_from(settings))
    assert measured.integrated == pytest.approx(result.audio_loudness_lufs, abs=0.05)


def test_music_and_effects_on_a_clip_without_audio(db_session, settings, storage):
    edit = audio_edit(db_session, storage, source=None)
    result = run(edit, db_session, settings, storage)
    assert result.status == ClipEditStatus.READY, result.error_message
    assert result.audio_codec == "aac" and abs(result.duration_seconds - 6.0) <= 0.1
    out = decode(storage.path_for(result.storage_key))
    assert amplitude(out, 0.5, 1.5, 200) > 0.05 and onsets(out, 3000) == pytest.approx(
        [2.0, 4.5], abs=0.03
    )


def test_a_silent_clip_with_nothing_to_hear_stays_without_audio(db_session, settings, storage):
    edit = audio_edit(db_session, storage, source=None, music=False, effects=(),
                      audio={"source_gain_db": -3})  # fmt: skip
    result = run(edit, db_session, settings, storage)
    assert result.status == ClipEditStatus.READY and result.audio_codec is None
    assert result.audio_loudness_lufs is None


def test_source_only_levels_and_normalization_off(db_session, settings, storage):
    loud = "0.9*sin(2*PI*1000*t)"
    edit = audio_edit(db_session, storage, source=loud, music=False, effects=(),
                      audio={"normalize": False, "source_gain_db": -6})  # fmt: skip
    result = run(edit, db_session, settings, storage)
    assert result.status == ClipEditStatus.READY, result.error_message
    out = decode(storage.path_for(result.storage_key))
    # -6 dB of a 0.9 tone, untouched by normalization (the limiter only acts above -1 dBFS).
    assert amplitude(out, 1, 5, 1000) == pytest.approx(0.9 * 10 ** (-6 / 20), abs=0.03)
    assert result.audio_true_peak_dbtp <= -0.5


def test_plain_edits_keep_the_clips_own_audio(db_session, settings, storage):
    edit = make_pipeline_edit(db_session, storage, captions=False)
    clip_file(storage.path_for(edit.clip.storage_key), 3.0, "0.3*sin(2*PI*1000*t)")
    result = run(use_config(db_session, edit, EditConfig.create(layout="center_crop",
                 captions_enabled=False)), db_session, settings, storage)  # fmt: skip
    assert result.status == ClipEditStatus.READY and result.audio_codec == "aac"
    assert result.audio_loudness_lufs is None  # no audio section: no mixing, no normalization
    out = decode(storage.path_for(result.storage_key))
    assert amplitude(out, 0.5, 2.5, 1000) == pytest.approx(0.3, abs=0.02)


@pytest.mark.parametrize("problem", ["file_missing", "other_project", "wrong_kind"])
def test_unavailable_assets_fail_the_render_safely(db_session, settings, storage, problem):
    edit = audio_edit(db_session, storage)
    music_id = edit.config["audio"]["music"]["asset_id"]
    music = db_session.get(AudioAsset, uuid.UUID(music_id))
    if problem == "file_missing":
        storage.path_for(music.storage_key).unlink()
    elif problem == "other_project":
        other = make_pipeline_edit(db_session, storage, captions=False).clip.video.project_id
        music.project_id = other
    else:
        music.kind = "sfx"
    db_session.commit()
    result = run(edit, db_session, settings, storage)
    assert result.status == ClipEditStatus.FAILED
    assert result.error_code == "audio_asset_unavailable"
    assert str(storage.root) not in result.error_message and music_id not in result.error_message
    assert not storage.path_for(f"edits/{edit.id}").exists()  # nothing partial is kept


def test_a_superseded_attempt_writes_nothing_and_keeps_newer_files(
    db_session, settings, storage, monkeypatch
):
    edit = audio_edit(db_session, storage)
    real = pipeline_module.prepare_track

    def taken_over(*args, **kwargs):
        result = real(*args, **kwargs)
        # A retry claims the edit while this attempt is still mixing.
        db_session.execute(
            ClipEdit.__table__.update().where(ClipEdit.id == edit.id).values(
                celery_task_id="task-2", attempt=2
            )
        )  # fmt: skip
        db_session.commit()
        newer = storage.path_for(f"edits/{edit.id}/work-2")
        newer.mkdir(parents=True, exist_ok=True)
        (newer / "audio-mix.wav").write_bytes(b"newer attempt")
        return result

    monkeypatch.setattr(pipeline_module, "prepare_track", taken_over)
    result = run(edit, db_session, settings, storage, task_id="task-1")
    db_session.refresh(result)
    assert result.status != ClipEditStatus.FAILED and result.storage_key is None
    assert not storage.path_for(f"edits/{edit.id}/work-1").exists()  # our own files removed
    assert (storage.path_for(f"edits/{edit.id}/work-2") / "audio-mix.wav").exists()


@requires_libass
def test_the_full_audiovisual_short(db_session, settings, storage):
    """Smart reframe + word-synced captions + hook + music + ducking + effects."""
    edit = audio_edit(db_session, storage, seconds=3.0, effects=(1.0,))
    track = add_completed_track(db_session, edit.clip)
    analysis = completed_analysis(db_session, edit.clip)
    config = EditConfig.create(
        layout="smart_reframe", reframe_analysis_id=analysis.id, captions_enabled=True,
        caption_style="focus", caption_track_id=track.id, hook_enabled=True,
        hook_text="Watch this", audio=edit.config["audio"],
    )  # fmt: skip
    result = run(use_config(db_session, edit, config), db_session, settings, storage)
    assert result.status == ClipEditStatus.READY, result.error_message
    assert (result.width, result.height, result.audio_codec) == (1080, 1920, "aac")
    assert abs(result.duration_seconds - 3.0) <= 0.1
    path = storage.path_for(result.storage_key)
    f = frame(path, 1.2)  # TWO is spoken: the highlight is drawn, the hook is on screen
    assert (np.abs(f - YELLOW).max(axis=2) < 50)[1000:1600].sum() > 300
    assert (f[150:450].max(axis=2) > 230).sum() > 500
    out = decode(path)
    assert onsets(out, 3000) == pytest.approx([1.0], abs=0.03)
    assert result.audio_loudness_lufs == pytest.approx(TARGET_I, abs=1.0)
