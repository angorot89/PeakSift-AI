"""The dynamic caption renderer (``caption_v2``): word-aware cues → an ASS document for libass.

``caption_v1`` (``caption_styles.py``) stays unchanged for every edit created before V0.8.

**Active-word emphasis.** Each cue is written as back-to-back ``Dialogue`` events, one per
interval in which a different word is active; every event carries the whole cue, with only
the active word's colour overridden. The layout of all events of a cue is identical, so the
text never moves — only the emphasis does. (ASS karaoke tags such as ``\\k`` fill words
progressively and keep earlier words highlighted, which is not "the word being spoken".)
Phrase-timed cues are one event with no emphasis.

**Entrance.** The first event of a cue fades in and grows from a slightly smaller scale over a
fraction of a second; later events of the same cue have no animation.

**Creator styles** (V2.0, the StreamLadder editor study) add, per preset and only through these
fields: an allow-listed display font (``caption_fonts.py``), one word at a time (single-word
cues), how the spoken word stands out (colour, a coloured marker outline, or an underline), a
short "pop" of the spoken word (it grows by a few percent as it is spoken; lines are fitted with
room for it), "reveal" (words appear as they are spoken; unspoken ones are drawn transparent so
nothing moves) and a soft glow (``\blur``). The four original presets keep exactly their
earlier output.

**Lines.** Line breaks come from the cue builder (``\\N``); libass wrapping is disabled
(``WrapStyle: 2``), so the browser preview and the render break lines identically.

**Text safety.** Everything goes through ``escape_ass_text_v2``: control characters become
spaces, bidi override/isolate controls are dropped, a backslash is followed by a WORD JOINER
(so no ``\\N``/override can form) and braces are escaped. Emoji are kept (glyph availability
is a font question; see ``fonts.py``). Users choose a preset name only — never colours, fonts,
sizes or ASS syntax.
"""

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from app.services.branding.colors import normalize_color
from app.services.clip_edit.caption_fonts import CAPTION_FONTS, font_file, text_width_in
from app.services.clip_edit.caption_metrics import text_width
from app.services.clip_edit.config import (
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    DynamicPreset,
)
from app.services.clip_edit.dynamic_cues import CueRules, WordCue
from app.services.clip_edit.emoji import apply_emoji_policy

WORD_JOINER = "⁠"
_FONT_NAME = re.compile(r"^[A-Za-z0-9 _-]{1,64}$")
_BIDI_CONTROLS = frozenset("‪‫‬‭‮⁦⁧⁨⁩")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class V2Style:
    """A dynamic preset. Colours are ``#RRGGBB``; ``size`` is the libass font size on the
    1080 × 1920 canvas. ``max_line_width`` caps a line in pixels for readability; the safe
    width (frame minus side margins and outline) caps it for layout — the smaller one wins."""

    label: str
    size: int
    bold: bool
    uppercase: bool
    text: str
    active: str
    outline_colour: str
    outline: float
    shadow: float
    box: bool  # an opaque box behind each line (BorderStyle 3) instead of an outline
    box_alpha: int  # 0 opaque … 255 transparent (box only)
    max_line_width: int
    fade_ms: int
    grow_from: int  # entrance scale in percent (100 = no scale animation)
    grow_ms: int
    # Creator styles (V2.0). The defaults are the original behaviour.
    font: str | None = None  # a CAPTION_FONTS key; None = the server's caption font
    one_word: bool = False  # one word at a time
    highlight: str = "colour"  # how the spoken word stands out: colour | marker | underline
    marker: str | None = None  # marker: the outline colour around the spoken word
    marker_outline: float = 0  # marker: its outline width
    pop: int = 100  # the spoken word's scale in percent (100 = none)
    reveal: bool = False  # words appear as they are spoken
    glow: float = 0  # \blur of the outline (0 = crisp)
    scripts: tuple[str, ...] = ("latin", "arabic")  # what the style is made for (display)


