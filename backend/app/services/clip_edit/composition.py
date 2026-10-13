"""Compose a generated clip into a 9:16 short (1080 × 1920) with FFmpeg.

Layouts (all keep the source's aspect ratio — nothing is ever stretched):

- ``center_crop``  scale until the frame is *filled*, then crop the centre
- ``blur_background``  the whole frame scaled to *fit*, centred over a blurred, filled copy
- ``fit``  the whole frame scaled to fit on a plain dark background

Filtergraphs are built only from constants selected by the validated ``Layout`` enum; no
request value or transcript text ever reaches them. Captions (later step) are a separate
ASS file referenced by a fixed relative name with FFmpeg running inside the workspace, so
no filesystem path is embedded in a filtergraph either. Rotation metadata is applied while
decoding, so phone footage is composed upright.

Output: fast-start MP4, H.264 (libx264, yuv420p), AAC when the source has audio.
"""

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.clip_edit.config import OUTPUT_HEIGHT, OUTPUT_WIDTH, Layout
from app.services.clip_render.renderer import (
    AUDIO_CODEC,
    PIXEL_FORMAT,
    VIDEO_CODEC,
    RenderError,
    RenderOptions,
    run_ffmpeg,
)
from app.services.ffprobe import ProbeError, VideoMetadata, probe

logger = logging.getLogger(__name__)

# Fixed name of the caption file inside the render workspace (FFmpeg runs with cwd there).
CAPTIONS_FILENAME = "captions.ass"
FIT_BACKGROUND = "0x111113"  # the app's surface colour
# Background blur is computed at quarter resolution, then scaled up: strong and cheap.
BLUR_SCALE_DIVISOR = 4
BLUR_SIGMA = 12


@dataclass(frozen=True)
class ComposedShort:
    path: Path
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    fps: float | None
    video_codec: str
    audio_codec: str | None


@lru_cache(maxsize=8)
def supports_captions(ffmpeg_path: str) -> bool:
    """Whether this FFmpeg build has libass (the ``subtitles`` filter). Cached per binary."""
    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-filters"],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return any(
        line.split()[1:2] == ["subtitles"]
        for line in result.stdout.decode(errors="replace").splitlines()
    )


def layout_filter(layout: Layout, width: int = OUTPUT_WIDTH, height: int = OUTPUT_HEIGHT) -> str:
    """Filtergraph from ``[0:v]`` to ``[framed]``. Only constants and validated enums."""
    fill = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    fit = f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    if layout == Layout.CENTER_CROP:
        return f"[0:v]{fill},setsar=1[framed]"
    if layout == Layout.FIT:
        return (
            f"[0:v]{fit},pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={FIT_BACKGROUND},"
            "setsar=1[framed]"
        )
    if layout == Layout.BLUR_BACKGROUND:
        small_w, small_h = width // BLUR_SCALE_DIVISOR, height // BLUR_SCALE_DIVISOR
        return (
            "[0:v]split=2[bg][fg];"
            f"[bg]scale={small_w}:{small_h}:force_original_aspect_ratio=increase,"
            f"crop={small_w}:{small_h},gblur=sigma={BLUR_SIGMA},"
            f"scale={width}:{height}[blurred];"
            f"[fg]{fit}[front];"
            "[blurred][front]overlay=(W-w)/2:(H-h)/2,setsar=1[framed]"
        )
    raise ValueError(f"Unsupported layout: {layout!r}")


def build_edit_command(
    ffmpeg_path: str,
    source: Path,
    target: Path,
    *,
    layout: Layout,
    has_audio: bool,
    captions: bool,
    preset: str,
    crf: int,
    audio_bitrate: str,
) -> list[str]:
    graph = layout_filter(layout)
    if captions:
        # A fixed relative name: FFmpeg runs with the workspace as its working directory.
        graph += f";[framed]subtitles=filename={CAPTIONS_FILENAME}[out]"
        video_label = "[out]"
    else:
        video_label = "[framed]"
    command = [
        ffmpeg_path,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        graph,
        "-map",
        video_label,
    ]
    if has_audio:
        command += ["-map", "0:a:0"]
    command += [
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-c:v",
        VIDEO_CODEC,
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        PIXEL_FORMAT,
    ]
    if has_audio:
        command += ["-c:a", AUDIO_CODEC, "-b:a", audio_bitrate]
    command += ["-movflags", "+faststart", "-f", "mp4", str(target)]
    return command


