"""Word-aware cue grouping, line layout and active-word timing (pure, deterministic)."""

import pytest

from app.services.clip_edit.dynamic_cues import (
    CueRules,
    SourceWord,
    build_word_cues,
    layout_lines,
    phrase_cues,
    split_token,
    text_units,
)

RULES = CueRules(line_units=18, max_words=7)


def words(*spec):
    """spec: (text, start, end) tuples."""
    return [SourceWord(t, s, e) for t, s, e in spec]


def seq(text, start=0.0, step=0.3, gap=0.05):
    out, t = [], start
    for token in text.split():
        out.append(SourceWord(token, round(t, 3), round(t + step, 3)))
        t += step + gap
    return out


def texts(cue):
    return [w.text for w in cue.words]


def lines(cue):
    return [" ".join(w.text for w in line) for line in cue.line_words()]


# --- grouping -----


def test_sentence_punctuation_closes_cues_and_text_is_preserved():
    cues = build_word_cues(
        seq("I floated by the window. You expect silence, instead it hums."), clip_duration=30
    )
    assert [" ".join(texts(c)) for c in cues] == [
        "I floated by the window.",
        "You expect silence,",
        "instead it hums.",
    ]
    assert all(c.timed for c in cues)


def test_a_clause_end_needs_at_least_two_words():
    cues = build_word_cues(seq("Well, nobody tells you anything"), clip_duration=30)
    assert " ".join(texts(cues[0])).startswith("Well, nobody")


def test_natural_pauses_split_cues():
    ws = words(
        ("first", 0.0, 0.3), ("thought", 0.35, 0.7), ("second", 1.4, 1.7), ("thought", 1.75, 2.1)
    )
    cues = build_word_cues(ws, clip_duration=10)
    assert [texts(c) for c in cues] == [["first", "thought"], ["second", "thought"]]


def test_limits_keep_cues_short():
    cues = build_word_cues(
        seq("one two three four five six seven eight nine ten eleven twelve", step=0.2),
        clip_duration=30,
    )
    assert all(len(c.words) <= 8 for c in cues) and len(cues) >= 2
    slow = build_word_cues(seq("a b c d e", step=1.0, gap=0.0), clip_duration=30)
    assert all(c.words[-1].end - c.start <= RULES.max_duration + 1.2 for c in slow)


def test_no_orphan_single_word_cue_when_it_fits():
    cues = build_word_cues(
        seq("we counted every single breath slowly", step=0.25),
        clip_duration=30,
        rules=CueRules(max_words=6),
    )
    assert all(len(c.words) > 1 for c in cues)


def test_a_single_spoken_word_is_still_a_cue():
    cues = build_word_cues(words(("Wow!", 1.0, 1.3)), clip_duration=5)
    assert len(cues) == 1 and texts(cues[0]) == ["Wow!"]
    assert cues[0].end - cues[0].start >= RULES.min_duration  # extended so it does not flash


def test_zero_words_gives_no_cues_and_bad_input_is_ignored():
    assert build_word_cues([], clip_duration=5) == []
    assert build_word_cues(words(("x", 2.0, 1.0), ("y", float("nan"), 1.0)), clip_duration=5) == []
    with pytest.raises(ValueError):
        build_word_cues([], clip_duration=0)


# --- lines -----


def test_short_cues_are_one_line_and_long_ones_two_balanced_lines():
    one = build_word_cues(seq("Short line here."), clip_duration=10)[0]
    assert one.lines == (0,) and len(lines(one)) == 1
    two = build_word_cues(
        seq("Nobody tells you what the first night feels like."), clip_duration=10
    )
    for cue in two:
        assert len(cue.line_words()) <= 2
        assert all(text_units(line) <= RULES.line_units for line in lines(cue))
    long = [c for c in two if len(c.line_words()) == 2][0]
    a, b = (text_units(line) for line in lines(long))
    assert abs(a - b) <= 8 and len(long.line_words()[1]) > 1  # balanced, no orphan word


