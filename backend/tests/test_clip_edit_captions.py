import math

import pytest

from app.services.clip_edit.captions import (
    MIN_CUE_SECONDS,
    WORD_JOINER,
    Cue,
    SourceSegment,
    build_cues,
    clean_text,
    escape_ass_text,
)


def seg(start, end, text):
    return SourceSegment(start=start, end=end, text=text)


def cues_for(segments, start, end, **kw):
    return build_cues(segments, clip_start=start, clip_end=end, **kw)


def words(cues):
    return " ".join(c.text for c in cues).split(" ")


# --- selection and clip-local time ---------------------------------------------------------


def test_segments_are_shifted_to_clip_local_time():
    cues = cues_for([seg(124.2, 127.5, "Wait you actually told him")], 120.0, 140.0)
    assert cues == [Cue(start=4.2, end=7.5, text="Wait you actually told him")]


def test_segments_outside_the_clip_are_excluded():
    cues = cues_for(
        [seg(10.0, 12.0, "before"), seg(121.0, 123.0, "inside here"), seg(150.0, 152.0, "after")],
        120.0,
        140.0,
    )
    assert words(cues) == ["inside", "here"]


def test_empty_transcript_range_yields_no_cues():
    assert cues_for([], 0.0, 10.0) == []
    assert cues_for([seg(50.0, 55.0, "far away")], 0.0, 10.0) == []
    assert cues_for([seg(1.0, 3.0, "   \t ")], 0.0, 10.0) == []


def test_clip_starting_mid_segment_keeps_only_the_words_inside():
    # 10 equal-length words over 10 s: words 5..9 are spoken from 15 s on.
    text = "w0 w1 w2 w3 w4 w5 w6 w7 w8 w9"
    cues = cues_for([seg(10.0, 20.0, text)], 15.0, 30.0)
    assert words(cues) == ["w5", "w6", "w7", "w8", "w9"]
    assert cues[0].start == 0.0 and cues[-1].end == pytest.approx(5.0)


def test_clip_ending_mid_segment_keeps_only_the_words_inside():
    text = "w0 w1 w2 w3 w4 w5 w6 w7 w8 w9"
    cues = cues_for([seg(10.0, 20.0, text)], 5.0, 15.0)
    assert words(cues) == ["w0", "w1", "w2", "w3", "w4"]
    assert cues[-1].end <= 10.0  # never beyond the clip duration


@pytest.mark.parametrize("clip", [(0.0, 7.3), (3.0, 9.0), (12.5, 13.6)])
def test_cues_are_inside_the_clip_ordered_and_non_overlapping(clip):
    start, end = clip
    segments = [
        seg(i * 1.7, i * 1.7 + 2.5, f"segment number {i} says several words here")
        for i in range(10)
    ]
    cues = cues_for(segments, start, end)
    previous_end = 0.0
    for cue in cues:
        assert 0.0 <= cue.start < cue.end <= end - start + 1e-9
        assert cue.start >= previous_end - 1e-9
        assert cue.end - cue.start >= MIN_CUE_SECONDS - 1e-9
        previous_end = cue.end


def test_invalid_clip_ranges_are_refused():
    for start, end in ((5.0, 5.0), (6.0, 2.0), (float("nan"), 3.0), (0.0, math.inf)):
        with pytest.raises(ValueError):
            cues_for([seg(0.0, 1.0, "x y")], start, end)


def test_non_finite_or_inverted_segments_are_ignored():
    cues = cues_for(
        [seg(float("nan"), 2.0, "bad"), seg(3.0, 2.0, "bad"), seg(4.0, 6.0, "good words")],
        0.0,
        10.0,
    )
    assert words(cues) == ["good", "words"]


# --- segmentation -----


def test_long_segments_become_short_readable_cues_in_order():
    text = (
        "So I get to the gate and the agent looks at my passport "
        "and says sir this expired three years ago"
    )
    cues = cues_for([seg(0.0, 9.0, text)], 0.0, 9.0)
    assert len(cues) >= 3
    assert all(len(c.text.split(" ")) <= 7 and len(c.text) <= 40 for c in cues)
    assert " ".join(c.text for c in cues) == text  # every word, in order, unchanged


