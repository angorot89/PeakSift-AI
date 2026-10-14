"""The dynamic caption renderer (caption_v2): ASS structure, escaping, presets, line fitting,
and real libass renders checked frame by frame (the active word really moves)."""

import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import get_settings
from app.services.clip_edit.caption_metrics import (
    ADVANCE_BOLD,
    ADVANCE_REGULAR,
    EM_PER_SIZE,
    text_width,
)
from app.services.clip_edit.caption_v2 import (
    PRESETS_V2,
    DynamicPreset,
    ass_colour,
    build_dynamic_ass,
    escape_ass_text_v2,
    line_capacity,
    rules_for,
)
from app.services.clip_edit.config import OUTPUT_HEIGHT, OUTPUT_WIDTH
from app.services.clip_edit.dynamic_cues import SourceWord, WordCue, build_word_cues, phrase_cues
from tests.media_fixtures import requires_ffmpeg, requires_libass

MARGIN_H = 90
ONE_TWO_THREE = [
    SourceWord("ONE", 0.5, 1.0),
    SourceWord("TWO", 1.0, 1.5),
    SourceWord("THREE", 1.5, 2.0),
]


def document(cues, preset=DynamicPreset.FOCUS, **kwargs):
    return build_dynamic_ass(
        cues,
        preset=preset,
        alignment=kwargs.get("alignment", 2),
        margin_v=kwargs.get("margin_v", 400),
        margin_h=MARGIN_H,
        font_family="Noto Sans",
    )


def dialogue_lines(ass: str) -> list[str]:
    return [line for line in ass.splitlines() if line.startswith("Dialogue:")]


def centis(t: str) -> int:
    h, m, s = t.split(":")
    return (int(h) * 3600 + int(m) * 60) * 100 + round(float(s) * 100)


# --- presets and colours -----


def test_there_are_four_complete_presets_with_valid_colours():
    assert {p.value for p in DynamicPreset} == {"focus", "punch", "minimal", "boxed"}
    for preset, style in PRESETS_V2.items():
        for colour in (style.text, style.active, style.outline_colour):
            assert re.fullmatch(r"#[0-9A-F]{6}", colour), (preset, colour)
        assert style.text != style.active  # the spoken word is visibly different
        assert 60 <= style.size <= 130 and 0 < style.max_line_width <= OUTPUT_WIDTH
        assert style.fade_ms <= 150 and style.grow_ms <= 150 and 88 <= style.grow_from <= 100


def test_ass_colour_is_alpha_blue_green_red():
    assert ass_colour("#FFD43B") == "&H003BD4FF"
    assert ass_colour("#101014", 40) == "&H28141010"


# --- escaping -----


def test_text_is_inert_and_preserved():
    hostile = "{\\an8\\c&H0000FF&}hack} \\N new\\h line"
    escaped = escape_ass_text_v2(hostile)
    assert "{" not in escaped.replace("\\{", "") and "}" not in escaped.replace("\\}", "")
    assert "\\N" not in escaped and "\\h" not in escaped and "\\an8" not in escaped
    assert escape_ass_text_v2("C'était\nمرحبا 🔥 naïve") == "C'était مرحبا 🔥 naïve"  # emoji kept
    assert escape_ass_text_v2("a‮b⁦c") == "abc"  # bidi overrides cannot reorder text
    assert escape_ass_text_v2("hello world", uppercase=True) == "HELLO WORLD"


def test_unsupported_font_names_are_refused():
    with pytest.raises(ValueError):
        build_dynamic_ass(
            [],
            preset=DynamicPreset.FOCUS,
            alignment=2,
            margin_v=0,
            margin_h=0,
            font_family="Evil,1,2",
        )


# --- document structure -----