def compose_short(
    source: Path,
    target: Path,
    *,
    layout: Layout,
    options: RenderOptions,
    workspace: Path | None = None,
    captions: bool = False,
    heartbeat: Callable[[], None] | None = None,
) -> ComposedShort:
    """Render ``source`` (a generated clip) as a 1080 × 1920 short into ``target``.

    With ``captions``, ``workspace/captions.ass`` must exist; FFmpeg runs inside
    ``workspace``. The partial output is removed on any failure.
    """
    if not source.is_file() or source.stat().st_size == 0:
        raise RenderError("source_missing", "The generated clip file is missing")
    if captions and (workspace is None or not (workspace / CAPTIONS_FILENAME).is_file()):
        raise RenderError("captions_missing", "The caption file was not prepared")
    if captions and not supports_captions(options.ffmpeg_path):
        raise RenderError(
            "captions_unavailable",
            "This server's FFmpeg cannot render captions (libass is missing)",
        )
    try:
        source_meta = probe(source, ffprobe_path=options.ffprobe_path)
    except ProbeError:
        raise RenderError("source_unreadable", "The generated clip could not be read") from None
    if not source_meta.duration_seconds:
        raise RenderError("source_unreadable", "The generated clip has no duration")
    has_audio = source_meta.audio_codec is not None

    command = build_edit_command(
        options.ffmpeg_path,
        source,
        target,
        layout=layout,
        has_audio=has_audio,
        captions=captions,
        preset=options.preset,
        crf=options.crf,
        audio_bitrate=options.audio_bitrate,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    redactions = {str(source): "<source>", str(target): "<output>"}
    if workspace is not None:
        redactions[str(workspace)] = "<workspace>"
    try:
        run_ffmpeg(command, options, heartbeat, redactions, cwd=workspace)
        if not target.is_file() or target.stat().st_size == 0:
            raise RenderError("invalid_output", "Rendering produced no output")
        return _validate(target, source_meta, has_audio, options)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _validate(
    target: Path, source_meta: VideoMetadata, has_audio: bool, options: RenderOptions
) -> ComposedShort:
    try:
        meta = probe(target, ffprobe_path=options.ffprobe_path)
    except ProbeError:
        raise RenderError("invalid_output", "The rendered short could not be read back") from None
    if meta.video_codec != "h264":
        raise RenderError("invalid_output", "The rendered short does not contain H.264 video")
    if (meta.width, meta.height) != (OUTPUT_WIDTH, OUTPUT_HEIGHT):
        raise RenderError(
            "invalid_output",
            f"The rendered short is {meta.width}x{meta.height}, not {OUTPUT_WIDTH}x{OUTPUT_HEIGHT}",
        )
    if not meta.fps or meta.fps <= 0:
        raise RenderError("invalid_output", "The rendered short has no frame rate")
    expected = source_meta.duration_seconds or 0.0
    if meta.duration_seconds is None or (
        abs(meta.duration_seconds - expected) > options.duration_tolerance_seconds
    ):
        raise RenderError(
            "invalid_output", "The rendered short's duration does not match the source clip"
        )
    if has_audio and meta.audio_codec != AUDIO_CODEC:
        raise RenderError("invalid_output", "The rendered short is missing its audio track")
    if not has_audio and meta.audio_codec is not None:
        raise RenderError("invalid_output", "The rendered short has an unexpected audio track")
    return ComposedShort(
        path=target,
        size_bytes=target.stat().st_size,
        duration_seconds=meta.duration_seconds,
        width=meta.width,
        height=meta.height,
        fps=meta.fps,
        video_codec=meta.video_codec,
        audio_codec=meta.audio_codec,
    )
