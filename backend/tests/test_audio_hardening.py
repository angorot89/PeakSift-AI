"""Senior-review hardening of audio assets and mixing: storage containment (symlinks),
degenerate uploads, unusual formats, output validation, clipping refusal, many cues and
log redaction."""

import logging
import uuid
import wave
from pathlib import Path

import pytest

from app.core.config import Settings, get_settings
from app.models import AudioAsset, ClipEditStatus
from app.services.audio_mix.config import DuckingStrength, MusicConfig, SfxCue
from app.services.audio_mix.loudness import Loudness
from app.services.audio_mix.mixer import render_mix
from app.services.audio_mix.plan import MixPlanRequest, MusicInput, SfxInput
from app.services.clip_edit import pipeline as pipeline_module
from app.services.clip_render.pipeline import render_options_from
from app.services.clip_render.renderer import RenderError
from app.services.ffprobe import AudioInfo
from app.services.storage import LocalMediaStorage
from tests.audio_fixtures import RATE, decode, tone
from tests.media_fixtures import requires_ffmpeg
from tests.test_audio_assets_api import make_audio, upload
from tests.test_audio_edit_render import audio_edit, run
from tests.test_video_upload import create_project, sign_up

pytestmark = requires_ffmpeg


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


def test_a_symlinked_asset_file_never_escapes_the_media_root(
    db_session, settings, storage, tmp_path
):
    edit = audio_edit(db_session, storage, seconds=3.0, effects=())
    music = db_session.get(AudioAsset, uuid.UUID(edit.config["audio"]["music"]["asset_id"]))
    target = storage.path_for(music.storage_key)
    outside = tone(tmp_path / "outside.wav", "0.5*sin(2*PI*200*t)", 3)
    target.unlink()
    target.symlink_to(outside)
    result = run(edit, db_session, settings, storage)
    assert result.status == ClipEditStatus.FAILED and result.error_code == "audio_asset_unavailable"
    assert str(tmp_path) not in (result.error_message or "")


def test_preview_of_a_symlinked_asset_is_a_plain_404(client, tmp_path):
    sign_up(client, f"sym-{uuid.uuid4().hex[:8]}@example.com")
    project = create_project(client)["id"]
    body = upload(client, project, make_audio(tmp_path / "a.mp3")).json()
    [stored] = [p for p in Path(get_settings().media_root).rglob("*.mp3")]
    secret = tmp_path / "secret.txt"
    secret.write_text("not for you")
    stored.unlink()
    stored.symlink_to(secret)
    response = client.get(f"/projects/{project}/audio-assets/{body['id']}/content")
    assert response.status_code == 404 and "not for you" not in response.text
    stored.unlink()


def test_zero_duration_and_long_names(client, tmp_path):
    sign_up(client, f"edge-{uuid.uuid4().hex[:8]}@example.com")
    project = create_project(client)["id"]
    empty_wav = tmp_path / "silence.wav"
    with wave.open(str(empty_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"")
    assert upload(client, project, empty_wav).status_code in (415, 422)
    assert not list(Path(get_settings().media_root).rglob("*.wav"))
    long_name = "a" * 300 + ".mp3"
    body = upload(client, project, make_audio(tmp_path / "x.mp3"), name=long_name).json()
    assert len(body["display_name"]) <= 255 and body["display_name"].endswith(".mp3")
    for path in Path(get_settings().media_root).rglob("*.mp3"):
        path.unlink()


def test_unusual_sample_rates_and_channel_counts_mix_to_the_working_format(tmp_path):
    source = tone(tmp_path / "src.wav", "0.2*sin(2*PI*1000*t)", 3, rate=22050)
    music = tone(tmp_path / "m.wav", "0.4*sin(2*PI*200*t)", 3, rate=8000)
    effect = tone(tmp_path / "s.wav", "0.5*sin(2*PI*3000*t)", 0.3, rate=96000, mono=False)
    request = MixPlanRequest(
        3.0, source,
        music=MusicInput(music, 3.0, MusicConfig(asset_id="m", ducking=DuckingStrength.OFF)),
        sfx=(SfxInput(effect, 0.3, SfxCue(at_seconds=1.0, asset_id="s")),),
    )  # fmt: skip
    out = render_mix(request, tmp_path / "mix.wav", render_options_from(get_settings()))
    stereo = decode(out, channels=2)
    assert len(stereo) == 3 * RATE * 2


def test_many_cues_of_the_same_effect_render(db_session, settings, storage):
    edit = audio_edit(db_session, storage, seconds=3.0, music=False,
                      effects=tuple(round(0.2 * i, 1) for i in range(12)))  # fmt: skip
    result = run(edit, db_session, settings, storage)
    assert result.status == ClipEditStatus.READY, result.error_message
    assert len(edit.config["audio"]["sfx"]) == 12


def test_a_clipped_result_is_refused(db_session, settings, storage, monkeypatch):
    edit = audio_edit(db_session, storage, seconds=3.0, effects=())
    hot = Loudness(integrated=-3.0, true_peak=0.8, lra=1.0, threshold=-13.0, offset=0.0)
    monkeypatch.setattr(pipeline_module, "measure_loudness", lambda *a, **k: hot)
    result = run(edit, db_session, settings, storage)
    assert result.status == ClipEditStatus.FAILED and result.error_code == "audio_clipped"
    assert not storage.path_for(f"edits/{edit.id}").exists()


def test_an_invalid_final_audio_track_is_refused(db_session, settings, storage, monkeypatch):
    edit = audio_edit(db_session, storage, seconds=3.0, effects=())
    monkeypatch.setattr(
        pipeline_module, "probe_audio",
        lambda *a, **k: AudioInfo(duration_seconds=3.0, codec="aac", sample_rate=48000, channels=1),
    )  # fmt: skip
    result = run(edit, db_session, settings, storage)
    assert result.status == ClipEditStatus.FAILED and result.error_code == "invalid_output"


def test_ffmpeg_errors_are_logged_without_paths(tmp_path, caplog):
    broken = tmp_path / "broken-music.wav"
    broken.write_bytes(b"RIFF" + b"\x00" * 64)
    request = MixPlanRequest(2.0, None, music=MusicInput(broken, 5.0, MusicConfig(asset_id="a")))
    with caplog.at_level(logging.WARNING), pytest.raises(RenderError) as excinfo:
        render_mix(request, tmp_path / "mix.wav", render_options_from(get_settings()))
    assert excinfo.value.code == "audio_mix_failed"
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert str(tmp_path) not in logged and str(tmp_path) not in excinfo.value.message
