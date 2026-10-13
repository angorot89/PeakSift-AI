"""Cut one clip out of a source video with FFmpeg and validate the result with ffprobe.

Output profile ``source_mp4_v1``: MP4 container with ``+faststart``, H.264 (libx264,
``yuv420p``), AAC audio when the source has an audio track, the source's resolution,
aspect ratio and visual orientation (FFmpeg applies rotation metadata while decoding, so
phone footage comes out upright). The only geometry change is rounding odd dimensions
down to even ones, which ``yuv420p`` requires.

Accuracy: the clip is *re-encoded*, never stream-copied. ``-ss`` is placed before ``-i``
so FFmpeg seeks to the nearest earlier keyframe and then decodes and discards frames up
to the requested time; the first emitted frame is therefore the first frame at or after
``start`` (within one frame interval). Stream copy (``-c copy``) would snap to keyframes
and could start seconds early, which is why it is not used.
"""

import logging
import math
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.services.ffprobe import ProbeError, VideoMetadata, probe

logger = logging.getLogger(__name__)

VIDEO_CODEC = "libx264"
PIXEL_FORMAT = "yuv420p"
AUDIO_CODEC = "aac"
# yuv420p needs even dimensions; round odd sources down by one pixel (no scaling otherwise).
EVEN_DIMENSIONS_FILTER = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
STDERR_TAIL_BYTES = 2000


@dataclass(frozen=True)
class RenderOptions:
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    preset: str = "veryfast"
    crf: int = 20
    audio_bitrate: str = "128k"
    timeout_seconds: float = 1800
    # How far the rendered duration may differ from the requested one (container/encoder
    # rounding, frame alignment) before the output is rejected.
    duration_tolerance_seconds: float = 1.0
    # A requested end may overrun the probed source duration by this much (encoder padding).
    source_tolerance_seconds: float = 1.0
    heartbeat_interval_seconds: float = 15


@dataclass(frozen=True)
class RenderedClip:
    """A validated artifact at ``path`` (the caller decides where it finally lives)."""

    path: Path
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    fps: float | None
    video_codec: str
    audio_codec: str | None


