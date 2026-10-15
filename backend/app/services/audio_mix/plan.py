"""The FFmpeg plan for a short's audio: inputs and a filtergraph built from validated numbers.

Everything that reaches FFmpeg here is either a constant, an allow-listed preset, a number
formatted by ``_n`` (finite, fixed precision) or a file path the application resolved through
storage. Nothing from a request is interpolated as text.

Timeline (all in the edited short's own time, ``0 … duration``):

- **bed**: silence of exactly the short's duration. Every other part is mixed onto it with
  ``amix=duration=first``, so the mix is never longer or shorter than the video.
- **source**: the clip's own audio, at ``source_gain_db``.
- **music**: the track from ``source_start_seconds``. When it is shorter than the short and
  ``loop`` is on, a second, endlessly looping copy of the track (from its beginning) follows
  the first pass; without ``loop`` the music simply ends. Fades are applied to the music
  that actually plays (clamped so they never exceed it), then the gain.
- **sound effects**: each cue plays its file from the start, at its own gain, delayed to its
  time in the short (whole milliseconds; cue times are on a 10 ms grid). A cue never runs past
  the end of the short (it is trimmed), and a cue at or after the end is left out. Effects
  are not ducked and do not duck the music.
- **ducking**: when the source exists and ducking is on, the source is split and also drives a
  ``sidechaincompress`` on the music (see ``ducking.py``). Without source audio there is
  nothing to duck under, so the music plays as configured.

Working format: 48 kHz stereo float. Mono sources are duplicated to both channels.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path

from app.services.audio_mix.config import MusicConfig, SfxCue
from app.services.audio_mix.ducking import ducking_filter

SAMPLE_RATE = 48000
WORK_FORMAT = f"aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"


def _n(value: float) -> str:
    """A finite number with fixed precision (never exponent notation or NaN)."""
    if not math.isfinite(value):
        raise ValueError("Audio plans only contain finite numbers")
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


@dataclass(frozen=True)
class MusicInput:
    path: Path
    track_seconds: float
    config: MusicConfig


@dataclass(frozen=True)
class SfxInput:
    path: Path
    track_seconds: float
    cue: SfxCue


@dataclass(frozen=True)
class MixPlanRequest:
    duration: float  # the short's duration: authoritative
    source: Path | None  # the clip, when it has an audio stream
    source_gain_db: float = 0.0
    music: MusicInput | None = None
    sfx: tuple[SfxInput, ...] = ()


@dataclass(frozen=True)
class MusicTimeline:
    """Where the music plays in the short, and the fades actually applied."""

    plays_seconds: float  # how long music is heard (≤ duration)
    needs_loop: bool
    fade_in: float
    fade_out: float


def music_timeline(music: MusicInput, duration: float) -> MusicTimeline:
    config = music.config
    remaining = max(0.0, music.track_seconds - config.source_start_seconds)
    needs_loop = config.loop and remaining < duration
    plays = duration if needs_loop else min(duration, remaining)
    fade_in, fade_out = config.fade_in_seconds, config.fade_out_seconds
    if fade_in + fade_out > plays > 0:  # both fit inside the music that actually plays
        scale = plays / (fade_in + fade_out)
        fade_in, fade_out = fade_in * scale, fade_out * scale
    return MusicTimeline(plays, needs_loop, min(fade_in, plays), min(fade_out, plays))


@dataclass
class _Graph:
    inputs: list[list[str]] = field(default_factory=list)
    chains: list[str] = field(default_factory=list)

    def add_input(self, path: Path, *options: str) -> int:
        self.inputs.append([*options, "-i", str(path)])
        return len(self.inputs) - 1


def _ducking(request: MixPlanRequest) -> str | None:
    """The sidechain compressor for the music, when there is music and source to duck under."""
    if request.music is None or request.source is None:
        return None
    if music_timeline(request.music, request.duration).plays_seconds <= 0:
        return None  # no music plays, so there is nothing to duck
    return ducking_filter(request.music.config.ducking)


def _source_chain(graph: _Graph, request: MixPlanRequest) -> str | None:
    if request.source is None:
        return None
    index = graph.add_input(request.source)
    d = _n(request.duration)
    # With ducking the source also becomes the control signal ("key") of the compressor.
    tail = ",asplit=2[source][duck_key]" if _ducking(request) else "[source]"
    graph.chains.append(
        f"[{index}:a:0]{WORK_FORMAT},volume={_n(request.source_gain_db)}dB,"
        f"atrim=duration={d},asetpts=PTS-STARTPTS,apad=whole_dur={d}{tail}"
    )
    return "[source]"


def _music_chain(graph: _Graph, request: MixPlanRequest) -> str | None:
    music = request.music
    if music is None:
        return None
    config = music.config
    timeline = music_timeline(music, request.duration)
    if timeline.plays_seconds <= 0:
        return None
    start = _n(config.source_start_seconds)
    first = graph.add_input(music.path, "-ss", start)
    graph.chains.append(f"[{first}:a:0]{WORK_FORMAT},asetpts=PTS-STARTPTS[music_a]")
    label = "[music_a]"
    if timeline.needs_loop:
        again = graph.add_input(music.path, "-stream_loop", "-1")
        graph.chains.append(f"[{again}:a:0]{WORK_FORMAT},asetpts=PTS-STARTPTS[music_b]")
        graph.chains.append("[music_a][music_b]concat=n=2:v=0:a=1[music_ab]")
        label = "[music_ab]"
    steps = [f"atrim=duration={_n(timeline.plays_seconds)}", "asetpts=PTS-STARTPTS"]
    if timeline.fade_in > 0:
        steps.append(f"afade=t=in:st=0:d={_n(timeline.fade_in)}")
    if timeline.fade_out > 0:
        out_start = timeline.plays_seconds - timeline.fade_out
        steps.append(f"afade=t=out:st={_n(out_start)}:d={_n(timeline.fade_out)}")
    steps.append(f"volume={_n(config.gain_db)}dB")
    ducking = _ducking(request)
    if ducking is None:
        graph.chains.append(f"{label}{','.join(steps)}[music]")
        return "[music]"
    graph.chains.append(f"{label}{','.join(steps)}[music_level]")
    graph.chains.append(f"[music_level][duck_key]{ducking}[music]")
    return "[music]"


def _sfx_chains(graph: _Graph, request: MixPlanRequest) -> list[str]:
    labels: list[str] = []
    for effect in request.sfx:
        at = effect.cue.at_seconds
        plays = min(effect.track_seconds, request.duration - at)
        if at < 0 or plays <= 0:
            continue  # starts at or after the end of the short: nothing of it is heard
        index = graph.add_input(effect.path)
        label = f"[sfx{len(labels)}]"
        graph.chains.append(
            f"[{index}:a:0]{WORK_FORMAT},atrim=duration={_n(plays)},asetpts=PTS-STARTPTS,"
            f"volume={_n(effect.cue.gain_db)}dB,adelay=delays={round(at * 1000)}:all=1{label}"
        )
        labels.append(label)
    return labels


def build_mix_command(ffmpeg_path: str, request: MixPlanRequest, target: Path) -> list[str]:
    """One FFmpeg run that writes the short's mixed audio (48 kHz stereo float WAV)."""
    if not math.isfinite(request.duration) or request.duration <= 0:
        raise ValueError("The short's duration must be positive")
    graph = _Graph()
    parts = [p for p in (_source_chain(graph, request), _music_chain(graph, request)) if p]
    parts += _sfx_chains(graph, request)
    d = _n(request.duration)
    graph.chains.append(f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={d}[bed]")
    graph.chains.append(
        f"[bed]{''.join(parts)}amix=inputs={1 + len(parts)}:duration=first:normalize=0,"
        f"aformat=sample_fmts=flt:channel_layouts=stereo:sample_rates={SAMPLE_RATE}[mix]"
    )
    command = [ffmpeg_path, "-v", "error", "-nostdin", "-y"]
    for options in graph.inputs:
        command += options
    command += [
        "-filter_complex", ";".join(graph.chains), "-map", "[mix]",
        "-c:a", "pcm_f32le", "-f", "wav", str(target),
    ]  # fmt: skip
    return command