def test_layout_prefers_breaking_after_punctuation():
    ws = [
        w
        for c in build_word_cues(
            seq("Breathe slowly, trust your tether"),
            clip_duration=10,
            rules=CueRules(line_units=20, min_words=9),
        )
        for w in c.words
    ]
    assert layout_lines(ws, CueRules(line_units=20)) == (0, 2)


def test_long_tokens_are_split_without_inventing_time_or_breaking_graphemes():
    url = "https://example.com/very/long/path/to/something"
    pieces = split_token(url, 18)
    assert "".join(pieces) == url and all(text_units(p) <= 18 for p in pieces)
    cue = build_word_cues(words((url, 1.0, 2.0)), clip_duration=5)[0]
    assert [w.attached for w in cue.words][0] is False and all(w.attached for w in cue.words[1:])
    # Every piece shares the word's one interval (from its real start); no sub-word times.
    assert len({(w.start, w.end) for w in cue.words}) == 1 and cue.words[0].start == 1.0
    assert "".join(w.text for w in cue.words) == url and len(cue.line_words()) >= 2
    assert (
        split_token("e\u0301" * 20, 18)[1][0] != "\u0301"
    )  # a combining accent stays with its base
    family = "👨\u200d👩\u200d👧"
    assert all(not p.startswith("\u200d") for p in split_token(family * 6, 4))


def test_arabic_and_wide_text_are_measured_sensibly():
    assert text_units("مرحبا") == 5 and text_units("日本語") == 6 and text_units("e\u0301") == 1


# --- active word timing -----


def test_each_word_is_active_until_the_next_one_starts_and_the_last_until_the_cue_ends():
    ws = words(("Nobody", 0.1, 0.4), ("tells", 0.45, 0.8), ("you", 0.85, 1.1))
    cue = build_word_cues(ws, clip_duration=10)[0]
    assert [(w.start, w.end) for w in cue.words] == [(0.1, 0.45), (0.45, 0.85), (0.85, cue.end)]
    assert cue.end == pytest.approx(1.35)  # last word end + hold
    # Exactly one active word at any time inside the cue: no flicker, no overlap.
    for t in [0.1, 0.3, 0.44, 0.45, 0.9, 1.3]:
        assert cue.active_index(t) is not None
    assert cue.active_index(0.05) is None and cue.active_index(cue.end) is None
    assert cue.active_index(0.45) == 1 and cue.active_index(0.4499) == 0


def test_cues_never_overlap_or_leave_the_clip():
    cues = build_word_cues(seq("a b c. d e f. g h i.", step=0.2, gap=0.0), clip_duration=1.7)
    assert all(a.end <= b.start for a, b in zip(cues, cues[1:], strict=False))
    assert cues[-1].end <= 1.7 and cues[0].start >= 0
    for cue in cues:
        assert all(cue.start <= w.start <= w.end <= cue.end for w in cue.words)


def test_words_after_the_clip_end_are_left_out():
    cues = build_word_cues(words(("in", 0.0, 0.4), ("out", 5.2, 5.5)), clip_duration=5)
    assert [texts(c) for c in cues] == [["in"]]


def test_output_is_deterministic():
    ws = seq("Here is the part that surprised me most. Your body forgets which way is down.")
    assert build_word_cues(ws, clip_duration=20) == build_word_cues(list(ws), clip_duration=20)


# --- phrase fallback -----


def test_phrase_cues_have_no_word_timing_and_are_never_highlighted():
    cues = phrase_cues([(1.0, 3.0, "I had flown twice that same")], clip_duration=10)
    assert len(cues) == 1 and cues[0].timed is False
    assert {(w.start, w.end) for w in cues[0].words} == {(1.0, 3.0)}
    assert cues[0].active_index(2.0) is None


def test_phrase_cues_respect_the_line_budget():
    text = "a phrase that is far too long to fit within two short caption lines at all"
    cues = phrase_cues([(0.0, 4.0, text)], clip_duration=10, rules=CueRules(line_units=12))
    assert len(cues) >= 2 and all(layout_lines(c.words, CueRules(line_units=12)) for c in cues)
    assert " ".join(w.text for c in cues for w in c.words) == text
    assert all(a.end <= b.start for a, b in zip(cues, cues[1:], strict=False))
