"""Brand colours: one normalized form and the readability rules that decide where a colour may
be used.

Only ``#RGB`` / ``#RRGGBB`` hex is accepted (case-insensitive) and stored as ``#RRGGBB``
uppercase — never CSS names, functions, alpha or anything a browser or FFmpeg would parse.

Readability uses the WCAG 2.1 contrast ratio. A brand colour is used **as text** (the spoken
word in captions) only when it reaches ``TEXT_CONTRAST`` against what surrounds the text in the
chosen preset (its dark outline or box); otherwise PeakSift keeps the preset's own colour for
the text and the brand colour stays an accent (the hook's label box, the end card). Branding
never makes captions unreadable.
"""

import re

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
TEXT_CONTRAST = 4.5  # WCAG AA for normal text


def normalize_color(value: object) -> str:
    """``#RRGGBB`` uppercase, or ValueError."""
    if not isinstance(value, str) or not _HEX.fullmatch(value.strip()):
        raise ValueError("Colours are hex values like #FF3A72")
    digits = value.strip()[1:]
    if len(digits) == 3:
        digits = "".join(d * 2 for d in digits)
    return "#" + digits.upper()


def optional_color(value: object) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return normalize_color(value)


def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    """WCAG relative luminance of a normalized ``#RRGGBB`` colour."""
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio (1–21) between two normalized colours."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on(color: str, background: str, minimum: float = TEXT_CONTRAST) -> bool:
    return contrast(color, background) >= minimum


def text_on(background: str) -> str:
    """The more readable of near-black and white text on ``background``."""
    dark, light = "#111114", "#FFFFFF"
    return dark if contrast(dark, background) >= contrast(light, background) else light


# Every caption preset draws its words on a dark outline or box; the lightest is the Boxed
# preset's box. A brand emphasis colour readable there is readable in every preset.
CAPTION_SURROUND = "#101014"


def emphasis_readable(color: str) -> bool:
    """Whether ``color`` may be used as caption text (the spoken word)."""
    return readable_on(color, CAPTION_SURROUND)