def test_cues_prefer_to_break_after_punctuation():
    cues = cues_for([seg(0.0, 6.0, "Three years. I had flown twice, that same year!")], 0.0, 6.0)
    assert cues[0].text == "Three years."
    assert any(c.text.endswith("twice,") for c in cues)


def test_a_single_trailing_word_is_merged_back():
    cues = cues_for([seg(0.0, 4.0, "one two three four five six seven eight")], 0.0, 4.0)
    assert all(len(c.text.split(" ")) >= 2 for c in cues)


def test_segmentation_is_deterministic():
    segments = [
        seg(i * 3.0, i * 3.0 + 3.0, f"sentence {i}, with a few more words. And more!")
        for i in range(20)
    ]
    assert cues_for(segments, 4.0, 50.0) == cues_for(segments, 4.0, 50.0)


def test_limits_are_configurable():
    cues = cues_for([seg(0.0, 8.0, "a b c d e f g h")], 0.0, 8.0, max_words=2, max_chars=10)
    assert [c.text for c in cues] == ["a b", "c d", "e f", "g h"]


def test_overlapping_transcript_segments_do_not_stack():
    cues = cues_for([seg(0.0, 4.0, "first part here"), seg(3.0, 6.0, "second part here")], 0.0, 6.0)
    assert all(b.start >= a.end for a, b in zip(cues, cues[1:], strict=False))


# --- text: Unicode, punctuation, words unchanged -----


@pytest.mark.parametrize(
    "text",
    [
        "Bonjour à tous, ça va ? C'est l'été !",
        "مرحبا بكم في الفيديو، كيف حالكم؟",
        "Rock & roll — \"quotes\" and 'apostrophes' 🙂",
    ],
)
def test_unicode_and_punctuation_are_preserved_exactly(text):
    cues = cues_for([seg(0.0, 5.0, text)], 0.0, 5.0)
    assert " ".join(c.text for c in cues) == text


def test_clean_text_only_normalises_whitespace_and_control_characters():
    assert clean_text("  Hello\u0000\n  world\t ") == "Hello world"
    assert clean_text("a\nb\r\nc\u0007d") == "a b c d"


def test_clean_text_keeps_joiners_and_marks_but_drops_bidi_overrides():
    family = "\U0001f469\u200d\U0001f467"  # ZWJ emoji sequence
    assert clean_text(f"hi {family}") == f"hi {family}"
    assert clean_text("\u200fمرحبا\u200e ok") == "\u200fمرحبا\u200e ok"
    assert clean_text("abc\u202edcba\u202c") == "abcdcba"  # right-to-left override removed


# --- ASS escaping -----


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain words", "plain words"),
        ("{\\b1}bold{\\b0}", "\\{\\" + WORD_JOINER + "b1\\}bold\\{\\" + WORD_JOINER + "b0\\}"),
        ("line\\Nbreak", "line\\" + WORD_JOINER + "Nbreak"),
        (
            "soft\\nbreak hard\\hspace",
            "soft\\" + WORD_JOINER + "nbreak hard\\" + WORD_JOINER + "hspace",
        ),
        ("real\nnewline", "real newline"),
        ("C:\\new", "C:\\" + WORD_JOINER + "new"),
        ("& < > % ' \" , :", "& < > % ' \" , :"),  # nothing else is special in Dialogue text
        ("مرحبا {x}", "مرحبا \\{x\\}"),
    ],
)
def test_ass_text_escaping(raw, expected):
    assert escape_ass_text(raw) == expected


def test_escaped_text_never_contains_an_active_sequence():
    import re

    hostile = "{\\an8\\fs200\\c&H0000FF&}\\N\\n\\h{\\p1}m 0 0 l 100 0{\\p0}}{"
    out = escape_ass_text(hostile)
    assert not re.search(r"(?<!\\)\{", out)  # every brace is escaped
    assert not re.search(r"\\(?!\u2060|\{|\})", out)  # every backslash is neutralised