PRESETS_V2: dict[DynamicPreset, V2Style] = {
    # Large clean white text with a solid outline; the spoken word turns warm yellow.
    DynamicPreset.FOCUS: V2Style(
        label="Focus",
        size=112,
        bold=True,
        uppercase=False,
        text="#FFFFFF",
        active="#FFD43B",
        outline_colour="#000000",
        outline=7,
        shadow=2,
        box=False,
        box_alpha=0,
        max_line_width=860,
        fade_ms=90,
        grow_from=94,
        grow_ms=140,
    ),
    # Heavier creator style: uppercase, thick outline, the spoken word in vivid green.
    DynamicPreset.PUNCH: V2Style(
        label="Punch",
        size=120,
        bold=True,
        uppercase=True,
        text="#FFFFFF",
        active="#7CFC5A",
        outline_colour="#000000",
        outline=10,
        shadow=3,
        box=False,
        box_alpha=0,
        max_line_width=860,
        fade_ms=80,
        grow_from=90,
        grow_ms=120,
    ),
    # Smaller and restrained: dimmed words, the spoken word in pure white, thin outline.
    DynamicPreset.MINIMAL: V2Style(
        label="Minimal",
        size=78,
        bold=False,
        uppercase=False,
        text="#9DA5B0",
        active="#FFFFFF",
        outline_colour="#000000",
        outline=3,
        shadow=2,
        box=False,
        box_alpha=0,
        max_line_width=760,
        fade_ms=120,
        grow_from=100,
        grow_ms=0,
    ),
    # High contrast: white on a dark box, the spoken word in yellow.
    DynamicPreset.BOXED: V2Style(
        label="Boxed",
        size=100,
        bold=True,
        uppercase=False,
        text="#FFFFFF",
        active="#FFD43B",
        outline_colour="#101014",
        outline=20,
        shadow=0,
        box=True,
        box_alpha=40,
        max_line_width=820,
        fade_ms=90,
        grow_from=96,
        grow_ms=120,
    ),
    # --- Creator styles (V2.0) ---------------------------------------------------------------
    # Condensed and loud: uppercase Anton, the spoken word yellow and popping.
    DynamicPreset.POP: V2Style(
        label="Pop",
        size=132,
        bold=False,
        uppercase=True,
        text="#FFFFFF",
        active="#FFE14D",
        outline_colour="#000000",
        outline=9,
        shadow=3,
        box=False,
        box_alpha=0,
        max_line_width=880,
        fade_ms=80,
        grow_from=92,
        grow_ms=110,
        font="anton",
        pop=116,
        scripts=("latin",),
    ),
    # Comic-book lettering, the spoken word in hot pink.
    DynamicPreset.COMIC: V2Style(
        label="Comic",
        size=138,
        bold=False,
        uppercase=True,
        text="#FFFFFF",
        active="#FF4FA3",
        outline_colour="#000000",
        outline=10,
        shadow=5,
        box=False,
        box_alpha=0,
        max_line_width=880,
        fade_ms=80,
        grow_from=90,
        grow_ms=120,
        font="bangers",
        pop=110,
        scripts=("latin",),
    ),
    # Round sticker letters with a thick violet outline.
    DynamicPreset.BUBBLE: V2Style(
        label="Bubble",
        size=116,
        bold=False,
        uppercase=True,
        text="#FFFFFF",
        active="#FFE14D",
        outline_colour="#5B21B6",
        outline=12,
        shadow=0,
        box=False,
        box_alpha=0,
        max_line_width=860,
        fade_ms=90,
        grow_from=94,
        grow_ms=120,
        font="luckiest_guy",
        scripts=("latin",),
    ),
    # Big single words, one after another.
    DynamicPreset.ONE_WORD: V2Style(
        label="One word",
        size=176,
        bold=False,
        uppercase=True,
        text="#FFFFFF",
        active="#FFFFFF",
        outline_colour="#000000",
        outline=11,
        shadow=4,
        box=False,
        box_alpha=0,
        max_line_width=900,
        fade_ms=40,
        grow_from=88,
        grow_ms=90,
        font="anton",
        one_word=True,
        scripts=("latin",),
    ),
    # White letters with a soft pink glow; the spoken word glows pink.
    DynamicPreset.NEON: V2Style(
        label="Neon",
        size=108,
        bold=False,
        uppercase=False,
        text="#FFFFFF",
        active="#FF7AD9",
        outline_colour="#FF2BB5",
        outline=5,
        shadow=0,
        box=False,
        box_alpha=0,
        max_line_width=840,
        fade_ms=120,
        grow_from=100,
        grow_ms=0,
        font="titan_one",
        glow=6,
        scripts=("latin",),
    ),
    # Clean and bold; the spoken word yellow and underlined.
    DynamicPreset.UNDERLINE: V2Style(
        label="Underline",
        size=104,
        bold=True,
        uppercase=False,
        text="#FFFFFF",
        active="#FFD43B",
        outline_colour="#000000",
        outline=7,
        shadow=2,
        box=False,
        box_alpha=0,
        max_line_width=860,
        fade_ms=90,
        grow_from=96,
        grow_ms=120,
        highlight="underline",
    ),
    # Words appear as they are spoken.
    DynamicPreset.REVEAL: V2Style(
        label="Reveal",
        size=104,
        bold=True,
        uppercase=False,
        text="#FFFFFF",
        active="#FFFFFF",
        outline_colour="#000000",
        outline=7,
        shadow=2,
        box=False,
        box_alpha=0,
        max_line_width=860,
        fade_ms=60,
        grow_from=100,
        grow_ms=0,
        reveal=True,
    ),
    # Tall uppercase headline letters with a soft drop shadow.
    DynamicPreset.HEADLINE: V2Style(
        label="Headline",
        size=150,
        bold=False,
        uppercase=True,
        text="#FFFFFF",
        active="#FF9F1C",
        outline_colour="#000000",
        outline=3,
        shadow=7,
        box=False,
        box_alpha=0,
        max_line_width=880,
        fade_ms=90,
        grow_from=94,
        grow_ms=120,
        font="bebas_neue",
        scripts=("latin",),
    ),
    # The spoken word sits on a thick violet marker stroke.
    DynamicPreset.MARKER: V2Style(
        label="Marker",
        size=104,
        bold=True,
        uppercase=False,
        text="#FFFFFF",
        active="#FFFFFF",
        outline_colour="#000000",
        outline=6,
        shadow=0,
        box=False,
        box_alpha=0,
        max_line_width=820,
        fade_ms=90,
        grow_from=96,
        grow_ms=120,
        highlight="marker",
        marker="#7C3AED",
        marker_outline=16,
    ),
    # Bold display letters drawn for Arabic and Latin alike.
    DynamicPreset.BOLD_ARABIC: V2Style(
        label="Bold Arabic",
        size=118,
        bold=False,
        uppercase=False,
        text="#FFFFFF",
        active="#FFD43B",
        outline_colour="#000000",
        outline=8,
        shadow=2,
        box=False,
        box_alpha=0,
        max_line_width=860,
        fade_ms=90,
        grow_from=94,
        grow_ms=120,
        font="lalezar",
        scripts=("arabic", "latin"),
    ),
}


