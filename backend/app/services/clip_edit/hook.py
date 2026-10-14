"""The opening hook: one short line of text over the first seconds of a short.

Not a text-layer editor — exactly one optional overlay. The user picks the text (the editor
suggests the clip candidate's hook or title; no extra model is called), one of three styles,
a safe position and a bounded duration. Everything else is fixed here:

- text is normalized (whitespace collapsed, line breaks become spaces) and limited to
  ``MAX_HOOK_CHARS``; it is laid out on at most ``MAX_HOOK_LINES`` lines by real rendered
  width, and refused when it cannot fit (never shrunk silently or cut off);
- the hook is drawn into the same ASS file as the captions, in output-frame coordinates
  inside the General Social Safe Area, from 0 s to ``duration`` with a short fade in and out,
  so it can never stay over the whole video by accident;
- it goes through ``escape_ass_text_v2`` like captions: braces, backslashes, override tags
  and newlines stay inert text.
"""

import math
from dataclasses import dataclass
from enum import StrEnum

from app.services.clip_edit.caption_metrics import text_width
from app.services.clip_edit.caption_v2 import ass_colour, ass_time, escape_ass_text_v2
from app.services.clip_edit.config import OUTPUT_WIDTH
from app.services.clip_edit.dynamic_cues import CueRules, CueWord, layout_lines
from app.services.clip_edit.emoji import apply_emoji_policy
from app.services.clip_edit.safe_area import GENERAL_SOCIAL, SafeArea

MAX_HOOK_CHARS = 60  # one punchy line of intent; fits three lines in every style
MAX_HOOK_LINES = 3
MIN_HOOK_SECONDS = 0.5
MAX_HOOK_SECONDS = 5.0
DEFAULT_HOOK_SECONDS = 2.0
FADE_IN_MS, FADE_OUT_MS = 150, 200


class HookStyle(StrEnum):
    HEADLINE = "headline"  # big bold white with a heavy outline
    BOXED = "boxed"  # dark text on a bright label box
    MINIMAL = "minimal"  # clean white, thin outline


class HookPosition(StrEnum):
    TOP = "top"
    CENTER = "center"


@dataclass(frozen=True)
class HookLook:
    label: str
    size: int
    bold: bool
    text: str
    outline_colour: str
    outline: float
    shadow: float
    box: bool
    box_alpha: int
    max_line_width: int


HOOK_STYLES: dict[HookStyle, HookLook] = {
    HookStyle.HEADLINE: HookLook("Headline", 96, True, "#FFFFFF", "#000000", 7, 3, False, 0, 860),
    HookStyle.BOXED: HookLook("Boxed", 84, True, "#111114", "#FFD43B", 20, 0, True, 0, 840),
    HookStyle.MINIMAL: HookLook("Minimal", 72, False, "#FFFFFF", "#000000", 3, 2, False, 0, 840),
}


def normalize_hook_text(text: str) -> str:
    """Whitespace (including line breaks) collapsed; the words are kept exactly."""
    return " ".join(str(text).split())


@dataclass(frozen=True)
class HookConfig:
    text: str
    style: HookStyle
    position: HookPosition
    duration: float

    @classmethod
    def create(
        cls, *, text: str | None, style: str | None, position: str | None, duration: float | None
    ) -> "HookConfig":
        clean = normalize_hook_text(text or "")
        if not clean:
            raise ValueError("The hook needs some text")
        if len(clean) > MAX_HOOK_CHARS:
            raise ValueError(f"The hook can be at most {MAX_HOOK_CHARS} characters")
        chosen_style = HookStyle(style) if style else HookStyle.HEADLINE
        chosen_position = HookPosition(position) if position else HookPosition.TOP
        seconds = DEFAULT_HOOK_SECONDS if duration is None else duration
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, int | float)
            or not math.isfinite(seconds)
        ):
            raise ValueError("The hook duration must be a number of seconds")
        if not MIN_HOOK_SECONDS <= seconds <= MAX_HOOK_SECONDS:
            raise ValueError(
                f"The hook shows for {MIN_HOOK_SECONDS:g}–{MAX_HOOK_SECONDS:g} seconds"
            )
        config = cls(clean, chosen_style, chosen_position, round(float(seconds), 1))
        if hook_lines(config) is None:
            raise ValueError("The hook text is too long to fit on screen; shorten it")
        return config

    def snapshot(self) -> dict:
        return {
            "text": self.text,
            "style": self.style.value,
            "position": self.position.value,
            "duration": self.duration,
        }


