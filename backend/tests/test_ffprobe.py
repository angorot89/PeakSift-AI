import json
import subprocess
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services import ffprobe as ffprobe_module
from app.services.ffprobe import ProbeError, parse_ffprobe_output, parse_frame_rate, probe
from tests.media_fixtures import generate_video, have_ffmpeg

SAMPLE_OUTPUT = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30000/1001",
            "r_frame_rate": "30000/1001",
        },
        {"codec_type": "audio", "codec_name": "aac"},
    ],
    "format": {"duration": "8040.512000", "size": "123"},
}


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


# --- parsing ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("30000/1001", 29.97),
        ("30/1", 30.0),
        ("25", 25.0),
        ("24000/1001", 23.976),
        ("0/0", None),
        ("0/1", None),
        ("", None),
        (None, None),
        ("abc", None),
        ("1/0", None),
    ],
)
def test_parse_frame_rate(value, expected):
    assert parse_frame_rate(value) == expected


def test_parse_valid_output():
    metadata = parse_ffprobe_output(json.dumps(SAMPLE_OUTPUT))

    assert metadata.duration_seconds == pytest.approx(8040.512)
    assert (metadata.width, metadata.height) == (1920, 1080)
    assert metadata.fps == 29.97
    assert metadata.video_codec == "h264"
    assert metadata.audio_codec == "aac"


def test_parse_video_without_audio():
    data = {"streams": [SAMPLE_OUTPUT["streams"][0]], "format": {"duration": "2"}}

    metadata = parse_ffprobe_output(json.dumps(data))

    assert metadata.audio_codec is None
    assert metadata.video_codec == "h264"


def test_parse_falls_back_to_stream_duration_and_r_frame_rate():
    stream = {
        "codec_type": "video",
        "codec_name": "vp9",
        "duration": "12.5",
        "r_frame_rate": "60/1",
    }

    metadata = parse_ffprobe_output(json.dumps({"streams": [stream], "format": {}}))

    assert metadata.duration_seconds == 12.5
    assert metadata.fps == 60.0


@pytest.mark.parametrize("raw", [b"", b"not json", b"[]", b"42"])
def test_parse_rejects_malformed_output(raw: bytes):
    with pytest.raises(ProbeError):
        parse_ffprobe_output(raw)


def test_parse_rejects_files_without_video_stream():
    with pytest.raises(ProbeError, match="video stream"):
        parse_ffprobe_output(json.dumps({"streams": [{"codec_type": "audio"}], "format": {}}))


def test_parse_tolerates_garbage_values():
    stream = {"codec_type": "video", "codec_name": 7, "width": "wide", "height": -1}

    metadata = parse_ffprobe_output(json.dumps({"streams": [stream], "format": {"duration": "x"}}))

    assert (metadata.width, metadata.height, metadata.video_codec, metadata.duration_seconds) == (
        None,
        None,
        None,
        None,
    )


# --- subprocess handling (mocked) ---------------------------------------------------


def test_probe_invokes_ffprobe_as_argument_list(monkeypatch, tmp_path: Path):
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["command"], captured["kwargs"] = command, kwargs
        return FakeCompletedProcess(stdout=json.dumps(SAMPLE_OUTPUT).encode())

    monkeypatch.setattr(ffprobe_module.subprocess, "run", fake_run)

    metadata = probe(tmp_path / "x.mp4", ffprobe_path="/opt/bin/ffprobe", timeout_seconds=7)

    assert isinstance(captured["command"], list)
    assert captured["command"][0] == "/opt/bin/ffprobe"
    assert captured["command"][-1] == str(tmp_path / "x.mp4")
    assert "-print_format" in captured["command"] and "json" in captured["command"]
    assert captured["kwargs"]["timeout"] == 7
    assert captured["kwargs"].get("shell", False) is False
    assert metadata.width == 1920


def test_probe_failure_exit_code_does_not_leak_stderr(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        ffprobe_module.subprocess,
        "run",
        lambda *a, **k: FakeCompletedProcess(1, b"", b"/secret/media/x.mp4: Invalid data"),
    )

    with pytest.raises(ProbeError) as excinfo:
        probe(tmp_path / "x.mp4")

    assert "/secret" not in str(excinfo.value)
    assert "exit code 1" in str(excinfo.value)


def test_probe_timeout(monkeypatch, tmp_path: Path):
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(ffprobe_module.subprocess, "run", fake_run)

    with pytest.raises(ProbeError, match="timed out"):
        probe(tmp_path / "x.mp4", timeout_seconds=0.5)


def test_probe_missing_binary(monkeypatch, tmp_path: Path):
    def fake_run(command, **kwargs):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(ffprobe_module.subprocess, "run", fake_run)

    with pytest.raises(ProbeError, match="not installed"):
        probe(tmp_path / "x.mp4")


# --- real ffprobe (integration) -----------------------------------------------------

requires_ffmpeg = pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg/ffprobe not installed")


@requires_ffmpeg
def test_probe_real_mp4(tmp_path: Path):
    path = generate_video(tmp_path / "clip.mp4", seconds=1, fps=30)

    metadata = probe(path, ffprobe_path=get_settings().ffprobe_path)

    assert metadata.duration_seconds == pytest.approx(1.0, abs=0.2)
    assert (metadata.width, metadata.height) == (64, 64)
    assert metadata.fps == 30.0
    assert metadata.video_codec == "h264"
    assert metadata.audio_codec == "aac"


@requires_ffmpeg
def test_probe_real_video_without_audio(tmp_path: Path):
    path = generate_video(tmp_path / "silent.mp4", seconds=1, fps=24, audio=False)

    metadata = probe(path)

    assert metadata.audio_codec is None
    assert metadata.fps == 24.0


@requires_ffmpeg
def test_probe_real_webm(tmp_path: Path):
    path = generate_video(tmp_path / "clip.webm", seconds=1, fps=25)

    metadata = probe(path)

    assert metadata.video_codec == "vp9"
    assert metadata.audio_codec == "opus"
    assert (metadata.width, metadata.height) == (64, 64)


@requires_ffmpeg
def test_probe_real_rejects_non_media(tmp_path: Path):
    path = tmp_path / "fake.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048)

    with pytest.raises(ProbeError):
        probe(path)
