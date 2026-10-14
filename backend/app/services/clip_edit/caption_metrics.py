"""Glyph advance widths for caption line fitting, measured with libass and Noto Sans.

Caption lines are broken by the cue builder, not by libass, so the builder must know how wide
a line will render. These are advance widths of printable ASCII in Noto Sans Regular and Bold,
as fractions of the libass font size, measured by rendering each character with the same
FFmpeg/libass/fontconfig stack that renders shorts (10 vs 20 repetitions, so side bearings
cancel out). Other characters use conservative classes: an accented Latin letter is as wide as
its base letter; Arabic letters, CJK ideographs and emoji use measured class widths with a
margin. Line fitting therefore errs on the side of shorter lines, never on overflow.

Note how libass sizes fonts: the font size is the line height (ascent + descent), so one em
is about 0.73 × the size for Noto Sans — the browser preview accounts for the same ratio.
"""

import unicodedata

ADVANCE_REGULAR: dict[str, float] = {
    " ": 0.171,
    "!": 0.175,
    '"': 0.27,
    "#": 0.421,
    "$": 0.375,
    "%": 0.543,
    "&": 0.484,
    "'": 0.149,
    "(": 0.199,
    ")": 0.199,
    "*": 0.363,
    "+": 0.375,
    ",": 0.175,
    "-": 0.214,
    ".": 0.175,
    "/": 0.246,
    "0": 0.375,
    "1": 0.375,
    "2": 0.375,
    "3": 0.375,
    "4": 0.375,
    "5": 0.375,
    "6": 0.375,
    "7": 0.375,
    "8": 0.375,
    "9": 0.375,
    ":": 0.175,
    ";": 0.175,
    "<": 0.375,
    "=": 0.375,
    ">": 0.375,
    "?": 0.285,
    "@": 0.594,
    "A": 0.421,
    "B": 0.425,
    "C": 0.414,
    "D": 0.477,
    "E": 0.367,
    "F": 0.339,
    "G": 0.477,
    "H": 0.488,
    "I": 0.223,
    "J": 0.18,
    "K": 0.406,
    "L": 0.344,
    "M": 0.594,
    "N": 0.5,
    "O": 0.512,
    "P": 0.399,
    "Q": 0.512,
    "R": 0.406,
    "S": 0.359,
    "T": 0.367,
    "U": 0.481,
    "V": 0.395,
    "W": 0.613,
    "X": 0.387,
    "Y": 0.371,
    "Z": 0.375,
    "[": 0.214,
    "\\": 0.246,
    "]": 0.214,
    "^": 0.375,
    "_": 0.296,
    "`": 0.188,
    "a": 0.371,
    "b": 0.402,
    "c": 0.317,
    "d": 0.406,
    "e": 0.371,
    "f": 0.227,
    "g": 0.402,
    "h": 0.406,
    "i": 0.168,
    "j": 0.168,
    "k": 0.348,
    "l": 0.171,
    "m": 0.613,
    "n": 0.406,
    "o": 0.395,
    "p": 0.402,
    "q": 0.402,
    "r": 0.274,
    "s": 0.317,
    "t": 0.238,
    "u": 0.406,
    "v": 0.336,
    "w": 0.516,
    "x": 0.348,
    "y": 0.336,
    "z": 0.313,
    "{": 0.25,
    "|": 0.359,
    "}": 0.25,
    "~": 0.375,
}

ADVANCE_BOLD: dict[str, float] = {
    " ": 0.172,
    "!": 0.184,
    '"': 0.317,
    "#": 0.429,
    "$": 0.379,
    "%": 0.593,
    "&": 0.492,
    "'": 0.175,
    "(": 0.222,
    ")": 0.222,
    "*": 0.356,
    "+": 0.375,
    ",": 0.188,
    "-": 0.211,
    ".": 0.184,
    "/": 0.274,
    "0": 0.375,
    "1": 0.375,
    "2": 0.375,
    "3": 0.375,
    "4": 0.375,
    "5": 0.375,
    "6": 0.375,
    "7": 0.375,
    "8": 0.375,
    "9": 0.375,
    ":": 0.184,
    ";": 0.192,
    "<": 0.375,
    "=": 0.375,
    ">": 0.375,
    "?": 0.313,
    "@": 0.593,
    "A": 0.457,
    "B": 0.434,
    "C": 0.422,
    "D": 0.481,
    "E": 0.367,
    "F": 0.36,
    "G": 0.477,
    "H": 0.504,
    "I": 0.254,
    "J": 0.218,
    "K": 0.438,
    "L": 0.367,
    "M": 0.621,
    "N": 0.535,
    "O": 0.52,
    "P": 0.406,
    "Q": 0.52,
    "R": 0.429,
    "S": 0.363,
    "T": 0.379,
    "U": 0.496,
    "V": 0.429,
    "W": 0.636,
    "X": 0.442,
    "Y": 0.414,
    "Z": 0.379,
    "[": 0.218,
    "\\": 0.274,
    "]": 0.218,
    "^": 0.375,
    "_": 0.274,
    "`": 0.242,
    "a": 0.395,
    "b": 0.414,
    "c": 0.34,
    "d": 0.414,
    "e": 0.395,
    "f": 0.254,
    "g": 0.414,
    "h": 0.429,
    "i": 0.196,
    "j": 0.199,
    "k": 0.406,
    "l": 0.196,
    "m": 0.64,
    "n": 0.425,
    "o": 0.41,
    "p": 0.414,
    "q": 0.414,
    "r": 0.297,
    "s": 0.332,
    "t": 0.285,
    "u": 0.429,
    "v": 0.375,
    "w": 0.563,
    "x": 0.379,
    "y": 0.375,
    "z": 0.324,
    "{": 0.261,
    "|": 0.36,
    "}": 0.261,
    "~": 0.375,
}

# libass treats the font size as the line height (ascent + descent). For Noto Sans
# (ascent 1069 + descent 293 per 1000 em) one em is 1000 / 1362 of the size; the browser
# preview sets its CSS font size with the same ratio.
EM_PER_SIZE = round(1000 / 1362, 4)

# Measured class averages (regular / bold) with a safety margin; see the module docstring.
ARABIC = 0.38
WIDE = 0.76  # CJK ideographs, kana, fullwidth forms
EMOJI = 0.9  # libass may draw a monochrome or fallback glyph; assume a wide one
OTHER = 0.62


def char_width(ch: str, *, bold: bool) -> float:
    """Advance of one character as a fraction of the font size."""
    table = ADVANCE_BOLD if bold else ADVANCE_REGULAR
    if ch in table:
        return table[ch]
    category = unicodedata.category(ch)
    if category[0] in ("M", "C") or ch in ("\u200d", "\ufe0f"):
        return 0.0  # combining marks, joiners, variation selectors
    base = unicodedata.normalize("NFD", ch)[0]
    if base in table:
        return table[base]
    code = ord(ch)
    if 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0xFB50 <= code <= 0xFEFF:
        return ARABIC
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return EMOJI if code >= 0x1F000 or 0x2600 <= code <= 0x27BF else WIDE
    return OTHER


def text_width(text: str, *, bold: bool, size: float) -> float:
    """Rendered advance width of text in pixels at libass font size size."""
    return sum(char_width(ch, bold=bold) for ch in text) * size
