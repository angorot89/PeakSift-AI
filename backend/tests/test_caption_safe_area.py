"""Social-safe positioning: one definition, mapped positions, real renders inside it, and the
same numbers served to the editor preview."""

import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import get_settings
from app.services.clip_edit.caption_metrics import EM_PER_SIZE
from app.services.clip_edit.caption_v2 import (
    PRESETS_V2,
    DynamicPreset,
    build_dynamic_ass,
    rules_for,
)
from app.services.clip_edit.config import OUTPUT_HEIGHT, OUTPUT_WIDTH, CaptionPosition
from app.services.clip_edit.dynamic_cues import SourceWord, build_word_cues
from app.services.clip_edit.hook import HookConfig, HookStyle, hook_ass
from app.services.clip_edit.safe_area import GENERAL_SOCIAL, SAFE_AREA_VERSION, caption_placement
from tests.media_fixtures import requires_ffmpeg, requires_libass

BG = np.array([0x2B, 0x3A, 0x55])


def test_the_general_social_safe_area_is_conservative_and_versioned():
    area = GENERAL_SOCIAL
    assert SAFE_AREA_VERSION == "general_social_v1"
    assert 0.08 <= area.top <= 0.15 and 0.18 <= area.bottom <= 0.3
    assert area.left == area.right and 0.06 <= area.left <= 0.12  # symmetric: captions are centred
    assert area.px() == {"top": 192, "bottom": 422, "left": 97, "right": 97}


def test_positions_map_into_the_safe_area_not_onto_the_edges():
    bottom = caption_placement(CaptionPosition.BOTTOM)
    top = caption_placement(CaptionPosition.TOP)
    center = caption_placement(CaptionPosition.CENTER)
    assert (bottom.alignment, bottom.margin_v) == (2, 422)
    assert (top.alignment, top.margin_v) == (8, 192)
    assert (center.alignment, center.margin_v) == (5, 0)
    assert {p.margin_h for p in (bottom, top, center)} == {97}


def text_rows_and_cols(ass: str, at: float, tmp_path: Path):
    (tmp_path / "c.ass").write_text(ass, encoding="utf-8")
    raw = subprocess.run(
        [
            get_settings().ffmpeg_path, "-v", "error", "-f", "lavfi",
            "-i", f"color=c=0x2B3A55:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:d=3:r=25",
            "-vf", "subtitles=c.ass", "-ss", f"{at:.2f}", "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        capture_output=True, check=True, cwd=tmp_path, timeout=60,
    ).stdout  # fmt: skip
    frame = np.frombuffer(raw, np.uint8).reshape(OUTPUT_HEIGHT, OUTPUT_WIDTH, 3).astype(int)
    ink = np.abs(frame - BG).max(axis=2) > 60
    rows, cols = np.nonzero(ink)
    return rows, cols


@requires_ffmpeg
@requires_libass
@pytest.mark.parametrize("preset", list(DynamicPreset))
@pytest.mark.parametrize("position", list(CaptionPosition))
def test_rendered_two_line_captions_stay_inside_the_safe_area(preset, position, tmp_path):
    placement = caption_placement(position)
    text = "Nobody tells you what the first night in orbit feels like"
    words = [SourceWord(w, 0.1 + 0.2 * i, 0.25 + 0.2 * i) for i, w in enumerate(text.split())]
    cue = build_word_cues(words, clip_duration=3, rules=rules_for(preset, placement.margin_h))[0]
    assert len(cue.line_words()) == 2  # the hardest case: the tallest and widest block
    ass = build_dynamic_ass(
        [cue],
        preset=preset,
        alignment=placement.alignment,
        margin_v=placement.margin_v,
        margin_h=placement.margin_h,
        font_family=get_settings().caption_font_family,
    )
    rows, cols = text_rows_and_cols(ass, cue.end - 0.05, tmp_path)
    px = GENERAL_SOCIAL.px()
    # Vertically the whole drawing stays inside, box padding included (anti-aliasing aside);
    # sideways an outline or box may reach a little past the measured line width.
    slack, side_slack = 6, 24
    assert rows.min() >= px["top"] - slack, (preset, position, rows.min())
    assert rows.max() <= OUTPUT_HEIGHT - px["bottom"] + slack, (preset, position, rows.max())
    assert cols.min() >= px["left"] - side_slack
    assert cols.max() <= OUTPUT_WIDTH - px["right"] + side_slack


@requires_ffmpeg
@requires_libass
@pytest.mark.parametrize("style", list(HookStyle))
def test_a_top_hook_stays_inside_the_safe_area_box_included(style, tmp_path):
    hook = HookConfig.create(
        text="What nobody tells you about seeing Earth from space",
        style=style.value,
        position="top",
        duration=2,
    )
    hook_style, hook_event = hook_ass(hook, font_family=get_settings().caption_font_family)
    ass = build_dynamic_ass(
        [],
        preset=DynamicPreset.FOCUS,
        alignment=2,
        margin_v=422,
        margin_h=97,
        font_family=get_settings().caption_font_family,
        extra_styles=[hook_style],
        extra_events=[hook_event],
    )
    rows, cols = text_rows_and_cols(ass, 1.0, tmp_path)
    px = GENERAL_SOCIAL.px()
    assert rows.min() >= px["top"] - 6, (style, rows.min())
    assert cols.min() >= px["left"] - 24 and cols.max() <= OUTPUT_WIDTH - px["right"] + 24


def test_the_editor_gets_the_renderers_exact_numbers(client):
    from tests.test_clip_edit_api import sign_up

    assert client.get("/caption-styles").status_code == 401
    sign_up(client)
    data = client.get("/caption-styles").json()
    assert data["renderer"] == "caption_v2" and (data["output_width"], data["output_height"]) == (
        1080,
        1920,
    )
    assert data["font"] == {
        "family": get_settings().caption_font_family,
        "em_per_size": EM_PER_SIZE,
    }
    assert data["safe_area"] == {
        "version": SAFE_AREA_VERSION,
        "top": 0.1,
        "bottom": 0.22,
        "left": 0.09,
        "right": 0.09,
    }
    for position in CaptionPosition:
        assert data["positions"][position.value] == vars(caption_placement(position))
    assert [p["name"] for p in data["presets"]] == [p.value for p in DynamicPreset]
    hook = data["hook"]
    assert (hook["max_chars"], hook["max_lines"], hook["default_seconds"]) == (60, 3, 2.0)
    assert [h["name"] for h in hook["styles"]] == ["headline", "boxed", "minimal"]
    assert hook["positions"]["top"] == {"alignment": 8, "margin_v": 192, "margin_h": 97}
    for served in data["presets"]:
        style = PRESETS_V2[DynamicPreset(served["name"])]
        assert served["size"] == style.size and served["active"] == style.active
        assert served["uppercase"] == style.uppercase and served["box"] == style.box
