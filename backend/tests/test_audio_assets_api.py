"""Private audio asset uploads: content validation (ffprobe), limits, waveform peaks,
duplicates, filename safety, cleanup, ownership. Fixtures are generated with FFmpeg."""

import subprocess
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import AudioAsset
from app.services.audio_assets import (
    WAVEFORM_MAX_BUCKETS,
    WAVEFORM_MIN_BUCKETS,
    compute_waveform,
    validate_audio_upload,
    waveform_bucket_count,
)
from app.services.video_upload import UploadValidationError
from tests.media_fixtures import generate_video, requires_ffmpeg
from tests.test_video_upload import create_project, sign_up

pytestmark = requires_ffmpeg

CODECS = {
    ".mp3": ["-c:a", "libmp3lame", "-b:a", "96k"],
    ".wav": ["-c:a", "pcm_s16le"],
    ".m4a": ["-c:a", "aac", "-b:a", "96k"],
    ".aac": ["-c:a", "aac", "-b:a", "96k", "-f", "adts"],
    ".ogg": ["-c:a", "libvorbis"],
    ".opus": ["-c:a", "libopus", "-b:a", "64k"],
}


def make_audio(
    path: Path, *, seconds: float = 2.0, channels: int = 2, rate: int = 44100, freq: int = 330
) -> Path:
    layout = "stereo" if channels == 2 else "mono"
    tone = f"0.5*sin(2*PI*{freq}*t)"
    subprocess.run(
        [
            ffmpeg(), "-v", "error", "-y", "-f", "lavfi",
            "-i", f"aevalsrc={tone}:s={rate}:d={seconds}",
            "-af", f"aformat=channel_layouts={layout}",
            *CODECS[path.suffix], str(path),
        ],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    return path


def ffmpeg() -> str:
    return get_settings().ffmpeg_path  # the configured build (codecs differ between builds)


def upload(client, project_id, path: Path, kind="music", name=None, content_type=None):
    file = (name or path.name, path.read_bytes(), content_type or "application/octet-stream")
    return client.post(
        f"/projects/{project_id}/audio-assets", files={"file": file}, data={"kind": kind}
    )


def audio_files() -> list[Path]:
    return [p for p in Path(get_settings().media_root).rglob("*") if p.is_file()]


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in audio_files():
        path.unlink()


@pytest.fixture
def project(client):
    sign_up(client, f"maker-{uuid.uuid4().hex[:8]}@example.com")
    return create_project(client)["id"]


# --- formats and metadata ------


@pytest.mark.parametrize(
    ("suffix", "codec", "container"),
    [
        (".mp3", "mp3", "mp3"),
        (".wav", "pcm_s16le", "wav"),
        (".m4a", "aac", "mp4"),
        (".aac", "aac", "aac"),
        (".ogg", "vorbis", "ogg"),
        (".opus", "opus", "ogg"),
    ],
)
def test_supported_formats_are_probed_and_indexed(
    client, project, tmp_path, suffix, codec, container
):
    path = make_audio(tmp_path / f"track{suffix}", seconds=3, channels=1, rate=48000)
    response = upload(client, project, path)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["codec"] == codec and body["container"] == container
    assert body["channels"] == 1 and body["kind"] == "music"
    assert body["duration_seconds"] == pytest.approx(3, abs=0.15)
    assert body["sample_rate"] > 0 and body["file_size"] == path.stat().st_size
    assert not {"storage_key", "sha256", "waveform_peaks"} & set(body)
    wave = client.get(f"/projects/{project}/audio-assets/{body['id']}/waveform").json()
    assert wave["buckets"] == len(wave["peaks"]) == WAVEFORM_MIN_BUCKETS
    assert all(isinstance(p, int) and 0 <= p <= 100 for p in wave["peaks"])
    assert max(wave["peaks"]) >= 40  # a half-scale tone, not an empty waveform


def test_stereo_metadata_and_the_canonical_content_type(client, project, tmp_path):
    path = make_audio(tmp_path / "loop.wav", channels=2, rate=44100)
    body = upload(client, project, path, content_type="audio/x-wav").json()
    assert (body["channels"], body["sample_rate"], body["content_type"]) == (2, 44100, "audio/wav")


def test_waveform_bucket_count_is_bounded_by_duration(client, project, tmp_path):
    long = upload(client, project, make_audio(tmp_path / "long.mp3", seconds=75)).json()
    wave = client.get(f"/projects/{project}/audio-assets/{long['id']}/waveform").json()
    assert wave["buckets"] == WAVEFORM_MAX_BUCKETS
    mid = upload(client, project, make_audio(tmp_path / "mid.mp3", seconds=20, freq=500)).json()
    # 20 buckets per second of the probed duration (MP3 padding varies between encoders).
    mid_wave = client.get(f"/projects/{project}/audio-assets/{mid['id']}/waveform").json()
    assert mid_wave["buckets"] == waveform_bucket_count(mid["duration_seconds"])
    assert 395 <= mid_wave["buckets"] <= 405


def test_waveform_follows_loudness_over_time(tmp_path):
    loud_then_quiet = tmp_path / "steps.wav"
    subprocess.run(
        [
            ffmpeg(), "-v", "error", "-y", "-f", "lavfi",
            "-i", "aevalsrc=if(lt(t\\,5)\\,0.8\\,0.05)*sin(2*PI*300*t):s=16000:d=10",
            "-c:a", "pcm_s16le",
            str(loud_then_quiet),
        ],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    peaks = compute_waveform(loud_then_quiet, 10.0, ffmpeg_path=get_settings().ffmpeg_path)
    first, second = peaks[: len(peaks) // 2 - 5], peaks[len(peaks) // 2 + 5 :]
    assert min(first) >= 60 and max(second) <= 10


# --- refusals leave nothing behind ------


def test_corrupt_audio_is_refused_and_removed(client, project, tmp_path):
    bad = tmp_path / "broken.mp3"
    bad.write_bytes(b"ID3" + b"\x00garbage" * 500)
    response = upload(client, project, bad)
    assert response.status_code in (415, 422)
    assert audio_files() == []


def test_video_files_are_refused_even_when_renamed(client, project, tmp_path):
    with_audio = generate_video(tmp_path / "clip.mp4", seconds=1)
    silent = generate_video(tmp_path / "silent.mp4", seconds=1, audio=False)
    for path in (with_audio, silent):
        response = upload(client, project, path, name="song.m4a")
        assert response.status_code == 415, response.text
        assert "video" in response.json()["detail"]
    assert audio_files() == []


def test_contents_must_match_the_extension(client, project, tmp_path):
    mp3 = make_audio(tmp_path / "real.mp3")
    response = upload(client, project, mp3, name="pretend.wav")
    assert response.status_code == 415
    assert audio_files() == []


def test_declared_type_must_match_and_unknown_extensions_are_refused(client, project, tmp_path):
    mp3 = make_audio(tmp_path / "real.mp3")
    assert upload(client, project, mp3, content_type="video/mp4").status_code == 415
    assert upload(client, project, mp3, name="track.exe").status_code == 415
    assert upload(client, project, mp3, name="track").status_code == 415
    assert audio_files() == []


def test_empty_and_oversized_uploads(client, project, tmp_path, monkeypatch):
    empty = tmp_path / "empty.mp3"
    empty.write_bytes(b"")
    assert upload(client, project, empty).status_code == 400
    mp3 = make_audio(tmp_path / "real.mp3", seconds=3)
    monkeypatch.setattr(get_settings(), "audio_upload_max_bytes", 1024)
    response = upload(client, project, mp3)
    assert response.status_code == 413
    assert audio_files() == []


def test_duration_limits_per_kind(client, project, tmp_path, monkeypatch):
    long_sfx = make_audio(tmp_path / "whoosh.wav", seconds=6)
    monkeypatch.setattr(get_settings(), "audio_sfx_max_duration_seconds", 5.0)
    response = upload(client, project, long_sfx, kind="sfx")
    assert response.status_code == 413 and "Sound effects" in response.json()["detail"]
    assert upload(client, project, long_sfx, kind="music").status_code == 201
    monkeypatch.setattr(get_settings(), "audio_upload_max_duration_seconds", 4.0)
    other = make_audio(tmp_path / "other.wav", seconds=6, freq=600)
    assert upload(client, project, other, kind="music").status_code == 413
    assert len(audio_files()) == 1  # only the accepted music file


def test_kind_is_an_allow_list(client, project, tmp_path):
    mp3 = make_audio(tmp_path / "real.mp3")
    assert upload(client, project, mp3, kind="podcast").status_code == 422
    assert audio_files() == []


# --- names, duplicates, listing ------


def test_unicode_and_path_like_names_are_display_metadata_only(client, project, tmp_path):
    mp3 = make_audio(tmp_path / "real.mp3")
    body = upload(client, project, mp3, name="../../etc/Éclair d'été 🎵.mp3").json()
    assert body["display_name"] == "Éclair d'été 🎵.mp3"
    [stored] = audio_files()
    assert stored.parent.name == "audio" and stored.suffix == ".mp3"
    assert len(stored.stem) == 32 and "clair" not in stored.name


def test_the_same_file_for_the_same_purpose_is_reused(client, project, tmp_path, db_session):
    mp3 = make_audio(tmp_path / "beat.mp3")
    first = upload(client, project, mp3)
    again = upload(client, project, mp3, name="renamed.mp3")
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    as_sfx = upload(client, project, mp3, kind="sfx")
    assert as_sfx.status_code == 201 and as_sfx.json()["id"] != first.json()["id"]
    different = upload(
        client, project, make_audio(tmp_path / "beat2.mp3", freq=800), name="beat.mp3"
    )
    assert different.status_code == 201  # the same name with other contents is another asset
    assert len(audio_files()) == 3
    assert db_session.scalar(select(func.count()).select_from(AudioAsset)) == 3


def test_listing_is_newest_first_and_filterable(client, project, tmp_path, db_session):
    music = upload(client, project, make_audio(tmp_path / "a.mp3")).json()
    sfx = upload(client, project, make_audio(tmp_path / "b.wav", seconds=1), kind="sfx").json()
    # now() is constant inside the test transaction: give the rows distinct times.
    older = db_session.get(AudioAsset, uuid.UUID(music["id"]))
    older.created_at = older.created_at - timedelta(minutes=5)
    db_session.commit()
    everything = client.get(f"/projects/{project}/audio-assets").json()
    assert [a["id"] for a in everything] == [sfx["id"], music["id"]]
    only_sfx = client.get(f"/projects/{project}/audio-assets", params={"kind": "sfx"}).json()
    assert [a["id"] for a in only_sfx] == [sfx["id"]]


def test_upload_limits_are_published(client, project):
    limits = client.get("/audio-upload-limits").json()
    settings = get_settings()
    assert limits["max_bytes"] == settings.audio_upload_max_bytes
    assert limits["sfx_max_duration_seconds"] == settings.audio_sfx_max_duration_seconds
    assert ".mp3" in limits["accepted_extensions"] and ".opus" in limits["accepted_extensions"]


# --- ownership ------


def test_other_users_get_404_and_anonymous_requests_401(client, project, tmp_path):
    asset = upload(client, project, make_audio(tmp_path / "mine.mp3")).json()
    routes = [
        ("get", f"/projects/{project}/audio-assets"),
        ("get", f"/projects/{project}/audio-assets/{asset['id']}"),
        ("get", f"/projects/{project}/audio-assets/{asset['id']}/waveform"),
    ]
    client.post("/auth/logout")
    for method, url in routes:
        assert client.request(method, url).status_code == 401
    assert client.get("/audio-upload-limits").status_code == 401
    assert upload(client, project, tmp_path / "mine.mp3").status_code == 401
    sign_up(client, f"intruder-{uuid.uuid4().hex[:8]}@example.com")
    for method, url in routes:
        assert client.request(method, url).status_code == 404
    assert upload(client, project, tmp_path / "mine.mp3").status_code == 404
    # Their own project cannot read the asset through its id either.
    own = create_project(client, "Mine")["id"]
    assert client.get(f"/projects/{own}/audio-assets/{asset['id']}").status_code == 404
    assert len(audio_files()) == 1


def test_validation_helper_canonicalizes_types():
    assert validate_audio_upload("x.MP3", "audio/mp3") == ("x.MP3", ".mp3", "audio/mpeg")
    with pytest.raises(UploadValidationError):
        validate_audio_upload("x.flac", "audio/flac")
