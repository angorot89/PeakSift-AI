"""Render the kept parts of a clip back to back, before the Short is composed.

The V0.5 clip file stays read-only: the tightened copy is written into the attempt's
workspace, near-lossless (x264 at a low CRF, PCM audio in Matroska) because the composition
encodes it once more. Each join gets a few milliseconds of audio fade so a cut never clicks.
Only module-formatted numbers reach the filtergraph; the file is an input, never a name in it.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

from app.services.clip_render.renderer import RenderError, RenderOptions, run_ffmpeg
from app.services.ffprobe import ProbeError, probe

TIGHTENED_NAME = "tightened.mkv"
INTERMEDIATE_CRF = 12
INTERMEDIATE_PRESET = "veryfast"
JOIN_FADE_SECONDS = 0.012  # long enough to remove the click, far too short to hear


def _n(value: float) -> str:
    return f"{value:.3f}"


def tighten_graph(kept: Sequence[tuple[float, float]], has_audio: bool) -> str:
    """trim/atrim each kept piece, then concat them (video, and audio when there is any)."""
    if not kept:
        raise ValueError("Nothing is kept")
    parts: list[str] = []
    labels: list[str] = []
    for index, (start, end) in enumerate(kept):
        if not (0 <= start < end):
            raise ValueError("Invalid kept range")
        parts.append(f"[0:v]trim=start={_n(start)}:end={_n(end)},setpts=PTS-STARTPTS[v{index}]")
        labels.append(f"[v{index}]")
        if has_audio:
            length = end - start
            fade = min(JOIN_FADE_SECONDS, length / 4)
            parts.append(
                f"[0:a]atrim=start={_n(start)}:end={_n(end)},asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d={_n(fade)},"
                f"afade=t=out:st={_n(length - fade)}:d={_n(fade)}[a{index}]"
            )
            labels.append(f"[a{index}]")
    audio = 1 if has_audio else 0
    parts.append(
        f"{''.join(labels)}concat=n={len(kept)}:v=1:a={audio}[v]" + ("[a]" if audio else "")
    )
    return ";".join(parts)


def tighten_command(
    ffmpeg_path: str,
    source: Path,
    target: Path,
    kept: Sequence[tuple[float, float]],
    has_audio: bool,
) -> list[str]:
    command = [
        ffmpeg_path, "-v", "error", "-nostdin", "-y", "-i", str(source),
        "-filter_complex", tighten_graph(kept, has_audio), "-map", "[v]",
    ]  # fmt: skip
    if has_audio:
        command += ["-map", "[a]", "-c:a", "pcm_s16le"]
    command += [
        "-sn", "-dn", "-map_metadata", "-1",
        "-c:v", "libx264", "-preset", INTERMEDIATE_PRESET, "-crf", str(INTERMEDIATE_CRF),
        "-pix_fmt", "yuv420p", "-f", "matroska", str(target),
    ]  # fmt: skip
    return command


def tighten_clip(
    source: Path,
    workspace: Path,
    kept: Sequence[tuple[float, float]],
    options: RenderOptions,
    heartbeat: Callable[[], None] | None = None,
) -> Path:
    """Write the kept pieces of ``source`` into the workspace; validate the result's length."""
    try:
        meta = probe(source, ffprobe_path=options.ffprobe_path)
    except ProbeError:
        raise RenderError("source_unreadable", "The generated clip could not be read") from None
    has_audio = meta.audio_codec is not None
    target = workspace / TIGHTENED_NAME
    target.unlink(missing_ok=True)
    command = tighten_command(options.ffmpeg_path, source, target, kept, has_audio)
    try:
        run_ffmpeg(
            command,
            options,
            heartbeat,
            {str(source): "<source>", str(target): "<tightened>", str(workspace): "<workspace>"},
        )
        result = probe(target, ffprobe_path=options.ffprobe_path)
    except ProbeError:
        target.unlink(missing_ok=True)
        raise RenderError("invalid_output", "The tightened clip could not be read back") from None
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    expected = sum(end - start for start, end in kept)
    if (
        result.duration_seconds is None
        or abs(result.duration_seconds - expected) > options.duration_tolerance_seconds
        or (has_audio and result.audio_codec is None)
    ):
        target.unlink(missing_ok=True)
        raise RenderError("invalid_output", "The tightened clip does not have the expected length")
    return target
