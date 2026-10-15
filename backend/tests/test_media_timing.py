"""One media-bounds rule for transcript timing (normalize a small overshoot, refuse worse)."""

import math

import pytest

from app.core.config import get_settings
from app.services.clip_detection.contract import TranscriptLine
from app.services.clip_detection.windowing import TranscriptError, prepare_lines
from app.services.media_timing import MediaTimingError, fit_to_media, media_duration

TOL = 1.5


def test_a_small_overshoot_is_normalized_to_the_media_end():
    assert fit_to_media(18.0, 20.08, 20.0, tolerance=TOL) == (18.0, 20.0)
    assert fit_to_media(18.0, 20.0, 20.0, tolerance=TOL) == (18.0, 20.0)
    assert fit_to_media(1.0, 2.0, 20.0, tolerance=TOL) == (1.0, 2.0)
    assert fit_to_media(1.0, 99.0, None, tolerance=TOL) == (1.0, 99.0)  # duration unknown


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (10.0, 83.0, "ends after the media"),  # arbitrarily bad output is never clamped
        (-0.5, 2.0, "starts before 0"),
        (20.5, 21.0, "starts after the media ends"),
        (20.0, 20.4, "starts after the media ends"),
        (5.0, 5.0, "ends before it starts"),
        (6.0, 5.0, "ends before it starts"),
        (math.nan, 5.0, "non-finite"),
        (1.0, math.inf, "non-finite"),
    ],
)
def test_invalid_timing_is_refused(start, end, message):
    with pytest.raises(MediaTimingError) as excinfo:
        fit_to_media(start, end, 20.0, tolerance=TOL)
    assert message in str(excinfo.value)


def test_the_authoritative_duration_is_the_shortest_known_one():
    assert media_duration(20.0, 19.84) == 19.84
    assert media_duration(None, 0, 12.5) == 12.5
    assert media_duration(None, math.nan) is None


def test_the_v09_acceptance_transcript_is_usable_by_clip_detection():
    # Recorded during V0.9 acceptance: a tiny-model final segment ending at 21.0 s on a
    # 19.84 s video made clip detection refuse the whole transcript.
    lines = [
        TranscriptLine(0.0, 4.2, "Here is the first idea"),
        TranscriptLine(16.0, 21.0, "Thanks"),
    ]
    tolerance = get_settings().transcription_timestamp_tolerance_seconds
    prepared = prepare_lines(lines, video_duration=19.84, tolerance_seconds=tolerance)
    assert prepared[-1].end == 19.84
    with pytest.raises(TranscriptError):
        prepare_lines(
            [TranscriptLine(0.0, 83.0, "far too long")], video_duration=20.0,
            tolerance_seconds=tolerance,
        )  # fmt: skip
