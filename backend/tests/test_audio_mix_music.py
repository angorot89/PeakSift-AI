"""Background music in the short's mix, rendered with real FFmpeg and measured: start offset,
looping, no-loop ending, fades, gain, source gain, channel handling and exact duration."""

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.audio_mix.config import DuckingStrength, MusicConfig
from app.services.audio_mix.mixer import render_mix
from app.services.audio_mix.plan import (
    MixPlanRequest,
    MusicInput,
    build_mix_command,
    music_timeline,
)
from app.services.clip_render.pipeline import render_options_from
from app.services.clip_render.renderer import RenderError
from tests.audio_fixtures import RATE, amplitude, decode, dominant, rms_db, tone
from tests.media_fixtures import requires_ffmpeg

# Music proxy: 200 Hz for 0-5 s, 400 Hz for 5-10 s, 600 Hz for 10-15 s (frequency = position).
CODED = "0.5*sin(2*PI*(200+200*floor(t/5))*t)"


def music(tmp_path: Path, **config) -> MusicInput:
    path = tmp_path / "music.wav"
    if not path.exists():
        tone(path, CODED, 15)
    # Plain mixing here: ducking (on by default with music over a source) has its own tests.
    defaults = {"asset_id": "00000000-0000-0000-0000-000000000001", "fade_in_seconds": 0,
                "fade_out_seconds": 0, "gain_db": 0, "ducking": DuckingStrength.OFF}  # fmt: skip
    return MusicInput(path, 15.0, MusicConfig(**{**defaults, **config}))


def mix(tmp_path: Path, request: MixPlanRequest, name: str = "mix.wav"):
    out = render_mix(request, tmp_path / name, render_options_from(get_settings()))
    return decode(out)


# --- timeline (pure) ------


def test_music_timeline_covers_offset_loop_and_fades():
    m = MusicInput(Path("m"), 15.0, MusicConfig(asset_id="a", source_start_seconds=12))
    assert music_timeline(m, 8.0).needs_loop and music_timeline(m, 8.0).plays_seconds == 8.0
    no_loop = MusicInput(
        Path("m"), 15.0, MusicConfig(asset_id="a", source_start_seconds=12, loop=False)
    )
    assert music_timeline(no_loop, 8.0).plays_seconds == pytest.approx(3.0)
    long = MusicInput(Path("m"), 180.0, MusicConfig(asset_id="a", source_start_seconds=42))
    assert not music_timeline(long, 25.0).needs_loop  # 42-67 s of the track
    # Fades never exceed the music that plays: 4 s + 4 s over 3 s of music → 1.5 + 1.5.
    short = MusicInput(
        Path("m"), 3.0,
        MusicConfig(asset_id="a", loop=False, fade_in_seconds=4, fade_out_seconds=4),
    )  # fmt: skip
    t = music_timeline(short, 10.0)
    assert (t.plays_seconds, t.fade_in, t.fade_out) == (3.0, 1.5, 1.5)


def test_the_command_contains_only_numbers_constants_and_resolved_paths(tmp_path):
    asset_id = "9f1c2e4a-0000-4000-8000-00000000abcd"
    m = MusicInput(tmp_path / "m.wav", 15.0, MusicConfig(asset_id=asset_id, gain_db=-16.5))
    request = MixPlanRequest(8.0, tmp_path / "c.mp4", -1.5, m)
    command = build_mix_command("ffmpeg", request, tmp_path / "o.wav")
    graph = command[command.index("-filter_complex") + 1]
    assert "volume=-16.5dB" in graph and "volume=-1.5dB" in graph
    assert asset_id not in " ".join(command)  # ids select files; they never reach FFmpeg
    assert str(tmp_path) not in graph  # paths are inputs, never inside the filtergraph
    with pytest.raises(ValueError):
        build_mix_command("ffmpeg", MixPlanRequest(float("nan"), None), tmp_path / "o.wav")


# --- real renders ------


@requires_ffmpeg
def test_music_starts_at_the_chosen_point_of_the_track(tmp_path):
    out = mix(tmp_path, MixPlanRequest(4.0, None, music=music(tmp_path, source_start_seconds=6)))
    assert dominant(out, 0.2, 3.8) == pytest.approx(400, abs=2)  # 6-10 s of the track
    out = mix(
        tmp_path, MixPlanRequest(4.0, None, music=music(tmp_path, source_start_seconds=11)), "b.wav"
    )
    assert dominant(out, 0.2, 3.8) == pytest.approx(600, abs=2)


@requires_ffmpeg
def test_looping_restarts_the_track_and_fills_the_short_exactly(tmp_path):
    out = mix(tmp_path, MixPlanRequest(20.0, None, music=music(tmp_path, source_start_seconds=12)))
    assert len(out) == 20 * RATE
    assert dominant(out, 0.2, 2.8) == pytest.approx(600, abs=2)  # 12-15 s of the track
    assert dominant(out, 3.3, 7.7) == pytest.approx(200, abs=2)  # then from the beginning
    assert dominant(out, 8.3, 12.7) == pytest.approx(400, abs=2)
    assert dominant(out, 18.3, 19.8) == pytest.approx(200, abs=2)  # second loop
    assert rms_db(out, 19.5, 20.0) > -20  # no gap at the end


