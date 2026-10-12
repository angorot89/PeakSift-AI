"""Read media metadata with ffprobe (JSON output, argument-array invocation, timeout)."""

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None


@dataclass(frozen=True)
class AudioInfo:
    duration_seconds: float | None
    codec: str | None
    sample_rate: int | None
    channels: int | None


class ProbeError(Exception):
    """The file could not be inspected. The message is safe to store and show."""


def parse_frame_rate(value: object) -> float | None:
    """ffprobe reports rates as fractions such as ``30000/1001``; return them as floats."""
    if not isinstance(value, str) or not value:
        return None
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return round(float(rate), 3) if rate > 0 else None


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return value if isinstance(value, int) and value > 0 else None


def _str_or_none(value: object) -> str | None:
    return value[:64] if isinstance(value, str) and value else None


def _load_output(raw: bytes | str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise ProbeError("ffprobe returned unreadable output") from None
    if not isinstance(data, dict):
        raise ProbeError("ffprobe returned unreadable output")
    return data


def _streams(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in data.get("streams", []) if isinstance(s, dict)]


def _container(data: dict[str, Any]) -> dict[str, Any]:
    container = data.get("format")
    return container if isinstance(container, dict) else {}


def parse_ffprobe_output(raw: bytes | str) -> VideoMetadata:
    data = _load_output(raw)
    streams = _streams(data)
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeError("The file does not contain a video stream")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = _float_or_none(_container(data).get("duration")) or _float_or_none(
        video.get("duration")
    )
    fps = parse_frame_rate(video.get("avg_frame_rate")) or parse_frame_rate(
        video.get("r_frame_rate")
    )

    return VideoMetadata(
        duration_seconds=duration,
        width=_int_or_none(video.get("width")),
        height=_int_or_none(video.get("height")),
        fps=fps,
        video_codec=_str_or_none(video.get("codec_name")),
        audio_codec=_str_or_none(audio.get("codec_name")) if audio else None,
    )


def parse_audio_output(raw: bytes | str) -> AudioInfo:
    data = _load_output(raw)
    audio = next((s for s in _streams(data) if s.get("codec_type") == "audio"), None)
    if audio is None:
        raise ProbeError("The file does not contain an audio stream")
    duration = _float_or_none(_container(data).get("duration")) or _float_or_none(
        audio.get("duration")
    )
    return AudioInfo(
        duration_seconds=duration,
        codec=_str_or_none(audio.get("codec_name")),
        sample_rate=_int_or_none(audio.get("sample_rate")),
        channels=_int_or_none(audio.get("channels")),
    )


def run_ffprobe(path: Path, *, ffprobe_path: str = "ffprobe", timeout_seconds: float = 30) -> bytes:
    """Run ffprobe on ``path`` and return its JSON output. Raises ProbeError with a safe message.

    The command is an argument list (never a shell string) and the only variable
    part is the file path, which the application generated itself.
    """
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout_seconds, check=False)
    except FileNotFoundError:
        raise ProbeError("ffprobe is not installed on the server") from None
    except subprocess.TimeoutExpired:
        raise ProbeError(f"ffprobe timed out after {timeout_seconds:g} seconds") from None

    if result.returncode != 0:
        # stderr can contain the local path, so it is deliberately not stored or shown.
        raise ProbeError(f"ffprobe could not read the file (exit code {result.returncode})")
    return result.stdout


def probe(
    path: Path, *, ffprobe_path: str = "ffprobe", timeout_seconds: float = 30
) -> VideoMetadata:
    """Inspect a video file. Raises ProbeError with a safe message on any failure."""
    return parse_ffprobe_output(
        run_ffprobe(path, ffprobe_path=ffprobe_path, timeout_seconds=timeout_seconds)
    )


def probe_audio(
    path: Path, *, ffprobe_path: str = "ffprobe", timeout_seconds: float = 30
) -> AudioInfo:
    """Inspect an audio file. Raises ProbeError with a safe message on any failure."""
    return parse_audio_output(
        run_ffprobe(path, ffprobe_path=ffprobe_path, timeout_seconds=timeout_seconds)
    )
