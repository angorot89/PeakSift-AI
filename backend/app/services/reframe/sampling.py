"""Sample downscaled frames from a clip for subject detection.

FFmpeg decodes the clip, applies its rotation metadata (so frames are display-oriented),
keeps ``sample_fps`` frames per second, scales them to ``analysis_width`` and writes raw RGB
to a pipe. Frames are yielded one at a time, so memory stays bounded by a single frame and
nothing is written to disk — there are no temporary frame files to leak or clean up.

Timestamps are clip-local seconds: frame ``n`` is the picture on screen at ``t = n /
sample_fps``. The ``fps`` filter runs with ``round=up``: its default (``near``) emits the last
frame of each rounding window, i.e. up to half a sample period *after* ``t``, which would make
the crop path lag the video (measured: ~0.2 s late at 2 fps; tested against direct seeks).

The detector does not need full resolution: at the default 640 px width a 1080p face is
still dozens of pixels wide, while decoding, scaling and inference cost drop by an order of
magnitude. Geometry stays normalized, so the analysis size never leaks into the crop path.

Security: an argument list (never a shell), the only variable parts are the generated clip
path and validated numbers; a hard timeout kills FFmpeg; stderr is never stored or shown.
"""

import json
import math
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

MAX_SAMPLES = 20_000  # far beyond any clip length at sane rates; guards runaway output


class SamplingError(Exception):
    """Frames could not be sampled. ``message`` is safe to store and show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SourceGeometry:
    """The clip's display-oriented size (rotation applied) and duration."""

    width: int
    height: int
    duration_seconds: float


@dataclass(frozen=True)
class SampledFrame:
    """One analysis frame: clip-local time, size and packed RGB24 pixels (row-major)."""

    index: int
    timestamp: float
    width: int
    height: int
    rgb: bytes


def _rotation(stream: dict) -> int:
    """Rotation in degrees from the stream's display matrix or legacy ``rotate`` tag."""
    for item in stream.get("side_data_list") or []:
        if isinstance(item, dict) and "rotation" in item:
            try:
                return int(round(float(item["rotation"])))
            except (TypeError, ValueError):
                return 0
    tags = stream.get("tags") or {}
    try:
        return int(tags.get("rotate", 0))
    except (TypeError, ValueError):
        return 0


def probe_geometry(path: Path, *, ffprobe_path: str, timeout_seconds: float = 30) -> SourceGeometry:
    """Display-oriented size and duration. Raises SamplingError with a safe message."""
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
        raise SamplingError("ffprobe_missing", "ffprobe is not installed on the server") from None
    except subprocess.TimeoutExpired:
        raise SamplingError("source_unreadable", "Reading the clip timed out") from None
    if result.returncode != 0:
        raise SamplingError("source_unreadable", "The clip could not be read")
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise SamplingError("source_unreadable", "The clip could not be read") from None
    streams = [s for s in data.get("streams", []) if isinstance(s, dict)]
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise SamplingError("source_unreadable", "The clip has no video stream")
    width, height = video.get("width"), video.get("height")
    if not (isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0):
        raise SamplingError("source_unreadable", "The clip has no usable picture size")
    if abs(_rotation(video)) % 180 == 90:
        width, height = height, width
    try:
        duration = float((data.get("format") or {}).get("duration") or video.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        raise SamplingError("source_unreadable", "The clip has no duration")
    return SourceGeometry(width=width, height=height, duration_seconds=duration)


def analysis_size(source: SourceGeometry, analysis_width: int) -> tuple[int, int]:
    """Downscaled (never upscaled) size with the source's aspect ratio, both sides even."""
    width = min(analysis_width, source.width)
    height = round(source.height * width / source.width)
    width, height = max(2, width - width % 2), max(2, height - height % 2)
    return width, height


def expected_samples(duration_seconds: float, sample_fps: float) -> int:
    """How many frames FFmpeg's fps filter emits for this duration (used for progress)."""
    return max(1, math.ceil(duration_seconds * sample_fps - 1e-6))


def sample_frames(
    path: Path,
    source: SourceGeometry,
    *,
    ffmpeg_path: str,
    sample_fps: float,
    analysis_width: int,
    timeout_seconds: float,
    heartbeat: Callable[[], None] | None = None,
    heartbeat_interval_seconds: float = 15,
) -> Iterator[SampledFrame]:
    """Yield display-oriented, downscaled RGB frames at ``sample_fps``.

    Closing the generator early (or any error) kills FFmpeg. Raises SamplingError.
    """
    if not math.isfinite(sample_fps) or sample_fps <= 0:
        raise ValueError("sample_fps must be positive")
    if not path.is_file():
        raise SamplingError("source_missing", "The clip file is missing")
    width, height = analysis_size(source, analysis_width)
    frame_bytes = width * height * 3
    command = [
        ffmpeg_path,
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"fps={sample_fps:g}:round=up,scale={width}:{height}:flags=area,format=rgb24",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        raise SamplingError("ffmpeg_missing", "ffmpeg is not installed on the server") from None

    # A watchdog kills FFmpeg at the deadline, so even a blocked pipe read cannot hang.
    timed_out = threading.Event()

    def expire() -> None:
        timed_out.set()
        if process.poll() is None:
            process.kill()

    watchdog = threading.Timer(timeout_seconds, expire)
    watchdog.daemon = True
    watchdog.start()
    last_beat = time.monotonic()
    index = 0
    try:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(frame_bytes)
            if timed_out.is_set():
                raise SamplingError("sampling_timeout", "Sampling the clip took too long")
            if not chunk:
                break
            if len(chunk) != frame_bytes:
                raise SamplingError("sampling_failed", "The clip could not be decoded completely")
            if index >= MAX_SAMPLES:
                raise SamplingError("sampling_failed", "The clip produced too many frames")
            yield SampledFrame(
                index=index,
                timestamp=round(index / sample_fps, 6),
                width=width,
                height=height,
                rgb=chunk,
            )
            index += 1
            if heartbeat and time.monotonic() - last_beat >= heartbeat_interval_seconds:
                heartbeat()
                last_beat = time.monotonic()
        code = process.wait()
        if timed_out.is_set():
            raise SamplingError("sampling_timeout", "Sampling the clip took too long")
        if code != 0:
            raise SamplingError("sampling_failed", "The clip could not be decoded")
        if index == 0:
            raise SamplingError("sampling_failed", "No frames could be read from the clip")
    finally:
        watchdog.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
        if process.stdout is not None:
            process.stdout.close()
