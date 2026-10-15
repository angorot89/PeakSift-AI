"""Timed sound-effect cues, rendered with real FFmpeg and measured: onset times in the
short's own time, gain, stacking, trimming at the end, and combinations with music/source."""

from pathlib import Path

import numpy as np
import pytest

from app.core.config import get_settings
from app.services.audio_mix.config import DuckingStrength, MusicConfig, SfxCue
from app.services.audio_mix.mixer import render_mix
from app.services.audio_mix.plan import MixPlanRequest, MusicInput, SfxInput, build_mix_command
from app.services.clip_render.pipeline import render_options_from
from tests.audio_fixtures import RATE, amplitude, decode, rms_db, tone
from tests.media_fixtures import requires_ffmpeg

pytestmark = requires_ffmpeg

BEEP = "0.5*sin(2*PI*3000*t)"  # the effect proxy: a 3 kHz beep


def beep(tmp_path: Path, seconds: float = 0.3, name: str = "beep.wav") -> Path:
    path = tmp_path / name
    if not path.exists():
        tone(path, BEEP, seconds)
    return path


def cue(path: Path, at: float, gain: float = 0.0, seconds: float = 0.3) -> SfxInput:
    return SfxInput(path, seconds, SfxCue(at_seconds=at, asset_id="a", gain_db=gain))


def render(tmp_path: Path, request: MixPlanRequest, name: str = "mix.wav"):
    return decode(render_mix(request, tmp_path / name, render_options_from(get_settings())))


def onsets(samples: np.ndarray, threshold: float = 0.05) -> list[float]:
    """Times where the signal first rises above ``threshold`` after at least 50 ms of quiet."""
    loud = np.abs(samples) > threshold
    times, quiet_since = [], -RATE  # so a cue at 0.0 s counts as an onset
    for i in np.flatnonzero(loud):
        if i - quiet_since > 0.05 * RATE:
            times.append(i / RATE)
        quiet_since = i
    return times


def test_one_cue_plays_at_its_time_in_the_short(tmp_path):
    out = render(tmp_path, MixPlanRequest(5.0, None, sfx=(cue(beep(tmp_path), 2.0),)))
    assert len(out) == 5 * RATE
    [start] = onsets(out)
    assert start == pytest.approx(2.0, abs=0.002)
    assert amplitude(out, 2.02, 2.28, 3000) == pytest.approx(0.5, abs=0.03)
    assert rms_db(out, 0, 1.9) < -90 and rms_db(out, 2.4, 5) < -90


def test_multiple_cues_including_near_zero_and_the_same_file_twice(tmp_path):
    path = beep(tmp_path)
    request = MixPlanRequest(6.0, None, sfx=(cue(path, 0.0), cue(path, 1.5), cue(path, 4.25)))
    out = render(tmp_path, request)
    assert onsets(out) == pytest.approx([0.0, 1.5, 4.25], abs=0.002)


def test_cues_at_the_same_time_add_up_and_gain_is_in_db(tmp_path):
    path = beep(tmp_path)
    single = render(tmp_path, MixPlanRequest(2.0, None, sfx=(cue(path, 1.0, -6),)), "one.wav")
    double = render(
        tmp_path, MixPlanRequest(2.0, None, sfx=(cue(path, 1.0, -6), cue(path, 1.0, -6))), "two.wav"
    )
    assert amplitude(single, 1.02, 1.28, 3000) == pytest.approx(0.25, abs=0.02)  # 0.5 at -6 dB
    assert amplitude(double, 1.02, 1.28, 3000) == pytest.approx(0.5, abs=0.03)


def test_a_cue_near_the_end_is_trimmed_and_never_lengthens_the_short(tmp_path):
    long = tone(tmp_path / "long.wav", BEEP, 3.0)
    out = render(tmp_path, MixPlanRequest(4.0, None, sfx=(cue(long, 3.6, seconds=3.0),)))
    assert len(out) == 4 * RATE
    assert onsets(out) == pytest.approx([3.6], abs=0.002)
    assert rms_db(out, 3.7, 4.0) > -15  # still playing when the short ends


def test_a_cue_at_or_after_the_end_is_left_out(tmp_path):
    path = beep(tmp_path)
    request = MixPlanRequest(3.0, None, sfx=(cue(path, 3.0), cue(path, 5.0)))
    command = build_mix_command("ffmpeg", request, tmp_path / "o.wav")
    assert command.count("-i") == 0 and "adelay" not in " ".join(command)
    out = render(tmp_path, request)
    assert len(out) == 3 * RATE and rms_db(out, 0, 3) < -90


def test_effects_with_music_and_source_and_without_source(tmp_path):
    music_track = tone(tmp_path / "music.wav", "0.5*sin(2*PI*200*t)", 6)
    source = tone(tmp_path / "speech.wav", "0.25*sin(2*PI*1000*t)", 6)
    music = MusicInput(
        music_track, 6.0,
        MusicConfig(asset_id="m", gain_db=-16, fade_in_seconds=0, fade_out_seconds=0,
                    ducking=DuckingStrength.MEDIUM),
    )  # fmt: skip
    effects = (cue(beep(tmp_path), 1.0), cue(beep(tmp_path), 4.0, -12))
    full = render(tmp_path, MixPlanRequest(6.0, source, music=music, sfx=effects), "full.wav")
    assert amplitude(full, 1.02, 1.28, 3000) == pytest.approx(0.5, abs=0.03)
    assert amplitude(full, 4.02, 4.28, 3000) == pytest.approx(0.125, abs=0.015)
    assert amplitude(full, 2.0, 3.5, 1000) == pytest.approx(0.25, abs=0.01)  # source intact
    # Effects do not drive the ducking: the music is ducked by the source only.
    no_source = render(tmp_path, MixPlanRequest(6.0, None, music=music, sfx=effects), "ns.wav")
    assert amplitude(no_source, 2.0, 3.5, 200) == pytest.approx(0.5 * 10 ** (-16 / 20), abs=0.005)
    assert amplitude(no_source, 1.02, 1.28, 3000) == pytest.approx(0.5, abs=0.03)
