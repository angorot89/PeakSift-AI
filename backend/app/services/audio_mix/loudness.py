"""Final loudness of a short's audio: measure, then normalize (two-pass ``loudnorm``).

PeakSift's internal social-video mix profile ``social_v1``: integrated loudness -14 LUFS,
true peak at most -1.5 dBTP (EBU R128 measurement as implemented by FFmpeg's ``loudnorm``).
It is PeakSift's own target for shorts — not a promise of how any platform normalizes
playback. The loudness-range target is a permissive 20 LU: speech with natural pauses keeps
its dynamics, because ``loudnorm`` then applies one linear gain instead of compressing.

Every final mix first passes a peak safety limiter at -1 dBFS (it only acts on peaks above
that), so a hot mix — a loud source plus music plus boosted effects — can never clip, and a
single clipping transient cannot dominate the loudness measurement.

1. **Measure** the limited mix: ``loudnorm`` in analysis mode prints a JSON report, which is
   parsed defensively (bounded output, every field checked to be a finite number). A silent
   (or practically silent) mix has no meaningful loudness and is only limited.
2. **Normalize** with the measured values (``linear=true``: one gain for the whole short when
   the true-peak ceiling allows it; FFmpeg falls back to its dynamic mode otherwise), then
   resample to 48 kHz.

With normalization switched off, only the safety limiter is applied.
"""

import json
import logging
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.services.clip_render.renderer import RenderError, RenderOptions

logger = logging.getLogger(__name__)

TARGET_I = -14.0
TARGET_TP = -1.5
TARGET_LRA = 20.0
# Below this the mix is treated as silence: there is nothing to normalize.
SILENCE_LUFS = -70.0
SAFETY_LIMIT = 10 ** (-1 / 20)  # -1 dBFS, linear
LIMITER = f"alimiter=limit={SAFETY_LIMIT:.6f}:level=false:attack=5:release=50"
MAX_REPORT_BYTES = 256 * 1024
SAMPLE_RATE = 48000


@dataclass(frozen=True)
class Loudness:
    integrated: float  # LUFS
    true_peak: float  # dBTP
    lra: float  # LU
    threshold: float  # LUFS
    offset: float  # dB


def _target() -> str:
    return f"I={TARGET_I:g}:TP={TARGET_TP:g}:LRA={TARGET_LRA:g}"


def parse_loudnorm_report(stderr: str) -> Loudness | None:
    """The input measurements from ``loudnorm``'s JSON, or None for silence.

    Raises ``RenderError`` when the report is missing or malformed.
    """
    start, end = stderr.rfind("{"), stderr.rfind("}")
    if start < 0 or end < start:
        raise RenderError("loudness_failed", "The loudness of the mix could not be measured")
    try:
        report = json.loads(stderr[start : end + 1])
    except ValueError:
        raise RenderError(
            "loudness_failed", "The loudness of the mix could not be measured"
        ) from None
    if not isinstance(report, dict):
        raise RenderError("loudness_failed", "The loudness of the mix could not be measured")
    values: dict[str, float] = {}
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        try:
            values[key] = float(report[key])
        except (KeyError, TypeError, ValueError):
            raise RenderError(
                "loudness_failed", "The loudness of the mix could not be measured"
            ) from None
    if not math.isfinite(values["input_i"]) or values["input_i"] < SILENCE_LUFS:
        return None  # silence: -inf (or practically nothing) is not a level to normalize
    if not all(math.isfinite(v) for v in values.values()):
        raise RenderError("loudness_failed", "The loudness of the mix could not be measured")
    return Loudness(
        integrated=values["input_i"],
        true_peak=values["input_tp"],
        lra=values["input_lra"],
        threshold=values["input_thresh"],
        offset=values["target_offset"],
    )


def _run(command: list[str], options: RenderOptions) -> str:
    """Run FFmpeg, returning (bounded) stderr; errors are safe and path-free."""
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=options.timeout_seconds, check=False
        )
    except FileNotFoundError:
        raise RenderError("ffmpeg_missing", "ffmpeg is not installed on the server") from None
    except subprocess.TimeoutExpired:
        raise RenderError("loudness_failed", "Measuring the loudness took too long") from None
    stderr = result.stderr[-MAX_REPORT_BYTES:].decode(errors="replace")
    if result.returncode != 0:
        logger.warning("loudness pass failed (exit %s)", result.returncode)
        raise RenderError("loudness_failed", "The loudness of the mix could not be processed")
    return stderr


def measure_loudness(
    path: Path, options: RenderOptions, *, limited: bool = False
) -> Loudness | None:
    """Integrated loudness, true peak, range and threshold of ``path`` (None = silence).

    ``limited`` measures the audio as it will be after the safety limiter.
    """
    chain = f"{LIMITER}," if limited else ""
    stderr = _run(
        [
            options.ffmpeg_path, "-hide_banner", "-nostats", "-nostdin", "-i", str(path),
            "-af", f"{chain}loudnorm={_target()}:print_format=json", "-f", "null", "-",
        ],
        options,
    )  # fmt: skip
    return parse_loudnorm_report(stderr)


def _n(value: float, low: float, high: float) -> str:
    """A measurement clamped into the range ``loudnorm`` accepts for it.

    Extremely hot material can measure above 0 LUFS (e.g. a loud effect boosted by +6 dB),
    which the filter refuses as ``measured_I``; clamping keeps such mixes renderable, and the
    true-peak ceiling still applies.
    """
    return f"{min(high, max(low, value)):.2f}"


def finish_audio(
    source: Path, target: Path, *, normalize: bool, options: RenderOptions
) -> Loudness | None:
    """Write the final audio (48 kHz stereo float WAV) to ``target``.

    Always peak-limited at -1 dBFS; normalized to ``social_v1`` when asked (silence is not
    normalized). Returns the measurement used for normalization, if any.
    """
    measured = measure_loudness(source, options, limited=True) if normalize else None
    if measured is not None:
        chain = (
            f"{LIMITER},loudnorm={_target()}:measured_I={_n(measured.integrated, -99, 0)}"
            f":measured_TP={_n(measured.true_peak, -99, 99)}"
            f":measured_LRA={_n(measured.lra, 0, 99)}"
            f":measured_thresh={_n(measured.threshold, -99, 0)}"
            f":offset={_n(measured.offset, -99, 99)}"
            f":linear=true,aresample={SAMPLE_RATE}"
        )
    else:  # normalization off, or a silent mix: only the safety limiter
        chain = LIMITER
    target.unlink(missing_ok=True)
    try:
        _run(
            [
                options.ffmpeg_path, "-v", "error", "-nostdin", "-y", "-i", str(source),
                "-af", f"{chain},aformat=sample_fmts=flt:channel_layouts=stereo",
                "-c:a", "pcm_f32le", "-f", "wav", str(target),
            ],
            options,
        )  # fmt: skip
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return measured
