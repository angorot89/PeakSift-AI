"""Visual element transitions: none or a short fade (0.1-0.5 s, at most half the element), one
opacity ramp shared by renderer and preview, and the fade filter checked in real FFmpeg — a
cutaway cross-fades from the main picture to the B-roll and back."""

import subprocess
import uuid

import pytest

from app.core.config import get_settings
from app.services.visuals.config import VisualElement, VisualsConfig
from app.services.visuals.transitions import fade_filter, opacity_at
from tests.media_fixtures import requires_ffmpeg

ASSET = str(uuid.uuid4())


def element(**overrides) -> VisualElement:
    data = {"asset_id": ASSET, "mode": "cutaway", "start_seconds": 2.0, "end_seconds": 4.0}
    data.update(overrides)
    return VisualElement.create(data)


def test_no_transition_is_the_default_and_adds_nothing_to_the_snapshot():
    plain = element()
    assert plain.transition == "none" and plain.transition_seconds is None
    assert "transition" not in plain.snapshot() and fade_filter(plain) is None


def test_a_fade_defaults_to_three_tenths_of_a_second_and_is_snapshotted():
    fade = element(transition="fade")
    assert fade.transition_seconds == 0.3
    assert fade.snapshot()["transition"] == "fade" and fade.snapshot()["transition_seconds"] == 0.3
    assert element(transition="fade", transition_seconds=0.456).transition_seconds == 0.46


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"transition": "wipe"}, "Unsupported transition"),
        ({"transition": "fade", "transition_seconds": 0.05}, "between 0.1 and 0.5"),
        ({"transition": "fade", "transition_seconds": 0.6}, "between 0.1 and 0.5"),
        ({"transition": "fade", "transition_seconds": "0.3"}, "must be a number"),
        ({"transition": "fade", "transition_seconds": 0.4, "end_seconds": 2.7}, "half the visual"),
    ],
)
def test_invalid_transitions_are_refused(overrides, message):
    with pytest.raises(ValueError, match=message):
        element(**overrides)


def test_the_fade_length_is_ignored_without_a_fade():
    assert element(transition_seconds=0.4).transition_seconds is None


def test_opacity_ramps_linearly_in_and_out():
    fade = element(transition="fade", transition_seconds=0.4)
    samples = {t: round(opacity_at(fade, t), 3) for t in (1.9, 2.0, 2.1, 2.4, 3.0, 3.8, 3.9, 4.0)}
    assert samples == {1.9: 0, 2.0: 0, 2.1: 0.25, 2.4: 1, 3.0: 1, 3.8: 0.5, 3.9: 0.25, 4.0: 0}
    cut = element()
    assert [opacity_at(cut, t) for t in (1.99, 2.0, 3.99, 4.0)] == [0, 1, 1, 0]


def test_the_fade_filter_uses_formatted_numbers_on_the_short_timeline():
    fade = element(transition="fade", transition_seconds=0.25)
    assert fade_filter(fade) == (
        "fade=t=in:st=2.000:d=0.250:alpha=1,fade=t=out:st=3.750:d=0.250:alpha=1"
    )


def test_transitions_survive_the_edit_snapshot():
    config = VisualsConfig.create(
        {"elements": [{"asset_id": ASSET, "mode": "pip", "start_seconds": 1, "end_seconds": 3,
                       "transition": "fade", "transition_seconds": 0.2}]}
    )  # fmt: skip
    assert VisualsConfig.from_snapshot(config.snapshot()) == config


@requires_ffmpeg
def test_a_faded_cutaway_cross_fades_in_real_ffmpeg(tmp_path):
    """Red main picture, blue B-roll from 0.5 s to 1.5 s with 0.3 s fades: the frames show red,
    a red/blue mix, blue, a mix again, then red."""
    cut = element(start_seconds=0.5, end_seconds=1.5, transition="fade", transition_seconds=0.3)
    fps = 25
    graph = (
        f"[1:v]setpts=PTS-STARTPTS+{cut.start:.3f}/TB,format=yuva420p,{fade_filter(cut)}[layer];"
        f"[0:v][layer]overlay=0:0:enable='between(t,{cut.start:.3f},{cut.end:.3f})'"
        ":eof_action=pass,format=rgb24[out]"
    )
    command = [
        get_settings().ffmpeg_path, "-v", "error", "-nostdin",
        "-f", "lavfi", "-i", f"color=c=red:s=16x16:r={fps}:d=2",
        "-f", "lavfi", "-i", f"color=c=blue:s=16x16:r={fps}:d={cut.duration}",
        "-filter_complex", graph, "-map", "[out]", "-f", "rawvideo", "-",
    ]  # fmt: skip
    raw = subprocess.run(command, capture_output=True, check=True, timeout=60).stdout
    frame_bytes = 16 * 16 * 3
    frames = [raw[i : i + frame_bytes] for i in range(0, len(raw), frame_bytes)]
    assert len(frames) == 2 * fps  # the main picture's duration, unchanged

    def blue_share(t: float) -> float:
        pixel = frames[round(t * fps)][8 * 16 * 3 : 8 * 16 * 3 + 3]  # a centre pixel
        red, _, blue = pixel
        return blue / max(1, red + blue)

    assert blue_share(0.2) < 0.05  # main picture
    assert 0.3 < blue_share(0.64) < 0.7  # fading in
    assert blue_share(1.0) > 0.95  # the B-roll
    assert 0.3 < blue_share(1.36) < 0.7  # fading out
    assert blue_share(1.8) < 0.05  # back to the main picture
