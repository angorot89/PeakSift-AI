"""Final-mix loudness: the loudnorm report parser, and real two-pass normalization measured
with FFmpeg — quiet and clipping mixes reach the target, silence stays silence (no NaN),
and with normalization off a peak limiter still prevents clipping."""

import pytest

from app.core.config import get_settings
from app.services.audio_mix.config import DuckingStrength, MusicConfig, SfxCue
from app.services.audio_mix.loudness import (
    TARGET_I,
    TARGET_TP,
    finish_audio,
    measure_loudness,
    parse_loudnorm_report,
)
from app.services.audio_mix.mixer import render_mix
from app.services.audio_mix.plan import MixPlanRequest, MusicInput, SfxInput
from app.services.clip_render.pipeline import render_options_from
from app.services.clip_render.renderer import RenderError
from tests.audio_fixtures import RATE, decode, rms_db, tone
from tests.media_fixtures import requires_ffmpeg

REPORT = """[Parsed_loudnorm_0 @ 0x1]
{
	"input_i" : "-31.35",
	"input_tp" : "-26.11",
	"input_lra" : "2.70",
	"input_thresh" : "-41.35",
	"output_i" : "-14.65",
	"output_tp" : "-9.25",
	"output_lra" : "2.60",
	"output_thresh" : "-24.65",
	"normalization_type" : "dynamic",
	"target_offset" : "0.65"
}
size=N/A time=00:00:12.00"""


def options():
    return render_options_from(get_settings())


def test_the_report_is_parsed_into_finite_measurements():
    loudness = parse_loudnorm_report(REPORT)
    assert (loudness.integrated, loudness.true_peak, loudness.lra) == (-31.35, -26.11, 2.7)
    assert (loudness.threshold, loudness.offset) == (-41.35, 0.65)


def test_silence_is_not_a_level():
    silent = REPORT.replace('"-31.35"', '"-inf"').replace('"-26.11"', '"-inf"')
    assert parse_loudnorm_report(silent.replace('"0.65"', '"inf"')) is None
    assert parse_loudnorm_report(REPORT.replace('"-31.35"', '"-75.00"')) is None


@pytest.mark.parametrize(
    "broken",
    [
        "",
        "no json here",
        REPORT.replace('"input_tp" : "-26.11",', ""),
        REPORT.replace('"-26.11"', '"loud"'),
        REPORT.replace('"-26.11"', '"nan"'),
        REPORT.replace('"0.65"', '"inf"'),
        '{"input_i": [1]}',
        "[1, 2]}",
    ],
)
def test_malformed_reports_are_a_controlled_error(broken):
    with pytest.raises(RenderError) as excinfo:
        parse_loudnorm_report(broken)
    assert excinfo.value.code == "loudness_failed"


@requires_ffmpeg
@pytest.mark.parametrize(
    ("expression", "level"),
    [
        ("0.05*sin(2*PI*1000*t)*lt(mod(t\\,4)\\,2)+0.02*sin(2*PI*200*t)", "quiet"),
        ("0.9*sin(2*PI*1000*t)*lt(mod(t\\,4)\\,2)+0.6*sin(2*PI*200*t)", "clipping"),
    ],
)
def test_quiet_and_clipping_mixes_reach_the_target(tmp_path, expression, level):
    mix = tone(tmp_path / f"{level}.wav", expression, 12, mono=False)
    before = measure_loudness(mix, options(), limited=True)
    out = tmp_path / "final.wav"
    used = finish_audio(mix, out, normalize=True, options=options())
    after = measure_loudness(out, options())
    assert used == before
    assert after.integrated == pytest.approx(TARGET_I, abs=1.0), (level, before, after)
    assert after.true_peak <= TARGET_TP + 0.5, (level, after)
    assert len(decode(out)) == 12 * RATE  # duration untouched


@requires_ffmpeg
def test_silence_stays_silent(tmp_path):
    mix = render_mix(MixPlanRequest(3.0, None), tmp_path / "mix.wav", options())
    out = tmp_path / "final.wav"
    assert finish_audio(mix, out, normalize=True, options=options()) is None
    samples = decode(out)
    assert len(samples) == 3 * RATE and rms_db(samples, 0, 3) < -100


@requires_ffmpeg
def test_normalization_off_only_limits_peaks(tmp_path):
    hot = tone(tmp_path / "hot.wav", "0.9*sin(2*PI*1000*t)+0.6*sin(2*PI*200*t)", 6, mono=False)
    out = tmp_path / "limited.wav"
    assert finish_audio(hot, out, normalize=False, options=options()) is None
    assert measure_loudness(out, options()).true_peak <= -0.9
    calm = tone(tmp_path / "calm.wav", "0.2*sin(2*PI*1000*t)", 6, mono=False)
    finish_audio(calm, out, normalize=False, options=options())
    assert rms_db(decode(out), 1, 5) == pytest.approx(rms_db(decode(calm), 1, 5), abs=0.1)


@requires_ffmpeg
def test_a_full_mix_with_music_and_effects_is_normalized(tmp_path):
    source = tone(tmp_path / "speech.wav", "0.1*sin(2*PI*1000*t)*lt(mod(t\\,3)\\,2)", 9)
    track = tone(tmp_path / "music.wav", "0.5*sin(2*PI*200*t)", 9)
    effect = tone(tmp_path / "hit.wav", "0.8*sin(2*PI*3000*t)", 0.3)
    request = MixPlanRequest(
        9.0, source,
        music=MusicInput(track, 9.0, MusicConfig(asset_id="m", gain_db=-14,
                                                 ducking=DuckingStrength.MEDIUM)),
        sfx=(SfxInput(effect, 0.3, SfxCue(at_seconds=4.0, asset_id="s", gain_db=6)),),
    )  # fmt: skip
    mix = render_mix(request, tmp_path / "mix.wav", options())
    out = tmp_path / "final.wav"
    finish_audio(mix, out, normalize=True, options=options())
    after = measure_loudness(out, options())
    assert after.integrated == pytest.approx(TARGET_I, abs=1.0)
    assert after.true_peak <= TARGET_TP + 0.5


@requires_ffmpeg
def test_unreadable_input_fails_safely(tmp_path):
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"RIFF" + b"\x00" * 32)
    out = tmp_path / "final.wav"
    with pytest.raises(RenderError) as excinfo:
        finish_audio(broken, out, normalize=True, options=options())
    assert excinfo.value.code == "loudness_failed" and str(tmp_path) not in excinfo.value.message
    assert not out.exists()
    with pytest.raises(RenderError):
        finish_audio(broken, out, normalize=False, options=options())
    assert not out.exists()


@requires_ffmpeg
def test_normalization_preserves_dynamics_with_one_linear_gain(tmp_path):
    # Speech-first: a loud and a quiet passage keep their 12 dB difference (no compression).
    mix = tone(
        tmp_path / "dynamic.wav",
        "if(lt(mod(t\\,6)\\,3)\\,0.2\\,0.05)*sin(2*PI*1000*t)", 12, mono=False,
    )  # fmt: skip
    out = tmp_path / "final.wav"
    finish_audio(mix, out, normalize=True, options=options())
    before, after = decode(mix), decode(out)
    for samples in (before, after):
        assert rms_db(samples, 0.5, 2.5) - rms_db(samples, 3.5, 5.5) == pytest.approx(12, abs=0.5)
    assert measure_loudness(out, options()).integrated == pytest.approx(TARGET_I, abs=1.0)
