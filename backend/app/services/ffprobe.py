"""Read video metadata with ffprobe (JSON output, argument-array invocation, timeout)."""

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None


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
    return value if isinstance(value, int) and value > 0 else None


def _str_or_none(value: object) -> str | None:
    return value[:64] if isinstance(value, str) and value else None


def parse_ffprobe_output(raw: bytes | str) -> VideoMetadata:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise ProbeError("ffprobe returned unreadable output") from None
    if not isinstance(data, dict):
        raise ProbeError("ffprobe returned unreadable output")

    streams = [s for s in data.get("streams", []) if isinstance(s, dict)]
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeError("The file does not contain a video stream")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    container = data.get("format") if isinstance(data.get("format"), dict) else {}
    duration = _float_or_none(container.get("duration")) or _float_or_none(video.get("duration"))
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


def probe(
    path: Path, *, ffprobe_path: str = "ffprobe", timeout_seconds: float = 30
) -> VideoMetadata:
    """Inspect ``path`` with ffprobe. Raises ProbeError with a safe message on any failure.

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

    return parse_ffprobe_output(result.stdout)