def _rules(look: HookLook, area: SafeArea) -> CueRules:
    margin = round(max(area.left, area.right) * OUTPUT_WIDTH)
    capacity = min(look.max_line_width, OUTPUT_WIDTH - 2 * margin - 2 * look.outline)

    def measure(text: str) -> float:
        return text_width(text, bold=look.bold, size=look.size)

    return CueRules(line_units=capacity, max_lines=2, measure=measure, space=measure(" "))


def _three_lines(words: list[CueWord], rules: CueRules) -> list[int] | None:
    def width(chunk: list[CueWord]) -> float:
        return sum(rules.measure(w.text) for w in chunk) + rules.space * (len(chunk) - 1)

    best: tuple[float, list[int]] | None = None
    for i in range(1, len(words) - 1):
        for j in range(i + 1, len(words)):
            lines = [words[:i], words[i:j], words[j:]]
            widths = [width(line) for line in lines]
            if max(widths) > rules.line_units:
                continue
            score = max(widths) - min(widths)
            score += sum(rules.line_units for line in lines if len(line) == 1)  # no lone words
            if best is None or score < best[0]:
                best = (score, [0, i, j, len(words)])
    return None if best is None else best[1]


def hook_lines(config: HookConfig, area: SafeArea = GENERAL_SOCIAL) -> list[str] | None:
    """The hook's lines (balanced, up to ``MAX_HOOK_LINES``), or None if it cannot fit."""
    look = HOOK_STYLES[config.style]
    rules = _rules(look, area)
    words = [CueWord(w, 0.0, 1.0) for w in config.text.split(" ")]
    if any(rules.measure(w.text) > rules.line_units for w in words):
        return None  # one word wider than the line: refuse rather than cut a word
    two = layout_lines(words, rules)
    if two is not None:
        bounds = [*two, len(words)]
    else:  # three balanced lines: every pair of breaks, the most even one that fits
        bounds = _three_lines(words, rules)
        if bounds is None:
            return None
    return [" ".join(w.text for w in words[a:b]) for a, b in zip(bounds, bounds[1:], strict=False)]


def hook_ass(
    config: HookConfig,
    *,
    font_family: str,
    emoji_family: str | None = None,
    area: SafeArea = GENERAL_SOCIAL,
) -> tuple[str, str]:
    """(Style line, Dialogue line) for the hook, to add to a short's ASS document."""
    look = HOOK_STYLES[config.style]
    lines = hook_lines(config, area)
    if lines is None:  # create() refuses this; a stored snapshot is re-checked here
        raise ValueError("The hook text does not fit")
    px = area.px()
    margin_h = max(px["left"], px["right"])
    alignment, margin_v = (8, px["top"]) if config.position == HookPosition.TOP else (5, 0)
    border = 3 if look.box else 1
    outline = ass_colour(look.outline_colour, look.box_alpha)
    back = outline if look.box else "&H80000000"
    text = ass_colour(look.text)
    style = (
        f"Style: Hook,{font_family},{look.size},{text},{text},{outline},{back},"
        f"{-1 if look.bold else 0},0,0,0,100,100,0,0,{border},{look.outline:g},{look.shadow:g},"
        f"{alignment},{margin_h},{margin_h},{margin_v},-1"
    )
    drawn = (apply_emoji_policy(escape_ass_text_v2(line), emoji_family) for line in lines)
    body = "\\N".join(line for line in drawn if line)
    event = (
        f"Dialogue: 1,{ass_time(0)},{ass_time(config.duration)},Hook,,0,0,0,,"
        f"{{\\fad({FADE_IN_MS},{FADE_OUT_MS})}}{body}"
    )
    return style, event
