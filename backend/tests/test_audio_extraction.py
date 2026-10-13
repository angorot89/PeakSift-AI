import subprocess
import uuid
from pathlib import Path

import pytest

from app.services import audio_extraction
from app.services.audio_extraction import (
    AudioExtractionError,
    build_ffmpeg_command,
    extract_normalized_audio,
    normalized_audio_key,
)
from app.services.ffprobe import probe_audio
from app.services.storage import InvalidStorageKey, LocalMediaStorage
from tests.media_fixtures import generate_video, requires_ffmpeg


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stderr: bytes = b""):
        self.returncode, self.stdout, self.stderr = returncode, b"", stderr


@pytest.fixture
def storage(tmp_path: Path) -> LocalMediaStorage:
    return LocalMediaStorage(tmp_path / "media")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "source.mp4"
    path.write_bytes(b"fake video bytes")
    return path


def leftovers(storage: LocalMediaStorage) -> list[Path]:
    return [p for p in storage.root.rglob("*") if p.is_file()]


# --- command construction -----


def test_command_is_an_argument_list_with_speech_settings(tmp_path: Path):
    command = build_ffmpeg_command("/opt/ffmpeg", tmp_path / "in.mp4", tmp_path / "out.mp3")

    assert isinstance(command, list)
    assert command[0] == "/opt/ffmpeg"
    assert command[command.index("-i") + 1] == str(tmp_path / "in.mp4")
    assert command[-1] == str(tmp_path / "out.mp3")
    assert "-vn" in command
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-ar") + 1] == "16000"
    assert command[command.index("-b:a") + 1] == "64k"
    assert command[command.index("-f") + 1] == "mp3"  # temp name has no usable extension
    assert "-nostdin" in command


def test_normalized_audio_key_is_internal_and_safe(storage: LocalMediaStorage):
    key = normalized_audio_key(uuid.UUID("12345678-1234-5678-1234-567812345678"))

    assert key == "transcription/12345678-1234-5678-1234-567812345678/normalized.mp3"
    assert storage.root in storage.path_for(key).parents


# --- mocked ffmpeg -----


def test_successful_extraction(monkeypatch, storage, source):
    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"ID3mp3bytes")
        assert kwargs["timeout"] == 123
        assert kwargs.get("shell", False) is False
        return FakeCompletedProcess()

    monkeypatch.setattr(audio_extraction.subprocess, "run", fake_run)
    monkeypatch.setattr(audio_extraction, "probe_audio", lambda *a, **k: _audio(42.5))

    result = extract_normalized_audio(
        source, storage, "transcription/t1/normalized.mp3", timeout_seconds=123
    )

    assert result.storage_key == "transcription/t1/normalized.mp3"
    assert result.size_bytes == len(b"ID3mp3bytes")
    assert result.duration_seconds == 42.5
    assert storage.path_for(result.storage_key).read_bytes() == b"ID3mp3bytes"
    assert not [p for p in leftovers(storage) if p.name.endswith(".part")]


def _audio(duration):
    from app.services.ffprobe import AudioInfo

    return AudioInfo(duration_seconds=duration, codec="mp3", sample_rate=16000, channels=1)


def test_ffmpeg_failure_is_safe_and_cleans_up(monkeypatch, storage, source):
    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"partial")
        return FakeCompletedProcess(1, b"/secret/path/source.mp4: Invalid data found")

    monkeypatch.setattr(audio_extraction.subprocess, "run", fake_run)

    with pytest.raises(AudioExtractionError) as excinfo:
        extract_normalized_audio(source, storage, "transcription/t1/normalized.mp3")

    assert excinfo.value.code == "ffmpeg_failed"
    assert "/secret" not in excinfo.value.message
    assert "exit code 1" in excinfo.value.message
    assert leftovers(storage) == []


def test_video_without_audio_track(monkeypatch, storage, source):
    monkeypatch.setattr(
        audio_extraction.subprocess,
        "run",
        lambda *a, **k: FakeCompletedProcess(1, b"Output file #0 does not contain any stream"),
    )

    with pytest.raises(AudioExtractionError) as excinfo:
        extract_normalized_audio(source, storage, "transcription/t1/normalized.mp3")

    assert excinfo.value.code == "no_audio_stream"
    assert excinfo.value.message == "The video has no audio track"
    assert leftovers(storage) == []


