"""The open-licence display fonts creator caption styles may use, and measuring text in them.

Fonts are an allow-list: a preset names a key here, never a family, file or path. Each font is
pinned to one file of the google/fonts repository (commit and sha256), installed by an operator
with ``scripts/fetch_caption_fonts.py`` into ``CAPTION_FONTS_DIR`` and never committed. A font
is used only when its installed file matches the pinned digest; a render copies it into the
attempt workspace and libass finds it there (``fontsdir``), so fontconfig never has to know it.

Licences (all allow bundling and commercial use; burned-in text carries no obligation):
SIL Open Font License 1.1 (Anton, Bangers, Bebas Neue, Titan One, Lalezar) and Apache 2.0
(Luckiest Guy). The licence files are installed next to the fonts.

Line fitting needs the rendered width of text. libass sizes a font by its OS/2 Windows line
height (``usWinAscent + usWinDescent``), so one em is ``unitsPerEm / (winAscent + winDescent)``
of the font size; widths are measured with FreeType (Pillow) at that em. Characters a font does
not cover are drawn by a fallback font (Noto Sans, Noto Sans Arabic), so they are measured with
the Noto tables of ``caption_metrics`` — conservative, never narrower than the real line.
"""

import hashlib
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.clip_edit.caption_metrics import char_width

GOOGLE_FONTS_COMMIT = "5026800714d07231937d92eb4cceabf06e05d74e"
GOOGLE_FONTS_RAW = f"https://raw.githubusercontent.com/google/fonts/{GOOGLE_FONTS_COMMIT}/"
WORKSPACE_FONTS_DIR = "fonts"  # a fixed relative name inside the attempt workspace

LATIN = ((0x20, 0x24F),)  # Basic Latin, Latin-1 Supplement, Latin Extended-A/B
ARABIC = ((0x600, 0x6FF), (0x750, 0x77F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))


@dataclass(frozen=True)
class CaptionFont:
    key: str
    family: str  # the family name inside the file (what the ASS style names)
    repo_path: str
    sha256: str
    licence: str
    licence_path: str
    licence_sha256: str
    scripts: tuple[str, ...]

    @property
    def file_name(self) -> str:
        return self.repo_path.rsplit("/", 1)[1]

    @property
    def licence_name(self) -> str:
        return f"{self.key}-{self.licence_path.rsplit('/', 1)[1]}"

    def covers(self, ch: str) -> bool:
        code = ord(ch)
        ranges = LATIN + (ARABIC if "arabic" in self.scripts else ())
        return any(lo <= code <= hi for lo, hi in ranges)


CAPTION_FONTS: dict[str, CaptionFont] = {
    font.key: font
    for font in (
        CaptionFont(
            "anton", "Anton", "ofl/anton/Anton-Regular.ttf",
            "a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab",
            "OFL-1.1", "ofl/anton/OFL.txt",
            "ee67e6ee22790b7929f1a3769ca2801d565c64b5a9096942c1adf5596de9c9e4", ("latin",),
        ),
        CaptionFont(
            "bangers", "Bangers", "ofl/bangers/Bangers-Regular.ttf",
            "4160a7311de9342674cce9160cde9fcbb30f48190397d86ff1b70b455af65824",
            "OFL-1.1", "ofl/bangers/OFL.txt",
            "630dd5a307c0657b094d324e069b390edf90182fe5003639e06c02a0e5769af7", ("latin",),
        ),
        CaptionFont(
            "bebas_neue", "Bebas Neue", "ofl/bebasneue/BebasNeue-Regular.ttf",
            "08e4623805102d819f58601e46e345648846075e363b2ceb23313c2d1c83ec73",
            "OFL-1.1", "ofl/bebasneue/OFL.txt",
            "72082f6cb4d04be2ecf7cc7d9e1e7d73787f0af8a5a278a47cade70c16b78341", ("latin",),
        ),
        CaptionFont(
            "titan_one", "Titan One", "ofl/titanone/TitanOne-Regular.ttf",
            "563ff6de179bbd44bcd7d2a6c448d6dc3bf935834237cf1250e506e65cd86ff1",
            "OFL-1.1", "ofl/titanone/OFL.txt",
            "61be7c29f4835e2be7243db12213d75d53ff028f29f4b493212a1688b1d3a1ba", ("latin",),
        ),
        CaptionFont(
            "luckiest_guy", "Luckiest Guy", "apache/luckiestguy/LuckiestGuy-Regular.ttf",
            "cfbdd68a039f92df51cf3721506af6242e64594c6325fe0bedbeff3fe385d980",
            "Apache-2.0", "apache/luckiestguy/LICENSE.txt",
            "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30", ("latin",),
        ),
        CaptionFont(
            "lalezar", "Lalezar", "ofl/lalezar/Lalezar-Regular.ttf",
            "7b80807bc831f141de0f7dcf6816412bf0c548968d548c5156ca388733390ea9",
            "OFL-1.1", "ofl/lalezar/OFL.txt",
            "327bac41d89cf9f32e0efe353228018e1661cff458a5d4905714958514df7bd5",
            ("arabic", "latin"),
        ),
    )
}  # fmt: skip


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=64)
def _verified(path: str, size: int, mtime: float, sha256: str) -> bool:
    return _digest(Path(path)) == sha256  # checked once per file version


def font_file(key: str, fonts_dir: str | Path) -> Path | None:
    """The installed, verified file of an allow-listed font; None when it is missing or
    differs from the pinned file (it is then never used)."""
    font = CAPTION_FONTS.get(key)
    if font is None:
        return None
    path = Path(fonts_dir) / font.file_name
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file() or not _verified(str(path), stat.st_size, stat.st_mtime, font.sha256):
        return None
    return path


def line_metrics(data: bytes) -> tuple[int, int, int]:
    """``(unitsPerEm, usWinAscent, usWinDescent)`` from a TrueType/OpenType file."""
    count = struct.unpack(">H", data[4:6])[0]
    tables: dict[bytes, int] = {}
    for i in range(count):
        tag, _checksum, offset, _length = struct.unpack(">4sIII", data[12 + 16 * i : 28 + 16 * i])
        tables[tag] = offset
    if b"head" not in tables or b"OS/2" not in tables:
        raise ValueError("Not a font with head and OS/2 tables")
    units = struct.unpack(">H", data[tables[b"head"] + 18 : tables[b"head"] + 20])[0]
    ascent, descent = struct.unpack(">HH", data[tables[b"OS/2"] + 74 : tables[b"OS/2"] + 78])
    if not units or not ascent + descent:
        raise ValueError("The font has no usable line metrics")
    return units, ascent, descent


MEASURE_EM_PX = 1000


@lru_cache(maxsize=16)
def _measurer(path: str) -> tuple[object, float]:
    from PIL import ImageFont  # Pillow is a dependency already (visual assets)

    units, ascent, descent = line_metrics(Path(path).read_bytes())
    return ImageFont.truetype(path, MEASURE_EM_PX), units / (ascent + descent)


def em_per_size(path: Path) -> float:
    return _measurer(str(path))[1]


@lru_cache(maxsize=8192)
def _glyph(path: str, ch: str) -> float:
    font, em = _measurer(path)
    return font.getlength(ch) / MEASURE_EM_PX * em  # type: ignore[attr-defined]


def text_width_in(text: str, *, font: CaptionFont, path: Path, size: float) -> float:
    """Pixels ``text`` needs at libass ``size`` in ``font`` (uncovered characters in the
    fallback font's measured widths)."""
    units = 0.0
    for ch in text:
        units += _glyph(str(path), ch) if font.covers(ch) else char_width(ch, bold=False)
    return units * size
