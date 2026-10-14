"""Multilingual and emoji rendering for dynamic captions and hooks: RTL layout that stays put
while the emphasis moves, mixed scripts, accents, and emoji drawn monochrome or left out."""

import os
from pathlib import Path

import numpy as np
import pytest

from app.core.config import get_settings
from app.services.clip_edit.caption_v2 import DynamicPreset, build_dynamic_ass, rules_for
from app.services.clip_edit.dynamic_cues import SourceWord, build_word_cues
from app.services.clip_edit.emoji import apply_emoji_policy, emoji_font, has_emoji, split_emoji
from app.services.clip_edit.hook import HookConfig, hook_ass
from tests.media_fixtures import requires_ffmpeg, requires_libass
from tests.test_caption_v2 import render_frames

MARGIN_H = 97
BG = np.array([0x2B, 0x3A, 0x55])


def cues_for(text: str, preset=DynamicPreset.FOCUS):
    words = [SourceWord(w, 0.2 + 0.3 * i, 0.45 + 0.3 * i) for i, w in enumerate(text.split())]
    return build_word_cues(words, clip_duration=6, rules=rules_for(preset, MARGIN_H))


def document(cues, emoji_family=None, preset=DynamicPreset.FOCUS):
    return build_dynamic_ass(
        cues,
        preset=preset,
        alignment=5,
        margin_v=0,
        margin_h=MARGIN_H,
        font_family="Noto Sans",
        emoji_family=emoji_family,
    )


def ink(frame: np.ndarray) -> np.ndarray:
    return np.abs(frame - BG).max(axis=2) > 60


# --- emoji clusters and policy -----


@pytest.mark.parametrize(
    ("text", "clusters"),
    [
        ("Wow 😂 done", ["😂"]),
        ("👍🏽 ok", ["👍🏽"]),  # skin tone stays attached
        ("❤️", ["❤️"]),  # variation selector
        ("👨‍👩‍👧 family", ["👨‍👩‍👧"]),  # ZWJ sequence
        ("press 1️⃣ now", ["1️⃣"]),  # keycap
        ("🇲🇦 Maroc", ["🇲🇦"]),  # flag pair
        ("no emoji here, 100%", []),
    ],
)
def test_emoji_clusters_are_never_split(text, clusters):
    assert [piece for piece, emoji in split_emoji(text) if emoji] == clusters
    assert "".join(piece for piece, _ in split_emoji(text)) == text
    assert has_emoji(text) == bool(clusters)


def test_emoji_are_wrapped_in_the_emoji_font_or_left_out():
    assert apply_emoji_policy("so 🔥 good", "Noto Emoji") == "so {\\fnNoto Emoji}🔥{\\fn} good"
    assert apply_emoji_policy("so 🔥 good", None) == "so good"  # no empty box, no double space
    assert apply_emoji_policy("🔥", None) == ""
    assert apply_emoji_policy("so 🔥 good", "Bad,Name") == "so good"  # never an unsafe font name


def test_emoji_only_words_disappear_cleanly_when_they_cannot_be_drawn():
    ass = document(cues_for("Wow 🔥 done"))
    events = [line.split(",", 9)[9] for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert events and all("🔥" not in e and "  " not in e for e in events)
    drawn = document(cues_for("Wow 🔥 done"), emoji_family="Noto Emoji")
    assert "{\\fnNoto Emoji}🔥{\\fn}" in drawn


def test_dynamic_captions_and_hooks_let_libass_detect_text_direction():
    style = next(
        line
        for line in document(cues_for("مرحبا بالعالم")).splitlines()
        if line.startswith("Style: Dynamic,")
    )
    assert style.endswith(",-1")  # Encoding -1: base direction detected per event (RTL for Arabic)
    hook_style, _ = hook_ass(
        HookConfig.create(text="مرحبا", style=None, position=None, duration=None),
        font_family="Noto Sans",
    )
    assert hook_style.endswith(",-1")


# --- real renders -----


@requires_ffmpeg
@requires_libass
def test_an_emoji_font_is_available_where_required():
    family = emoji_font(get_settings().ffmpeg_path)
    if os.environ.get("REQUIRE_LIBASS"):  # CI installs fonts-symbola
        assert family in ("Noto Emoji", "Symbola")
    else:
        assert family in (None, "Noto Emoji", "Symbola")


@requires_ffmpeg
@requires_libass
def test_emoji_render_as_glyphs_or_are_left_out_never_as_empty_boxes(tmp_path: Path):
    family = emoji_font(get_settings().ffmpeg_path)
    with_emoji = cues_for("Hot 🔥 take")
    without = cues_for("Hot take")
    # Each at the end of its own cue (the two cues have different lengths).
    a = ink(render_frames(document(with_emoji, family), [with_emoji[0].end - 0.05], tmp_path)[0])
    b = ink(render_frames(document(without, family), [without[0].end - 0.05], tmp_path)[0])
    if family is None:
        assert (a != b).mean() < 0.0005  # left out: same picture as without the emoji
    else:
        cols_a, cols_b = np.nonzero(a)[1], np.nonzero(b)[1]
        assert cols_a.max() - cols_a.min() > cols_b.max() - cols_b.min() + 40  # a real glyph


@requires_ffmpeg
@requires_libass
def test_arabic_stays_joined_and_in_place_while_the_emphasis_moves(tmp_path: Path):
    cue = cues_for("مرحبا بالعالم الجميل اليوم")[0]
    assert len(cue.words) == 4
    # Sample after the cue's 140 ms entrance (scale-in) has finished.
    first, last = render_frames(
        document([cue]), [cue.words[0].start + 0.2, cue.words[3].start + 0.05], tmp_path
    )
    a, b = ink(first), ink(last)
    # The same words in the same places whichever word is highlighted (colour-blind ink mask).
    # Measured: about 1 % differs (anti-aliasing where yellow meets white); with the old fixed
    # left-to-right base direction (Encoding 1) the words swapped places and 66 % differed.
    assert a.sum() > 2000 and (a != b).sum() / a.sum() < 0.03
    # RTL: the first spoken word is on the right of its line.
    yellow = np.array([0xFF, 0xD4, 0x3B])
    active_first = np.nonzero(np.abs(first - yellow).max(axis=2) < 50)[1].mean()
    assert active_first > 540, active_first


@requires_ffmpeg
@requires_libass
@pytest.mark.parametrize(
    "text",
    [
        "C'était vraiment génial, n'est-ce pas ?",
        "Salam صديقي, this is 100% naïve",
        "Café au lait « vraiment »",  # a combining accent, French quotes
        "“Curly quotes” and 3,5 € — dash",
    ],
)
def test_french_and_mixed_scripts_render_inside_the_frame(tmp_path: Path, text):
    cue = cues_for(text)[0]
    frame = render_frames(
        document([cue], emoji_font(get_settings().ffmpeg_path)), [cue.end - 0.05], tmp_path
    )[0]
    cols = np.nonzero(ink(frame))[1]
    assert len(cols) > 1500 and cols.min() >= MARGIN_H - 30 and cols.max() <= 1080 - MARGIN_H + 30


def test_the_editor_is_told_how_emoji_render(client):
    from tests.test_clip_edit_api import sign_up

    sign_up(client)
    emoji = client.get("/caption-styles").json()["emoji"]
    assert emoji == ("monochrome" if emoji_font(get_settings().ffmpeg_path) else "omitted")
