"""Render a short's audio mix into the render attempt's workspace (one FFmpeg run)."""

from collections.abc import Callable
from pathlib import Path

from app.services.audio_mix.loudness import Loudness, finish_audio
from app.services.audio_mix.plan import MixPlanRequest, build_mix_command
from app.services.clip_render.renderer import RenderError, RenderOptions, run_ffmpeg


def render_mix(
    request: MixPlanRequest,
    target: Path,
    options: RenderOptions,
    heartbeat: Callable[[], None] | None = None,
) -> Path:
    """Write the mixed audio (48 kHz stereo float WAV) to ``target``.

    FFmpeg errors are logged with every file path redacted and reported as a safe
    ``audio_mix_failed``; a partial file is never left behind.
    """
    try:
        command = build_mix_command(options.ffmpeg_path, request, target)
    except ValueError:
        raise RenderError("audio_mix_failed", "The audio settings could not be mixed") from None
    redactions = {str(target): "<mix>", str(target.parent): "<workspace>"}
    if request.source is not None:
        redactions[str(request.source)] = "<source>"
    if request.music is not None:
        redactions[str(request.music.path)] = "<music>"
    for effect in request.sfx:
        redactions[str(effect.path)] = "<sfx>"
    target.unlink(missing_ok=True)
    try:
        run_ffmpeg(command, options, heartbeat, redactions)
        if not target.is_file() or target.stat().st_size == 0:
            raise RenderError("audio_mix_failed", "The audio mix came out empty")
    except RenderError as error:
        target.unlink(missing_ok=True)
        if error.code in ("ffmpeg_missing", "render_timeout"):
            raise
        raise RenderError("audio_mix_failed", "The audio mix could not be rendered") from None
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def prepare_track(
    request: MixPlanRequest,
    workspace: Path,
    *,
    normalize: bool,
    options: RenderOptions,
    heartbeat: Callable[[], None] | None = None,
) -> tuple[Path, Loudness | None]:
    """Mix, then finish (limit, optionally normalize) the short's audio inside ``workspace``.

    Returns the final WAV and the loudness measurement used. Intermediate files stay in the
    attempt's workspace, which the render pipeline removes on success and on failure.
    """
    mixed = render_mix(request, workspace / "audio-mix.wav", options, heartbeat)
    final = workspace / "audio-final.wav"
    loudness = finish_audio(mixed, final, normalize=normalize, options=options)
    mixed.unlink(missing_ok=True)
    if heartbeat is not None:
        heartbeat()
    return final, loudness