def test_a_timed_cue_becomes_back_to_back_events_with_one_active_word_each():
    cues = build_word_cues(
        ONE_TWO_THREE, clip_duration=5, rules=rules_for(DynamicPreset.FOCUS, MARGIN_H)
    )
    ass = document(cues)
    assert (
        "WrapStyle: 2" in ass
        and f"PlayResX: {OUTPUT_WIDTH}" in ass
        and f"PlayResY: {OUTPUT_HEIGHT}" in ass
    )
    events = dialogue_lines(ass)
    assert len(events) == 3
    highlight = ass_colour(PRESETS_V2[DynamicPreset.FOCUS].active)
    spans = []
    for word, event in zip(["ONE", "TWO", "THREE"], events, strict=True):
        fields = event.split(",", 9)
        spans.append((centis(fields[1]), centis(fields[2])))
        text = fields[9]
        assert all(w in text for w in ("ONE", "TWO", "THREE"))  # the whole cue, always
        assert text.count(f"\\1c{highlight}") == 1 and f"\\1c{highlight}}}{word}" in text
    # The events tile the cue exactly: no gap (flicker) and no overlap.
    assert spans[0][0] == 50 and spans[-1][1] == 225
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:], strict=False))
    # Only the first event animates the entrance.
    assert "\\fad(" in events[0] and "\\t(" in events[0]
    assert all("\\fad(" not in e and "\\t(" not in e for e in events[1:])


def test_phrase_timed_cues_are_one_event_without_word_emphasis():
    cues = phrase_cues([(1.0, 3.0, "I had flown twice")], clip_duration=10)
    events = dialogue_lines(document(cues))
    assert len(events) == 1 and "\\1c" not in events[0]


def test_line_breaks_come_from_the_cue_builder():
    words = [
        SourceWord(w, 0.3 * i, 0.3 * i + 0.25)
        for i, w in enumerate("Nobody tells you what the first night feels".split())
    ]
    cues = build_word_cues(words, clip_duration=10, rules=rules_for(DynamicPreset.FOCUS, MARGIN_H))
    for cue, event in zip(cues, dialogue_lines(document(cues)), strict=False):
        assert event.count("\\N") == len(cue.lines) - 1


@pytest.mark.parametrize("preset", list(DynamicPreset))
def test_every_line_fits_the_preset_width(preset):
    text = (
        "Nobody tells you what the first night in orbit actually feels like, mmmm wwww "
        "MMMM WWWW unbelievably extraordinary moments matter"
    )
    words = [SourceWord(w, 0.3 * i, 0.3 * i + 0.25) for i, w in enumerate(text.split())]
    rules = rules_for(preset, MARGIN_H)
    style = PRESETS_V2[preset]
    for cue in build_word_cues(words, clip_duration=60, rules=rules):
        assert len(cue.line_words()) <= 2
        for line in cue.line_words():
            rendered = " ".join(w.text for w in line)
            rendered = rendered.upper() if style.uppercase else rendered
            assert text_width(rendered, bold=style.bold, size=style.size) <= line_capacity(
                preset, MARGIN_H
            )


# --- real libass renders, checked on frames -----


def render_frames(
    ass: str, times: list[float], tmp_path: Path, rate: int = 25
) -> list[np.ndarray]:
    (tmp_path / "c.ass").write_text(ass, encoding="utf-8")
    frames = []
    for t in times:
        raw = subprocess.run(
            [
                get_settings().ffmpeg_path, "-v", "error", "-f", "lavfi",
                "-i", f"color=c=0x2B3A55:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:d=3:r={rate}",
                "-vf", "subtitles=c.ass", "-ss", f"{t:.2f}", "-frames:v", "1",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ],
            capture_output=True, check=True, cwd=tmp_path, timeout=60,
        ).stdout  # fmt: skip
        frames.append(
            np.frombuffer(raw, np.uint8).reshape(OUTPUT_HEIGHT, OUTPUT_WIDTH, 3).astype(int)
        )
    return frames


def colour_mask(frame: np.ndarray, rgb: str, tolerance: int = 40) -> np.ndarray:
    target = np.array([int(rgb[i : i + 2], 16) for i in (1, 3, 5)])
    return np.abs(frame - target).max(axis=2) <= tolerance