@requires_ffmpeg
def test_without_loop_the_music_simply_ends(tmp_path):
    m = music(tmp_path, source_start_seconds=12, loop=False)
    out = mix(tmp_path, MixPlanRequest(8.0, None, music=m))
    assert len(out) == 8 * RATE
    assert rms_db(out, 0.5, 2.5) > -15 and rms_db(out, 3.5, 8.0) < -90


@requires_ffmpeg
def test_longer_music_never_lengthens_the_short(tmp_path):
    out = mix(tmp_path, MixPlanRequest(2.5, None, music=music(tmp_path)))
    assert len(out) == int(2.5 * RATE)


@requires_ffmpeg
def test_fades_shape_the_music_that_plays(tmp_path):
    m = music(tmp_path, source_start_seconds=0, fade_in_seconds=1, fade_out_seconds=2)
    out = mix(tmp_path, MixPlanRequest(8.0, None, music=m))
    steady = rms_db(out, 3.0, 4.0)
    assert rms_db(out, 0.0, 0.2) < steady - 12  # still fading in
    assert rms_db(out, 0.5, 0.6) < steady - 3
    assert rms_db(out, 1.2, 1.8) == pytest.approx(steady, abs=1)
    assert rms_db(out, 7.8, 8.0) < steady - 12  # fading out by the end of the short
    # Without looping the fade-out ends where the music ends, not at the end of the short.
    short = music(tmp_path, source_start_seconds=12, loop=False, fade_out_seconds=1)
    out = mix(tmp_path, MixPlanRequest(8.0, None, music=short), "short.wav")
    assert rms_db(out, 2.85, 3.0) < rms_db(out, 1.0, 1.5) - 12


@requires_ffmpeg
def test_music_gain_is_applied_in_db(tmp_path):
    loud = mix(tmp_path, MixPlanRequest(3.0, None, music=music(tmp_path, gain_db=0)), "l.wav")
    quiet = mix(tmp_path, MixPlanRequest(3.0, None, music=music(tmp_path, gain_db=-12)), "q.wav")
    assert rms_db(loud, 1, 2) - rms_db(quiet, 1, 2) == pytest.approx(12, abs=0.3)


@requires_ffmpeg
@pytest.mark.parametrize("mono", [True, False])
def test_source_gain_and_channels(tmp_path, mono):
    source = tone(tmp_path / "speech.wav", "0.4*sin(2*PI*1000*t)", 3, mono=mono)
    plain = mix(tmp_path, MixPlanRequest(3.0, source), "p.wav")
    lower = mix(tmp_path, MixPlanRequest(3.0, source, source_gain_db=-6), "g.wav")
    assert amplitude(plain, 1, 2, 1000) == pytest.approx(0.4, abs=0.02)
    assert rms_db(plain, 1, 2) - rms_db(lower, 1, 2) == pytest.approx(6, abs=0.3)
    stereo = decode(tmp_path / "p.wav", channels=2).reshape(-1, 2)
    assert abs(stereo[:, 0] - stereo[:, 1]).max() < 1e-3 if mono else True  # mono → both sides


@requires_ffmpeg
def test_source_and_music_mix_and_a_silent_short_stays_silent(tmp_path):
    source = tone(tmp_path / "speech.wav", "0.4*sin(2*PI*1000*t)", 4)
    out = mix(tmp_path, MixPlanRequest(4.0, source, music=music(tmp_path, gain_db=-6)))
    assert amplitude(out, 1, 3, 1000) == pytest.approx(0.4, abs=0.02)
    assert amplitude(out, 1, 3, 200) == pytest.approx(0.25, abs=0.02)  # 0.5 at -6 dB
    silent = mix(tmp_path, MixPlanRequest(2.0, None), "silent.wav")
    assert len(silent) == 2 * RATE and rms_db(silent, 0, 2) < -100


@requires_ffmpeg
def test_compressed_music_and_failures_are_safe(tmp_path):
    mp3 = tone(tmp_path / "track.mp3", CODED, 15)
    m = MusicInput(mp3, 15.0, MusicConfig(asset_id="a", source_start_seconds=6, fade_in_seconds=0))
    out = mix(tmp_path, MixPlanRequest(3.0, None, music=m))
    assert dominant(out, 0.3, 2.7) == pytest.approx(400, abs=2)
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"RIFF" + b"\x00" * 64)
    bad = MusicInput(broken, 15.0, MusicConfig(asset_id="a"))
    with pytest.raises(RenderError) as excinfo:
        render_mix(
            MixPlanRequest(2.0, None, music=bad),
            tmp_path / "x.wav",
            render_options_from(get_settings()),
        )
    assert excinfo.value.code == "audio_mix_failed" and str(tmp_path) not in excinfo.value.message
    assert not (tmp_path / "x.wav").exists()
