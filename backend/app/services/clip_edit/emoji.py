"""Emoji in burned-in captions and hooks: shown with a monochrome emoji font, or left out.

libass draws outline glyphs; it cannot draw colour-bitmap emoji fonts (Apple Color Emoji,
Noto Color Emoji), which come out as empty boxes. So PeakSift renders emoji with an installed
*monochrome* open emoji font — ``Noto Emoji`` (OFL; e.g. ``brew install --cask
font-noto-emoji``) or ``Symbola`` (Debian/Ubuntu ``fonts-symbola``). The first candidate that
really renders is chosen by probing libass itself: a probe emoji must render differently from
a code point no font has (which shows the same empty box as an unsupported emoji). Emoji
are then wrapped in ``{\\fn<family>}`` so libass uses that font for them.

When no such font renders, emoji are **left out of the burned-in text** (never drawn as
empty boxes) and ``GET /caption-styles`` reports ``emoji: "omitted"`` so the editor says so.
The stored words always keep their emoji. Monochrome only: no colour emoji is claimed.
ZWJ sequences are drawn with whatever the chosen font supports (a family may appear as its
separate people). Detection is per server process and cached.
"""

import functools
import logging
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

EMOJI_FONT_CANDIDATES = ("Noto Emoji", "Symbola")
PROBE_TIMEOUT_SECONDS = 20
_FONT_NAME = re.compile(r"^[A-Za-z0-9 _-]{1,64}$")

_PICTOGRAPHS = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x2300, 0x23FF))
_SKIN_TONES = (0x1F3FB, 0x1F3FF)
_TAGS = (0xE0020, 0xE007F)
ZWJ, VS16, KEYCAP = "‍", "️", "⃣"


def is_emoji_base(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _PICTOGRAPHS) or ch in "©®‼⁉™"


def _is_modifier(ch: str) -> bool:
    code = ord(ch)
    return (
        ch in (VS16, KEYCAP)
        or _SKIN_TONES[0] <= code <= _SKIN_TONES[1]
        or _TAGS[0] <= code <= _TAGS[1]
    )


_REGIONAL = (0x1F1E6, 0x1F1FF)


def _regional(ch: str) -> bool:
    return _REGIONAL[0] <= ord(ch) <= _REGIONAL[1]


def _emoji_at(text: str, i: int) -> int:
    """Length of the emoji cluster starting at text[i] (0 if none)."""
    ch = text[i]
    if _regional(ch):  # a flag is a pair of regional indicators
        return 2 if i + 1 < len(text) and _regional(text[i + 1]) else 1
    if ch in "0123456789#*" and text[i + 1 : i + 3] == VS16 + KEYCAP:
        return 3  # keycap
    if not is_emoji_base(ch):
        return 0
    j = i + 1
    while j < len(text):
        if _is_modifier(text[j]):
            j += 1
        elif text[j] == ZWJ and j + 1 < len(text) and is_emoji_base(text[j + 1]):
            j += 2
        else:
            break
    return j - i


def split_emoji(text: str) -> list[tuple[str, bool]]:
    """text as (piece, is_emoji) runs; an emoji cluster keeps its skin tone, variation
    selector, keycap, flag pair, tags and ZWJ-joined parts together."""
    runs: list[tuple[str, bool]] = []
    plain = ""
    i = 0
    while i < len(text):
        n = _emoji_at(text, i)
        if n:
            if plain:
                runs.append((plain, False))
                plain = ""
            runs.append((text[i : i + n], True))
            i += n
        else:
            plain += text[i]
            i += 1
    if plain:
        runs.append((plain, False))
    return runs


def has_emoji(text: str) -> bool:
    return any(emoji for _, emoji in split_emoji(text))


def _render(ffmpeg_path: str, text: str, workdir: Path) -> bytes:
    (workdir / "probe.ass").write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 200\nPlayResY: 100\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: P,Noto Sans,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,"
        "1,0,0,5,0,0,0,-1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,0:00:01.00,P,,0,0,0,,{text}\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [
            ffmpeg_path, "-v", "error", "-nostdin", "-f", "lavfi",
            "-i", "color=c=black:s=200x100:d=1:r=1", "-vf", "subtitles=probe.ass",
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-",
        ],
        capture_output=True, check=True, cwd=workdir, timeout=PROBE_TIMEOUT_SECONDS,
    ).stdout  # fmt: skip


@functools.cache
def emoji_font(ffmpeg_path: str) -> str | None:
    """The first candidate family libass really draws emoji with, or None."""
    try:
        with tempfile.TemporaryDirectory(prefix="peaksift-emoji-probe-") as tmp:
            workdir = Path(tmp)
            for family in EMOJI_FONT_CANDIDATES:
                emoji = _render(ffmpeg_path, f"{{\\fn{family}}}\U0001f600\U0001f525", workdir)
                missing = _render(ffmpeg_path, f"{{\\fn{family}}}\U0010fffd\U0010fffd", workdir)
                if any(emoji) and emoji != missing:
                    logger.info("Emoji in captions are drawn with %s", family)
                    return family
    except (OSError, subprocess.SubprocessError):
        logger.warning("Emoji font probe failed; emoji will be left out of burned-in text")
        return None
    logger.warning("No monochrome emoji font renders; emoji will be left out of burned-in text")
    return None


def apply_emoji_policy(escaped: str, family: str | None) -> str:
    """Wrap emoji clusters of already-escaped ASS text in the emoji font, or remove them."""
    if family is not None and not _FONT_NAME.fullmatch(family):
        family = None
    out: list[str] = []
    for piece, emoji in split_emoji(escaped):
        if not emoji:
            out.append(piece)
        elif family is not None:
            out.append(f"{{\\fn{family}}}{piece}{{\\fn}}")
    return re.sub(r" {2,}", " ", "".join(out)).strip()
