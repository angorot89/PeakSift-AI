"""Representative frames of a B-roll video for semantic indexing: bounded, deterministic, cheap.

A video is never embedded frame by frame. It is represented by at most
``SEMANTIC_VIDEO_MAX_FRAMES`` frames (default 8), so a ten-minute upload costs the same handful
of model runs as a short clip:

1. **Targets.** ``frames = clamp(ceil(duration / SECONDS_PER_FRAME), 1, max_frames)`` — about
   one frame per two seconds for short B-roll, never more than the bound.
2. **Candidates.** Twice that many times, evenly spaced over the video after skipping a short
   margin at each end (where fades, black leaders and encoder padding live). Times are computed
   from the probed duration and formatted by this module only; nothing user-supplied reaches
   FFmpeg.
3. **Extraction.** One FFmpeg call per candidate (fast input seeking, one frame, display
   orientation and pixel aspect applied, downscaled to at most ``FRAME_WIDTH`` px wide, PNG in
   the attempt's workspace), each with a timeout. A candidate FFmpeg cannot decode (corrupt
   data, past the real end of a VFR file) is skipped.
4. **Filtering** with lightweight, deterministic checks: nearly black or empty frames
   (low mean *and* low contrast) and near-duplicates of an already kept frame (tiny greyscale
   thumbnails compared pixel by pixel) are dropped — not a scene detector, just enough to spend
   the budget on distinct pictures.
5. **Selection.** If more frames survive than the target, an evenly spaced subset is kept, so
   the whole video stays represented (start, middle and end regions).

Each kept frame keeps its time in the asset, so a query can match one scene of a longer video
and later point at it (``best_frame_time``).
"""

import math
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

SECONDS_PER_FRAME = 2.0
EDGE_MARGIN_SECONDS = 0.25
EDGE_MARGIN_FRACTION = 0.05
FRAME_WIDTH = 640
DARK_MEAN = 16.0  # 0-255 luma
DARK_SPREAD = 10.0
EMPTY_SPREAD = 2.0  # a perfectly flat frame (any brightness) has no picture to match
DUPLICATE_DIFFERENCE = 4.0  # mean absolute difference of 16×16 greyscale thumbnails


class SamplingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SampledFrame:
    time: float  # seconds into the asset
    image: Image.Image


def target_count(duration: float, max_frames: int) -> int:
    if not math.isfinite(duration) or duration <= 0:
        return 1
    return max(1, min(max_frames, math.ceil(duration / SECONDS_PER_FRAME)))


def candidate_times(duration: float, max_frames: int) -> list[float]:
    """Evenly spaced, rounded to milliseconds, strictly inside the video (deterministic)."""
    if not math.isfinite(duration) or duration <= 0:
        return [0.0]
    margin = min(EDGE_MARGIN_SECONDS, duration * EDGE_MARGIN_FRACTION)
    span = duration - 2 * margin
    count = 2 * target_count(duration, max_frames)
    return [round(margin + span * (i + 0.5) / count, 3) for i in range(count)]


def _grey(image: Image.Image, size: int) -> np.ndarray:
    return np.asarray(image.convert("L").resize((size, size), Image.Resampling.BILINEAR), float)


def is_empty(image: Image.Image) -> bool:
    """Nearly black (dark and low contrast) or completely flat."""
    pixels = _grey(image, 32)
    mean, spread = float(pixels.mean()), float(pixels.std())
    return (mean < DARK_MEAN and spread < DARK_SPREAD) or spread < EMPTY_SPREAD


def is_duplicate(image: Image.Image, kept: list[np.ndarray]) -> bool:
    thumb = _grey(image, 16)
    return any(float(np.abs(thumb - other).mean()) < DUPLICATE_DIFFERENCE for other in kept)


def evenly(items: list, count: int) -> list:
    """``count`` items spread over the list, first and last included when possible."""
    if len(items) <= count:
        return items
    if count == 1:
        return [items[len(items) // 2]]
    step = (len(items) - 1) / (count - 1)
    return [items[round(i * step)] for i in range(count)]


Runner = Callable[[list[str], float], int]


def _run(command: list[str], timeout: float) -> int:
    try:
        completed = subprocess.run(  # noqa: S603 - argument list, no shell
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout,
            check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return -1
    return completed.returncode


def extract_frame(
    source: Path, time: float, target: Path, *, ffmpeg_path: str, timeout: float,
    runner: Runner = _run,
) -> Image.Image | None:  # fmt: skip
    """One frame at ``time`` (display orientation, square pixels, ≤ FRAME_WIDTH wide), or None
    when FFmpeg cannot produce one there."""
    if not math.isfinite(time) or time < 0:
        return None
    command = [
        ffmpeg_path, "-nostdin", "-v", "error", "-y",
        "-ss", f"{time:.3f}", "-i", str(source),
        "-frames:v", "1", "-an", "-sn", "-dn",
        "-vf", f"scale=iw*sar:ih,setsar=1,scale=w='min({FRAME_WIDTH},iw)':h=-2",
        "-pix_fmt", "rgb24", "-f", "image2", "-c:v", "png", str(target),
    ]  # fmt: skip
    if runner(command, timeout) != 0 or not target.is_file():
        return None
    try:
        with Image.open(target, formats=["PNG"]) as opened:
            opened.load()
            return opened.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def sample_video(
    source: Path, duration: float, work: Path, *, ffmpeg_path: str, max_frames: int,
    timeout: float, runner: Runner = _run,
) -> list[SampledFrame]:  # fmt: skip
    """The representative frames of a video, in time order. Raises SamplingError when none of
    the candidates gives a usable picture."""
    kept: list[SampledFrame] = []
    thumbs: list[np.ndarray] = []
    decoded = 0
    for position, time in enumerate(candidate_times(duration, max_frames)):
        image = extract_frame(
            source, time, work / f"frame-{position:03d}.png", ffmpeg_path=ffmpeg_path,
            timeout=timeout, runner=runner,
        )  # fmt: skip
        if image is None:
            continue
        decoded += 1
        if is_empty(image) or is_duplicate(image, thumbs):
            continue
        kept.append(SampledFrame(time, image))
        thumbs.append(_grey(image, 16))
    if not kept:
        if decoded:
            raise SamplingError("no_frames", "No usable picture was found in this video")
        raise SamplingError("unreadable_video", "The video could not be read")
    return evenly(kept, target_count(duration, max_frames))