class RenderError(Exception):
    """Rendering failed. ``code`` is stable; ``message`` is safe to store and show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def build_render_command(
    ffmpeg_path: str,
    source: Path,
    target: Path,
    *,
    start: float,
    duration: float,
    has_audio: bool,
    preset: str,
    crf: int,
    audio_bitrate: str,
) -> list[str]:
    """ffmpeg argument list. Paths come from storage keys; numbers were validated already."""
    command = [
        ffmpeg_path,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v:0",
    ]
    if has_audio:
        command += ["-map", "0:a:0"]
    command += [
        "-sn",  # no subtitle streams
        "-dn",  # no data streams
        "-map_metadata",
        "-1",  # drop container/stream tags (rotation is applied while decoding)
        "-c:v",
        VIDEO_CODEC,
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        PIXEL_FORMAT,
        "-vf",
        EVEN_DIMENSIONS_FILTER,
    ]
    if has_audio:
        command += ["-c:a", AUDIO_CODEC, "-b:a", audio_bitrate]
    command += ["-movflags", "+faststart", "-f", "mp4", str(target)]
    return command


def validate_range(
    start: float, end: float, source_duration: float | None, tolerance: float
) -> float:
    """Return the clip duration, or raise ``invalid_range``. Never trust the numbers blindly."""
    for name, value in (("start", start), ("end", end)):
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise RenderError("invalid_range", f"The clip {name} time is not a valid number")
    if start < 0:
        raise RenderError("invalid_range", "The clip starts before the beginning of the video")
    if end <= start:
        raise RenderError("invalid_range", "The clip must end after it starts")
    if source_duration and start >= source_duration:
        raise RenderError("invalid_range", "The clip starts after the end of the video")
    if source_duration and end > source_duration + tolerance:
        raise RenderError("invalid_range", "The clip ends after the end of the video")
    return end - start


def render_clip(
    source: Path,
    target: Path,
    *,
    start: float,
    end: float,
    options: RenderOptions,
    heartbeat: Callable[[], None] | None = None,
) -> RenderedClip:
    """Render ``[start, end]`` of ``source`` to ``target`` (a temp location) and validate it.

    ``heartbeat`` is called every ``heartbeat_interval_seconds`` while FFmpeg runs so a
    long render can prove it is alive. On any failure the partial output is removed.
    """
    if not source.is_file() or source.stat().st_size == 0:
        raise RenderError("source_missing", "The source video file is missing")
    try:
        source_meta = probe(source, ffprobe_path=options.ffprobe_path)
    except ProbeError:
        raise RenderError("source_unreadable", "The source video could not be read") from None

    duration = validate_range(
        start, end, source_meta.duration_seconds, options.source_tolerance_seconds
    )
    has_audio = source_meta.audio_codec is not None
    command = build_render_command(
        options.ffmpeg_path,
        source,
        target,
        start=start,
        duration=duration,
        has_audio=has_audio,
        preset=options.preset,
        crf=options.crf,
        audio_bitrate=options.audio_bitrate,
    )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    try:
        _run_ffmpeg(command, options, heartbeat)
        if not target.is_file() or target.stat().st_size == 0:
            raise RenderError("invalid_output", "Rendering produced no output")
        return _validate_output(target, duration, has_audio, options)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _run_ffmpeg(
    command: list[str], options: RenderOptions, heartbeat: Callable[[], None] | None
) -> None:
    # stderr goes to a temp file (never a pipe that could fill up and stall FFmpeg); only a
    # bounded tail is logged, and nothing from it is ever shown to users.
    with tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr
            )
        except FileNotFoundError:
            raise RenderError("ffmpeg_missing", "ffmpeg is not installed on the server") from None

        deadline = time.monotonic() + options.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise RenderError(
                    "render_timeout",
                    f"Rendering timed out after {options.timeout_seconds:g} seconds",
                )
            try:
                process.wait(timeout=min(options.heartbeat_interval_seconds, remaining))
                break
            except subprocess.TimeoutExpired:
                if heartbeat is not None:
                    heartbeat()

        if process.returncode != 0:
            stderr.seek(0, os.SEEK_END)
            stderr.seek(max(0, stderr.tell() - STDERR_TAIL_BYTES))
            tail = stderr.read().decode(errors="replace")
            logger.warning("ffmpeg failed (exit %s): %s", process.returncode, tail)
            raise RenderError(
                "ffmpeg_failed", f"Rendering failed (ffmpeg exit code {process.returncode})"
            )


def _validate_output(
    target: Path, expected_duration: float, has_audio: bool, options: RenderOptions
) -> RenderedClip:
    try:
        meta: VideoMetadata = probe(target, ffprobe_path=options.ffprobe_path)
    except ProbeError:
        raise RenderError("invalid_output", "The rendered clip could not be read back") from None
    if meta.video_codec != "h264":
        raise RenderError("invalid_output", "The rendered clip does not contain H.264 video")
    if not meta.width or not meta.height:
        raise RenderError("invalid_output", "The rendered clip has no picture size")
    if meta.duration_seconds is None:
        raise RenderError("invalid_output", "The rendered clip has no duration")
    if abs(meta.duration_seconds - expected_duration) > options.duration_tolerance_seconds:
        raise RenderError(
            "invalid_output",
            f"The rendered clip lasts {meta.duration_seconds:.2f}s instead of "
            f"{expected_duration:.2f}s",
        )
    if has_audio and meta.audio_codec != AUDIO_CODEC:
        raise RenderError("invalid_output", "The rendered clip is missing its audio track")
    if not has_audio and meta.audio_codec is not None:
        raise RenderError("invalid_output", "The rendered clip has an unexpected audio track")
    return RenderedClip(
        path=target,
        size_bytes=target.stat().st_size,
        duration_seconds=meta.duration_seconds,
        width=meta.width,
        height=meta.height,
        fps=meta.fps,
        video_codec=meta.video_codec,
        audio_codec=meta.audio_codec,
    )