def test_timeout_kills_and_cleans_up(monkeypatch, storage, source):
    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"half written")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(audio_extraction.subprocess, "run", fake_run)

    with pytest.raises(AudioExtractionError) as excinfo:
        extract_normalized_audio(
            source, storage, "transcription/t1/normalized.mp3", timeout_seconds=5
        )

    assert excinfo.value.code == "ffmpeg_timeout"
    assert "5 seconds" in excinfo.value.message
    assert leftovers(storage) == []


def test_missing_ffmpeg_binary(monkeypatch, storage, source):
    def fake_run(command, **kwargs):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(audio_extraction.subprocess, "run", fake_run)

    with pytest.raises(AudioExtractionError) as excinfo:
        extract_normalized_audio(source, storage, "transcription/t1/normalized.mp3")

    assert excinfo.value.code == "ffmpeg_missing"


def test_empty_output_is_rejected(monkeypatch, storage, source):
    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"")
        return FakeCompletedProcess()

    monkeypatch.setattr(audio_extraction.subprocess, "run", fake_run)

    with pytest.raises(AudioExtractionError) as excinfo:
        extract_normalized_audio(source, storage, "transcription/t1/normalized.mp3")

    assert excinfo.value.code == "empty_output"
    assert leftovers(storage) == []


def test_missing_source_never_runs_ffmpeg(monkeypatch, storage, tmp_path):
    calls = []
    monkeypatch.setattr(audio_extraction.subprocess, "run", lambda *a, **k: calls.append(a))

    with pytest.raises(AudioExtractionError) as excinfo:
        extract_normalized_audio(tmp_path / "nope.mp4", storage, "transcription/t1/normalized.mp3")

    assert excinfo.value.code == "source_missing"
    assert calls == []


def test_unsafe_key_is_rejected_before_anything_happens(monkeypatch, storage, source):
    calls = []
    monkeypatch.setattr(audio_extraction.subprocess, "run", lambda *a, **k: calls.append(a))

    with pytest.raises(InvalidStorageKey):
        extract_normalized_audio(source, storage, "../../escape/normalized.mp3")

    assert calls == []
    assert not storage.root.exists()


# --- real ffmpeg -----


@requires_ffmpeg
def test_real_extraction_produces_mono_16khz_mp3(tmp_path: Path, storage: LocalMediaStorage):
    video = generate_video(tmp_path / "clip.mp4", seconds=2, fps=25)

    result = extract_normalized_audio(video, storage, normalized_audio_key("real-1"))

    path = storage.path_for(result.storage_key)
    assert path.is_file() and result.size_bytes == path.stat().st_size > 0
    info = probe_audio(path)
    assert info.codec == "mp3"
    assert info.sample_rate == 16000
    assert info.channels == 1
    assert info.duration_seconds == pytest.approx(2.0, abs=0.3)
    assert result.duration_seconds == pytest.approx(2.0, abs=0.3)
    assert not [p for p in leftovers(storage) if p.name.endswith(".part")]


@requires_ffmpeg
def test_real_video_without_audio_fails_cleanly(tmp_path: Path, storage: LocalMediaStorage):
    video = generate_video(tmp_path / "silent.mp4", seconds=1, fps=25, audio=False)

    with pytest.raises(AudioExtractionError) as excinfo:
        extract_normalized_audio(video, storage, normalized_audio_key("real-2"))

    assert excinfo.value.code == "no_audio_stream"
    assert leftovers(storage) == []


@requires_ffmpeg
def test_real_invalid_source_fails_cleanly(tmp_path: Path, storage: LocalMediaStorage):
    bogus = tmp_path / "bogus.mp4"
    bogus.write_bytes(b"\x00" * 4096)

    with pytest.raises(AudioExtractionError) as excinfo:
        extract_normalized_audio(bogus, storage, normalized_audio_key("real-3"))

    assert excinfo.value.code in ("ffmpeg_failed", "no_audio_stream")
    assert str(bogus) not in excinfo.value.message
    assert leftovers(storage) == []