def ass_colour(rgb: str, alpha: int = 0) -> str:
    """``#RRGGBB`` → ``&HAABBGGRR``."""
    r, g, b = rgb[1:3], rgb[3:5], rgb[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


# Measured display-font widths agree with libass within about 1 %; keep a little room.
FONT_WIDTH_MARGIN = 1.03


class CaptionFontUnavailable(Exception):
    """A preset's font is not installed (or does not match its pinned file) on this server."""


def preset_font_file(preset: DynamicPreset, fonts_dir: str | Path) -> Path | None:
    """The installed file of the preset's display font; None for the server's caption font.
    Raises ``CaptionFontUnavailable`` when the preset needs a font that is not installed."""
    style = PRESETS_V2[preset]
    if style.font is None:
        return None
    path = font_file(style.font, fonts_dir)
    if path is None:
        raise CaptionFontUnavailable(style.font)
    return path


def line_capacity(preset: DynamicPreset, margin_h: int) -> float:
    """Pixels one line may use: the readability cap, or the space between the side margins
    (minus the outline or box padding on both sides) — whichever is smaller. A popping word
    grows, so its line keeps room for it."""
    style = PRESETS_V2[preset]
    outline = max(style.outline, style.marker_outline)
    room = min(style.max_line_width, OUTPUT_WIDTH - 2 * margin_h - 2 * outline)
    return room * 100 / max(100, style.pop) if style.pop > 100 else room


def rules_for(
    preset: DynamicPreset, margin_h: int, fonts_dir: str | Path | None = None
) -> CueRules:
    """Cue rules that fit lines by the real rendered width of this preset's text (in its
    display font when it has one; ``fonts_dir`` is then required)."""
    style = PRESETS_V2[preset]
    path = preset_font_file(preset, fonts_dir) if style.font and fonts_dir is not None else None
    if style.font and path is None:
        raise CaptionFontUnavailable(style.font)

    def measure(text: str) -> float:
        shown = text.upper() if style.uppercase else text
        if path is not None:
            font = CAPTION_FONTS[style.font]
            return text_width_in(shown, font=font, path=path, size=style.size) * FONT_WIDTH_MARGIN
        return text_width(shown, bold=style.bold, size=style.size)

    rules = CueRules(
        line_units=line_capacity(preset, margin_h), measure=measure, space=measure(" ")
    )
    if style.one_word:
        rules = replace(rules, max_words=1, min_words=1, max_lines=1)
    return rules


def escape_ass_text_v2(text: str, *, uppercase: bool = False) -> str:
    out = []
    for ch in text:
        if ch in _BIDI_CONTROLS:
            continue
        category = unicodedata.category(ch)
        if category == "Cc":
            out.append(" ")
        elif category in ("Cs", "Co", "Cn"):
            continue
        else:
            out.append(ch)
    cleaned = _WHITESPACE.sub(" ", "".join(out)).strip()
    if uppercase:
        cleaned = cleaned.upper()
    cleaned = cleaned.replace("\\", "\\" + WORD_JOINER)
    return cleaned.replace("{", "\\{").replace("}", "\\}")


def _centis(seconds: float) -> int:
    return max(0, int(round(seconds * 100)))


def ass_time(seconds: float) -> str:
    centis = _centis(seconds)
    hours, rest = divmod(centis, 360_000)
    minutes, rest = divmod(rest, 6_000)
    secs, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
EVENT_FORMAT = "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"


POP_MS = 90  # the spoken word grows to its pop size over this long


def _spoken(style: V2Style, text: str) -> str:
    """The spoken word with its emphasis (colour, marker or underline, and pop)."""
    on = [f"\\1c{ass_colour(style.active)}"]
    off = [f"\\1c{ass_colour(style.text)}"]
    if style.highlight == "marker" and style.marker:
        on += [f"\\3c{ass_colour(style.marker)}", f"\\bord{style.marker_outline:g}"]
        off += [f"\\3c{ass_colour(style.outline_colour)}", f"\\bord{style.outline:g}"]
    elif style.highlight == "underline":
        on.append("\\u1")
        off.append("\\u0")
    if style.pop > 100:
        on.append(f"\\t(0,{POP_MS},\\fscx{style.pop}\\fscy{style.pop})")
        off.append("\\fscx100\\fscy100")
    return "{" + "".join(on) + "}" + text + "{" + "".join(off) + "}"


def _cue_text(
    cue: WordCue,
    active: int | None,
    style: V2Style,
    emoji_family: str | None,
    at: float | None = None,
) -> str:
    parts: list[str] = []
    hidden_from = None
    if style.reveal and cue.timed and at is not None:
        # Words not yet spoken at ``at`` are drawn fully transparent (the layout stays put).
        hidden_from = next((i for i, w in enumerate(cue.words) if w.start > at + 1e-6), None)
    for line_index, line in enumerate(cue.line_words()):
        if line_index:
            parts.append("\\N")
        offset = cue.lines[line_index]
        drawn = False
        for k, word in enumerate(line):
            index = offset + k
            text = apply_emoji_policy(
                escape_ass_text_v2(word.text, uppercase=style.uppercase), emoji_family
            )
            if not text:
                continue  # an emoji-only word on a server that cannot draw emoji
            if drawn and not word.attached:
                parts.append(" ")
            if hidden_from is not None and index == hidden_from:
                parts.append("{\\alpha&HFF&}")
            if active is not None and index == active:
                parts.append(_spoken(style, text))
            else:
                parts.append(text)
            drawn = True
    return "".join(parts)


def _segments(cue: WordCue) -> list[tuple[float, float, int | None]]:
    """Back-to-back (start, end, active word) intervals covering the whole cue."""
    if not cue.timed:
        return [(cue.start, cue.end, None)]
    bounds = sorted(
        {cue.start, cue.end, *(w.start for w in cue.words), *(w.end for w in cue.words)}
    )
    bounds = [b for b in bounds if cue.start <= b <= cue.end]
    out: list[tuple[float, float, int | None]] = []
    for a, b in zip(bounds, bounds[1:], strict=False):
        if b - a <= 0:
            continue
        active = cue.active_index((a + b) / 2)
        if out and out[-1][2] == active:
            out[-1] = (out[-1][0], b, active)
        else:
            out.append((a, b, active))
    return out


def _entrance(style: V2Style, offset_ms: int) -> str:
    """The cue's entrance (fade in, grow to full size) as seen by an event that starts
    ``offset_ms`` into the cue. Every word event continues it, so a first word shorter than
    the entrance does not cut it off with a pop to full size."""
    tags: list[str] = []
    if offset_ms < style.fade_ms:
        if offset_ms == 0:
            tags.append(f"\\fad({style.fade_ms},0)")
        else:
            left = style.fade_ms - offset_ms
            alpha = round(255 * left / style.fade_ms)
            tags.append(f"\\fade({alpha},0,0,0,{left},{left},{left})")
    if style.grow_from != 100 and offset_ms < style.grow_ms:
        scale = round(style.grow_from + (100 - style.grow_from) * offset_ms / style.grow_ms, 2)
        tags.append(
            f"\\fscx{scale:g}\\fscy{scale:g}\\t(0,{style.grow_ms - offset_ms},\\fscx100\\fscy100)"
        )
    return "{" + "".join(tags) + "}" if tags else ""


def build_dynamic_ass(
    cues: Iterable[WordCue],
    *,
    preset: DynamicPreset,
    alignment: int,
    margin_v: int,
    margin_h: int,
    font_family: str,
    extra_styles: Iterable[str] = (),
    extra_events: Iterable[str] = (),
    emoji_family: str | None = None,
    active_colour: str | None = None,
) -> str:
    # ``font_family`` is the server's caption font; a preset with a display font names that
    # font's family instead (its file is copied next to the captions by the pipeline).
    """The short's ASS document. ``emoji_family`` is the monochrome emoji font libass can
    draw (see ``emoji.py``); None leaves emoji out of the burned-in text. ``active_colour`` is
    a brand's caption emphasis (``#RRGGBB``, already checked for readability) replacing the
    preset's colour for the spoken word only."""
    if not _FONT_NAME.fullmatch(font_family):
        raise ValueError("Unsupported caption font family name")
    style = PRESETS_V2[preset]
    if style.font is not None:
        font_family = CAPTION_FONTS[style.font].family
    if active_colour is not None:
        style = replace(style, active=normalize_color(active_colour))
    if style.box and alignment != 5:  # libass pads the box by the outline: keep it inside too
        margin_v += round(style.outline)
    if style.highlight == "marker" and alignment != 5:
        # The spoken word's marker outline is wider than the text's: keep it inside too.
        margin_v += round(max(0.0, style.marker_outline - style.outline))
    border = 3 if style.box else 1
    back = ass_colour(style.outline_colour, style.box_alpha) if style.box else "&H80000000"
    outline_colour = back if style.box else ass_colour(style.outline_colour)
    text = ass_colour(style.text)
    style_line = (
        f"Style: Dynamic,{font_family},{style.size},{text},{text},"
        f"{outline_colour},{back},{-1 if style.bold else 0},0,0,0,100,100,0,0,{border},"
        f"{style.outline:g},{style.shadow:g},{alignment},{margin_h},{margin_h},{margin_v},-1"
    )
    lines = [
        "[Script Info]",
        "; Generated by PeakSift (caption_v2). Text is escaped; no user markup.",
        "ScriptType: v4.00+",
        f"PlayResX: {OUTPUT_WIDTH}",
        f"PlayResY: {OUTPUT_HEIGHT}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        STYLE_FORMAT,
        style_line,
        *extra_styles,
        "",
        "[Events]",
        EVENT_FORMAT,
    ]
    for cue in cues:
        if not (math.isfinite(cue.start) and math.isfinite(cue.end)) or cue.end <= cue.start:
            continue
        first: int | None = None  # the cue's first drawn event, in centiseconds
        for a, b, active in _segments(cue):
            start, end = ass_time(a), ass_time(b)
            if end <= start:
                continue  # shorter than the subtitle clock: the next event covers it
            if first is None:
                first = _centis(a)
            entrance = _entrance(style, (_centis(a) - first) * 10)
            if style.glow:
                entrance = (entrance[:-1] if entrance else "{") + f"\\blur{style.glow:g}}}"
            body = _cue_text(cue, active, style, emoji_family, a)
            lines.append(f"Dialogue: 0,{start},{end},Dynamic,,0,0,0,,{entrance}{body}")
    lines.extend(extra_events)
    return "\n".join(lines) + "\n"
