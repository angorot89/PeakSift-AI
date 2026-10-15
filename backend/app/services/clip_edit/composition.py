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

Output: fast-start MP4, H.264 (libx264, yuv420p), AAC when the source has audio — or, when
the edit has an audio section, AAC from the prepared, mixed and finished track (a second
input; see ``app/services/audio_mix``), which replaces the clip's own audio stream.
"""

import logging
import math
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.services.clip_edit.config import OUTPUT_HEIGHT, OUTPUT_WIDTH, Layout
from app.services.clip_edit.smart_crop import CropPoint, smart_crop_filter
from app.services.clip_render.renderer import (
    AUDIO_CODEC,
    PIXEL_FORMAT,
    VIDEO_CODEC,
    RenderError,
    RenderOptions,
    run_ffmpeg,
)
from app.services.ffprobe import ProbeError, VideoMetadata, probe
from app.services.reframe.path import CropGeometry
from app.services.reframe.sampling import SamplingError, probe_geometry

logger = logging.getLogger(__name__)

# Fixed name of the caption file inside the render workspace (FFmpeg runs with cwd there).
CAPTIONS_FILENAME = "captions.ass"
FIT_BACKGROUND = "0x111113"  # the app's surface colour
# Background blur is computed at quarter resolution, then scaled up: strong and cheap.
BLUR_SCALE_DIVISOR = 4
BLUR_SIGMA = 12
DEFAULT_CAPTION_FONT = "Noto Sans"


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


# Only successful probes are cached: a transient failure is checked again next time.
_FILTERS: dict[str, frozenset[str]] = {}
_TEXT_RENDERS: set[tuple[str, str]] = set()
# The probe frame is 9:16 like the output, so the caption scales as it will in the short.
PROBE_SIZE = "360x640"
PROBE_MIN_TEXT_PIXELS = 20


def ffmpeg_filters(ffmpeg_path: str) -> frozenset[str] | None:
    """The filter names this FFmpeg build offers, or ``None`` when it cannot be run."""
    if ffmpeg_path in _FILTERS:
        return _FILTERS[ffmpeg_path]
    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-filters"],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    names = frozenset(
        parts[1]
        for line in result.stdout.decode(errors="replace").splitlines()
        if len(parts := line.split()) >= 2
    )
    _FILTERS[ffmpeg_path] = names
    return names


def supports_captions(ffmpeg_path: str) -> bool:
    """Whether this FFmpeg build has libass (the ``subtitles`` filter)."""
    filters = ffmpeg_filters(ffmpeg_path)
    return filters is not None and "subtitles" in filters


def caption_text_renders(ffmpeg_path: str, font_family: str) -> bool:
    """Burn a probe caption onto a black frame and check that text pixels appear.

    libass draws nothing when no usable font is installed, which would otherwise produce a
    "captioned" short without visible captions. Font fallback (any installed font) counts
    as working; only "no glyphs at all" fails. Successful results are cached per process.
    """
    if (ffmpeg_path, font_family) in _TEXT_RENDERS:
        return True
    from app.services.clip_edit.caption_styles import build_ass_document
    from app.services.clip_edit.captions import Cue
    from app.services.clip_edit.config import CaptionPosition, CaptionStyle

    document = build_ass_document(
        [Cue(start=0.0, end=1.0, text="Hg PeakSift")],
        style=CaptionStyle.BOLD,
        position=CaptionPosition.CENTER,
        font_family=font_family,
    )
    with tempfile.TemporaryDirectory(prefix="peaksift-caption-probe-") as directory:
        (Path(directory) / CAPTIONS_FILENAME).write_text(document, encoding="utf-8")
        command = [
            ffmpeg_path,
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={PROBE_SIZE}:d=1",
            "-vf",
            f"subtitles=filename={CAPTIONS_FILENAME}",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ]
        try:
            result = subprocess.run(
                command, cwd=directory, capture_output=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
    if result.returncode != 0:
        return False
    if sum(1 for value in result.stdout if value > 128) < PROBE_MIN_TEXT_PIXELS:
        return False
    _TEXT_RENDERS.add((ffmpeg_path, font_family))
    return True


def require_caption_rendering(ffmpeg_path: str, font_family: str) -> None:
    """Raise a safe, specific ``RenderError`` unless captions can really be drawn."""
    filters = ffmpeg_filters(ffmpeg_path)
    if filters is None:
        raise RenderError("ffmpeg_missing", "ffmpeg is not installed on the server")
    if "subtitles" not in filters:
        raise RenderError(
            "captions_unavailable",
            "This server's FFmpeg cannot render captions (libass is missing)",
        )
    if not caption_text_renders(ffmpeg_path, font_family):
        raise RenderError(
            "caption_font_unavailable",
            "Captions could not be drawn: no usable caption font is installed on the server",
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
    if layout in (Layout.SMART_REFRAME, Layout.MANUAL_CROP):
        raise ValueError("Smart and manual crops are built from crop points (smart_crop_filter)")
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
    video_graph: str | None = None,
    audio_track: Path | None = None,
) -> list[str]:
    # Smart reframe passes its own validated crop graph; every other layout uses constants.
    graph = video_graph if video_graph is not None else layout_filter(layout)
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
    ]
    if audio_track is not None:
        command += ["-i", str(audio_track)]
    command += [
        "-filter_complex",
        graph,
        "-map",
        video_label,
    ]
    if audio_track is not None:
        command += ["-map", "1:a:0"]
    elif has_audio:
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
    if has_audio or audio_track is not None:
        command += ["-c:a", AUDIO_CODEC, "-b:a", audio_bitrate]
    command += ["-movflags", "+faststart", "-f", "mp4", str(target)]
    return command


def manual_crop_point(width: int, height: int, focus: tuple[float, float]) -> CropPoint:
    """A fixed 9:16 crop centred on the focal point, clamped inside the source."""
    fx, fy = focus
    if not all(isinstance(v, int | float) and math.isfinite(v) and 0 <= v <= 1 for v in (fx, fy)):
        raise RenderError("invalid_focus", "The focal point must lie inside the frame")
    geometry = CropGeometry.for_source(width, height)
    cx = min(1 - geometry.crop_width / 2, max(geometry.crop_width / 2, fx))
    cy = min(1 - geometry.crop_height / 2, max(geometry.crop_height / 2, fy))
    return CropPoint(0.0, cx, cy, geometry.crop_width, geometry.crop_height)


def _manual_point(source: Path, focus: tuple[float, float], options: RenderOptions) -> CropPoint:
    try:
        geometry = probe_geometry(source, ffprobe_path=options.ffprobe_path)
    except SamplingError:
        raise RenderError("source_unreadable", "The generated clip could not be read") from None
    return manual_crop_point(geometry.width, geometry.height, focus)


def compose_short(
    source: Path,
    target: Path,
    *,
    layout: Layout,
    options: RenderOptions,
    workspace: Path | None = None,
    captions: bool = False,
    caption_font: str = DEFAULT_CAPTION_FONT,
    heartbeat: Callable[[], None] | None = None,
    crop_points: Sequence[CropPoint] | None = None,
    focus: tuple[float, float] | None = None,
    audio: Path | None = None,
) -> ComposedShort:
    """Render ``source`` (a generated clip) as a 1080 × 1920 short into ``target``.

    With ``captions``, ``workspace/captions.ass`` must exist; FFmpeg runs inside
    ``workspace``. Smart reframe needs ``crop_points`` (a validated crop path): the moving crop
    is applied first, then scaling to 1080 × 1920, then captions — so captions stay fixed on
    screen while the framing moves. The partial output is removed on any failure.
    """
    if not source.is_file() or source.stat().st_size == 0:
        raise RenderError("source_missing", "The generated clip file is missing")
    if captions and (workspace is None or not (workspace / CAPTIONS_FILENAME).is_file()):
        raise RenderError("captions_missing", "The caption file was not prepared")
    if captions:
        require_caption_rendering(options.ffmpeg_path, caption_font)
    try:
        source_meta = probe(source, ffprobe_path=options.ffprobe_path)
    except ProbeError:
        raise RenderError("source_unreadable", "The generated clip could not be read") from None
    if not source_meta.duration_seconds:
        raise RenderError("source_unreadable", "The generated clip has no duration")
    has_audio = source_meta.audio_codec is not None or audio is not None
    if audio is not None and (not audio.is_file() or audio.stat().st_size == 0):
        raise RenderError("audio_mix_failed", "The prepared audio is missing")

    video_graph = None
    if layout == Layout.MANUAL_CROP:
        if focus is None:
            raise RenderError("invalid_focus", "The focal point is missing")
        crop_points = [_manual_point(source, focus, options)]
    if layout in (Layout.SMART_REFRAME, Layout.MANUAL_CROP):
        if not crop_points:
            raise RenderError("reframe_unavailable", "The framing path is not available")
        try:
            geometry = probe_geometry(source, ffprobe_path=options.ffprobe_path)
        except SamplingError:
            raise RenderError("source_unreadable", "The generated clip could not be read") from None
        try:
            video_graph = smart_crop_filter(
                crop_points, geometry.width, geometry.height, OUTPUT_WIDTH, OUTPUT_HEIGHT
            )
        except ValueError:
            raise RenderError("invalid_path", "The framing path is not valid") from None

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
        video_graph=video_graph,
        audio_track=audio,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    redactions = {str(source): "<source>", str(target): "<output>"}
    if workspace is not None:
        redactions[str(workspace)] = "<workspace>"
    if audio is not None:
        redactions[str(audio)] = "<audio>"
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
