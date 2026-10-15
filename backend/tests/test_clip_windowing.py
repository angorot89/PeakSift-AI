import uuid

import pytest

from app.services.clip_detection.contract import TranscriptLine
from app.services.clip_detection.windowing import (
    MAX_LINE_CHARS,
    TranscriptError,
    build_windows,
    excerpt,
    normalize_text,
    prepare_lines,
    transcript_fingerprint,
)


def lines(count: int, *, seconds_each: float = 5.0, text: str = "words spoken here") -> list:
    return [
        TranscriptLine(start=i * seconds_each, end=(i + 1) * seconds_each, text=f"{text} {i}")
        for i in range(count)
    ]


def windows_for(items, **overrides):
    options = {"window_seconds": 60, "overlap_seconds": 10, "max_chars": 10_000, "max_windows": 500}
    options.update(overrides)
    return build_windows(tuple(items), **options)


# --- normalisation -----


def test_normalize_strips_control_characters_and_collapses_whitespace():
    assert normalize_text("  hello\u0000 \t world\n\n again \x1b[31m ") == "hello world again [31m"


def test_normalize_keeps_unicode_speech():
    assert normalize_text("مرحبا بكم — ça va? 🙂") == "مرحبا بكم — ça va? 🙂"


def test_normalize_caps_absurdly_long_lines():
    assert len(normalize_text("x" * (MAX_LINE_CHARS + 500))) == MAX_LINE_CHARS


# --- prepare -----


def test_prepare_normalises_and_drops_empty_lines():
    prepared = prepare_lines(
        [
            TranscriptLine(0.0, 2.0, "  Hello   there "),
            TranscriptLine(2.0, 3.0, "   "),  # silence marker
            TranscriptLine(3.0, 5.0, "\u0007Bye"),
        ],
        video_duration=10.0,
        tolerance_seconds=1.0,
    )
    assert prepared == (TranscriptLine(0.0, 2.0, "Hello there"), TranscriptLine(3.0, 5.0, "Bye"))


@pytest.mark.parametrize(
    ("items", "fragment"),
    [
        ([TranscriptLine(-1.0, 2.0, "a")], "starts before 0"),
        ([TranscriptLine(2.0, 2.0, "a")], "ends before it starts"),
        ([TranscriptLine(3.0, 2.0, "a")], "ends before it starts"),
        ([TranscriptLine(5.0, 6.0, "a"), TranscriptLine(1.0, 2.0, "b")], "out of order"),
        ([TranscriptLine(0.0, 12.0, "a")], "ends after the media"),
        ([TranscriptLine(float("nan"), 2.0, "a")], "non-finite"),
        ([TranscriptLine(0.0, float("inf"), "a")], "non-finite"),
    ],
)
def test_prepare_refuses_bad_timelines(items, fragment):
    with pytest.raises(TranscriptError) as info:
        prepare_lines(items, video_duration=10.0, tolerance_seconds=1.0)
    assert info.value.code == "transcript_invalid"
    assert fragment in info.value.message


def test_prepare_normalizes_a_small_overrun_to_the_video_end():
    prepared = prepare_lines(
        [TranscriptLine(0.0, 10.8, "a")], video_duration=10.0, tolerance_seconds=1.0
    )
    assert prepared[0].end == 10.0  # the same media-bounds rule as at transcription


def test_prepare_skips_duration_check_when_duration_unknown():
    assert prepare_lines([TranscriptLine(0.0, 99.0, "a")], video_duration=0, tolerance_seconds=1)


def test_prepare_rejects_an_empty_transcript():
    with pytest.raises(TranscriptError) as info:
        prepare_lines([TranscriptLine(0.0, 1.0, " ")], video_duration=10, tolerance_seconds=1)
    assert info.value.code == "transcript_empty"
    with pytest.raises(TranscriptError):
        prepare_lines([], video_duration=10, tolerance_seconds=1)


# --- fingerprint -----