@requires_ffmpeg
@requires_libass
@pytest.mark.parametrize("preset", list(DynamicPreset))
def test_the_active_word_really_moves_on_rendered_frames(preset, tmp_path):
    style = PRESETS_V2[preset]
    cues = build_word_cues(ONE_TWO_THREE, clip_duration=3, rules=rules_for(preset, MARGIN_H))
    ass = document(cues, preset, alignment=5, margin_v=0)
    before, one, two, three, after = render_frames(ass, [0.3, 0.8, 1.3, 1.8, 2.6], tmp_path)
    background = np.array([0x2B, 0x3A, 0x55])
    # Before the cue and after it: no caption at all.
    for frame in (before, after):
        assert (np.abs(frame - background).max(axis=2) > 60).sum() < 50
    centres = []
    for frame in (one, two, three):
        active = colour_mask(frame, style.active)
        inactive = colour_mask(frame, style.text)
        assert active.sum() > 300, preset  # the spoken word is drawn in the active colour
        assert inactive.sum() > 300, preset  # the other words are still visible
        centres.append(np.nonzero(active)[1].mean())
    # ONE, TWO, THREE are left to right: the emphasis follows the speech across the line.
    assert centres[0] + 40 < centres[1] < centres[2] - 40, (preset, centres)
    # The whole cue keeps the same footprint while the emphasis moves (no layout jumps).
    extents = [np.nonzero(np.abs(f - background).max(axis=2) > 60)[1] for f in (two, three)]
    assert (
        abs(extents[0].min() - extents[1].min()) <= 3
        and abs(extents[0].max() - extents[1].max()) <= 3
    )


@requires_ffmpeg
@requires_libass
def test_the_entrance_continues_across_a_short_first_word(tmp_path):
    # The first word is shorter than the entrance (Punch grows over 120 ms): the next event must
    # carry on growing, not pop to full size when the emphasis moves on.
    words = [SourceWord("GO", 0.5, 0.56), *ONE_TWO_THREE[1:]]
    preset = DynamicPreset.PUNCH
    cues = build_word_cues(words, clip_duration=3, rules=rules_for(preset, MARGIN_H))
    ass = document(cues, preset, alignment=5, margin_v=0)
    background = np.array([0x2B, 0x3A, 0x55])
    mid, settled = render_frames(ass, [0.58, 1.3], tmp_path, rate=50)
    widths = [np.ptp(np.nonzero(np.abs(f - background).max(axis=2) > 60)[1]) for f in (mid, settled)]
    # 80 ms into a 90% → 100% grow the cue is ~96.7% wide; a pop would make it 100%.
    assert 0.94 < widths[0] / widths[1] < 0.985, widths


def test_a_cue_whose_first_segment_rounds_away_still_fades_in():
    words = [SourceWord("A", 0.5, 0.502), SourceWord("BEE", 0.502, 1.0)]
    cues = build_word_cues(words, clip_duration=3, rules=rules_for(DynamicPreset.FOCUS, MARGIN_H))
    first = dialogue_lines(document(cues))[0]
    assert "\\fad(" in first or "\\fade(" in first, first


@requires_ffmpeg
@requires_libass
def test_long_lines_render_inside_the_side_margins(tmp_path):
    text = "Nobody tells you what the first night in orbit actually feels like"
    words = [SourceWord(w, 0.1 + 0.15 * i, 0.2 + 0.15 * i) for i, w in enumerate(text.split())]
    for preset in DynamicPreset:
        cue = build_word_cues(words, clip_duration=3, rules=rules_for(preset, MARGIN_H))[0]
        frame = render_frames(
            document([cue], preset, alignment=5, margin_v=0), [cue.end - 0.05], tmp_path
        )[0]
        cols = np.nonzero(np.abs(frame - np.array([0x2B, 0x3A, 0x55])).max(axis=2) > 60)[1]
        assert cols.min() >= MARGIN_H - 30 and cols.max() <= OUTPUT_WIDTH - MARGIN_H + 30, (
            preset,
            cols.min(),
            cols.max(),
        )


def test_preview_em_ratio_agrees_with_the_libass_measurements():
    # Noto Sans advances in font units (per 1000 em): the preview sizes text with EM_PER_SIZE,
    # so it must reproduce what libass measured, or preview lines come out wider than renders.
    for table, units in (
        (ADVANCE_REGULAR, {"0": 572, "H": 741}),
        (ADVANCE_BOLD, {"0": 572, "H": 765}),
    ):
        for char, advance in units.items():
            assert table[char] == pytest.approx(advance / 1000 * EM_PER_SIZE, abs=0.004)


def test_cues_built_for_rendering_are_word_cues():
    assert isinstance(build_word_cues(ONE_TWO_THREE, clip_duration=3)[0], WordCue)
