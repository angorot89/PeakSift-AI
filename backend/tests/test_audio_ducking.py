"""Automatic music ducking, rendered with real FFmpeg and measured: the music component dips
while the source is active by each preset's amount, recovers when the source is quiet, does
not flutter between syllables, and never touches the source itself."""

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.audio_mix.config import DuckingStrength, MusicConfig
from app.services.audio_mix.ducking import DUCKING_PRESETS, ducking_filter
from app.services.audio_mix.mixer import render_mix
from app.services.audio_mix.plan import MixPlanRequest, MusicInput, build_mix_command
from app.services.clip_render.pipeline import render_options_from
from tests.audio_fixtures import RATE, amplitude, db, decode, tone
from tests.media_fixtures import requires_ffmpeg

pytestmark = requires_ffmpeg

MUSIC = "0.5*sin(2*PI*200*t)"  # the music proxy: a steady 200 Hz tone
# Speech proxy: 1 kHz at 0.25 (about -12 dBFS) for 2 s, then 2 s of silence, repeated.
SPEECH = "0.25*sin(2*PI*1000*t)*lt(mod(t\\,4)\\,2)"
# The same rhythm broken into syllables (150 ms on, 100 ms off).
SYLLABLES = f"{SPEECH}*lt(mod(t\\,0.25)\\,0.15)"
MUSIC_GAIN = -16.0
UNDUCKED = 0.5 * 10 ** (MUSIC_GAIN / 20)


def render(tmp_path: Path, strength: str, *, source: str | None = SPEECH, name="mix.wav", **music):
    track = tmp_path / "music.wav"
    if not track.exists():
        tone(track, MUSIC, 12)
    src = None
    if source is not None:
        src = tone(tmp_path / f"source-{abs(hash(source))}.wav", source, 12)
    config = MusicConfig(
        asset_id="00000000-0000-0000-0000-000000000001", gain_db=MUSIC_GAIN,
        fade_in_seconds=0, fade_out_seconds=0, ducking=DuckingStrength(strength), **music,
    )  # fmt: skip
    request = MixPlanRequest(12.0, src, music=MusicInput(track, 12.0, config))
    return decode(render_mix(request, tmp_path / name, render_options_from(get_settings())))


def music_level(samples, start, end) -> float:
    """The music component relative to its unducked level, in dB."""
    return db(amplitude(samples, start, end, 200) / UNDUCKED)


@pytest.mark.parametrize(("strength", "least", "most"), [
    ("light", 4, 10), ("medium", 9, 17), ("strong", 14, 24),
])  # fmt: skip
def test_music_dips_while_the_source_is_active_and_recovers(tmp_path, strength, least, most):
    out = render(tmp_path, strength)
    active = [music_level(out, t + 0.4, t + 1.8) for t in (0, 4, 8)]
    recovered = [music_level(out, t + 0.9, t + 1.9) for t in (2, 6, 10)]
    for level in active:
        assert -most <= level <= -least, (strength, active)
    for level in recovered:
        assert level == pytest.approx(0, abs=1), (strength, recovered)
    # The source itself is never compressed: 1 kHz stays at its own level.
    assert amplitude(out, 0.4, 1.8, 1000) == pytest.approx(0.25, abs=0.01)


def test_stronger_presets_duck_more(tmp_path):
    dips = [music_level(render(tmp_path, s, name=f"{s}.wav"), 0.4, 1.8) for s in
            ("light", "medium", "strong")]  # fmt: skip
    assert dips[0] > dips[1] > dips[2]


def test_ducking_off_leaves_the_music_level_alone(tmp_path):
    out = render(tmp_path, "off")
    assert music_level(out, 0.4, 1.8) == pytest.approx(0, abs=0.3)
    assert "sidechaincompress" not in " ".join(
        build_mix_command("ffmpeg", MixPlanRequest(2.0, tmp_path / "s.wav", music=MusicInput(
            tmp_path / "m.wav", 5.0, MusicConfig(asset_id="a", ducking=DuckingStrength.OFF))),
            tmp_path / "o.wav")
    )  # fmt: skip


def test_no_flutter_between_syllables(tmp_path):
    out = render(tmp_path, "strong", source=SYLLABLES)
    # 50 ms windows through 1.4 s of syllabic speech: the ducked music stays steady.
    levels = [music_level(out, 0.4 + i * 0.05, 0.45 + i * 0.05) for i in range(28)]
    assert max(levels) - min(levels) < 2.5, levels
    assert max(levels) < -12  # and it stays ducked between syllables


def test_release_is_smooth_not_a_jump(tmp_path):
    out = render(tmp_path, "medium")
    steps = [music_level(out, 2 + i * 0.1, 2.1 + i * 0.1) for i in range(10)]
    assert steps[0] < -5 and steps[-1] > -1.5  # recovers within a second
    assert all(b >= a - 0.5 for a, b in zip(steps, steps[1:], strict=False))  # rising
    assert max(b - a for a, b in zip(steps, steps[1:], strict=False)) < 6  # no hard jump


def test_without_source_audio_or_with_a_silent_source_nothing_is_ducked(tmp_path):
    no_source = render(tmp_path, "strong", source=None, name="none.wav")
    assert len(no_source) == 12 * RATE
    assert music_level(no_source, 0.4, 1.8) == pytest.approx(0, abs=0.3)
    whisper = render(tmp_path, "strong", source="0.001*sin(2*PI*1000*t)", name="w.wav")
    assert music_level(whisper, 0.4, 1.8) == pytest.approx(0, abs=0.5)


def test_short_music_and_music_that_never_plays_still_render(tmp_path):
    ended = render(tmp_path, "medium", name="ended.wav", loop=False, source_start_seconds=9)
    assert len(ended) == 12 * RATE
    assert amplitude(ended, 4.4, 5.8, 200) < 0.001  # the music ended at 3 s
    assert amplitude(ended, 4.4, 5.8, 1000) == pytest.approx(0.25, abs=0.01)
    never = render(tmp_path, "medium", name="never.wav", loop=False, source_start_seconds=12)
    assert len(never) == 12 * RATE and amplitude(never, 0.4, 1.8, 200) < 0.001


def test_presets_are_constants_only():
    assert set(DUCKING_PRESETS) == {DuckingStrength.LIGHT, DuckingStrength.MEDIUM,
                                    DuckingStrength.STRONG}  # fmt: skip
    assert ducking_filter(DuckingStrength.OFF) is None
    assert ducking_filter(DuckingStrength.MEDIUM).startswith(
        "sidechaincompress=threshold=0.03:ratio=4:attack=20:release=500"
    )