def test_fingerprint_is_deterministic_and_sensitive():
    transcription_id = uuid.uuid4()
    base = lines(3)
    assert transcript_fingerprint(transcription_id, base) == transcript_fingerprint(
        transcription_id, list(base)
    )
    assert len(transcript_fingerprint(transcription_id, base)) == 64

    changed_text = [*base[:-1], TranscriptLine(base[-1].start, base[-1].end, "different")]
    changed_time = [*base[:-1], TranscriptLine(base[-1].start, base[-1].end + 0.01, base[-1].text)]
    assert transcript_fingerprint(transcription_id, changed_text) != transcript_fingerprint(
        transcription_id, base
    )
    assert transcript_fingerprint(transcription_id, changed_time) != transcript_fingerprint(
        transcription_id, base
    )
    assert transcript_fingerprint(uuid.uuid4(), base) != transcript_fingerprint(
        transcription_id, base
    )
    assert transcript_fingerprint(transcription_id, base[:-1]) != transcript_fingerprint(
        transcription_id, base
    )


# --- windows -----


def test_short_transcript_is_one_window():
    (window,) = windows_for(lines(4))
    assert window.index == 0 and window.start == 0.0 and window.end == 20.0
    assert len(window.lines) == 4


def test_long_transcript_is_split_with_overlap():
    items = lines(40)  # 200 s at 5 s per line
    windows = windows_for(items, window_seconds=60, overlap_seconds=10)

    assert [w.index for w in windows] == list(range(len(windows)))
    assert windows[0].start == 0.0 and windows[0].end == 60.0
    # The next window starts inside the previous one's last 10 seconds.
    assert windows[1].start == 50.0
    assert windows[-1].end == 200.0
    for previous, current in zip(windows, windows[1:], strict=False):
        assert current.start > previous.start
        assert current.start <= previous.end  # overlapping, never a gap
        assert previous.end - current.start <= 10.0


def test_every_line_belongs_to_at_least_one_window():
    items = lines(137, seconds_each=3.7)
    windows = windows_for(items, window_seconds=45, overlap_seconds=7)
    covered = {line for w in windows for line in w.lines}
    assert covered == set(items)
    assert sum(len(w.lines) for w in windows) >= len(items)


def test_char_budget_splits_windows_too():
    items = [TranscriptLine(i, i + 1, "x" * 400) for i in range(10)]  # 10 s, 4000 chars
    windows = windows_for(items, window_seconds=600, overlap_seconds=0, max_chars=1000)
    assert len(windows) == 5  # two 400-char lines per window; a third would exceed 1000
    assert all(w.char_count <= 1000 for w in windows)
    assert all(len(w.lines) == 2 for w in windows)


def test_a_single_oversized_line_still_forms_a_window():
    items = [TranscriptLine(0.0, 300.0, "x" * 1500), TranscriptLine(300.0, 302.0, "short")]
    windows = windows_for(items, window_seconds=60, overlap_seconds=0, max_chars=1000)
    assert len(windows) == 2
    assert windows[0].lines == (items[0],)
    assert windows[1].lines == (items[1],)


def test_final_partial_window_keeps_the_tail():
    items = lines(13)  # 65 s: one full 60 s window + a 5 s tail
    windows = windows_for(items, window_seconds=60, overlap_seconds=0)
    assert len(windows) == 2
    assert windows[1].lines == (items[12],)


def test_overlap_never_prevents_progress():
    items = lines(6, seconds_each=1.0)
    windows = windows_for(items, window_seconds=2, overlap_seconds=1000)  # overlap > window
    assert [w.start for w in windows] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert windows[-1].end == 6.0


def test_too_many_windows_is_refused():
    with pytest.raises(TranscriptError) as info:
        windows_for(lines(50), window_seconds=10, overlap_seconds=0, max_windows=3)
    assert info.value.code == "transcript_too_long"


def test_no_lines_no_windows():
    assert (
        build_windows((), window_seconds=60, overlap_seconds=5, max_chars=100, max_windows=5) == ()
    )


def test_window_options_must_be_positive():
    with pytest.raises(ValueError):
        build_windows(
            tuple(lines(2)), window_seconds=0, overlap_seconds=0, max_chars=1, max_windows=1
        )


def test_windows_are_deterministic():
    items = lines(80, seconds_each=4.2)
    assert windows_for(items, window_seconds=50, overlap_seconds=8) == windows_for(
        items, window_seconds=50, overlap_seconds=8
    )


# --- excerpt -----


def test_excerpt_takes_only_overlapping_lines():
    items = lines(5)  # [0,5) [5,10) [10,15) [15,20) [20,25)
    assert (
        excerpt(items, 6.0, 16.0) == "words spoken here 1 words spoken here 2 words spoken here 3"
    )
    assert excerpt(items, 10.0, 15.0) == "words spoken here 2"
    assert excerpt(items, 30.0, 40.0) == ""
