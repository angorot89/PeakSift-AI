"""Caption font probe: the font families captions rely on really draw through libass.

"Some font exists" is not enough: libass silently falls back, so each family the app expects
is checked by name in fontconfig, then drawn and compared with the same number of unassigned
code points (U+10FFFD), which draw as missing-glyph boxes or nothing. Real glyphs must differ.

- Latin: the configured caption font (``CAPTION_FONT_FAMILY``, Noto Sans).
- Arabic: Noto Sans Arabic, reached by fallback from the caption font (as captions use it).
- Emoji: a monochrome emoji family from ``EMOJI_FONT_CANDIDATES`` (libass cannot draw colour
  emoji); without one, dynamic captions leave emoji out, which the probe reports as a failure
  because CI is expected to install Symbola.

Used by CI and the acceptance checklist; no network, writes only to a temporary directory.

    python scripts/caption_font_probe.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.services.clip_edit.emoji import EMOJI_FONT_CANDIDATES, _render, emoji_font  # noqa: E402

MISSING = "\U0010fffd"


def resolves(family: str) -> bool:
    fc_match = shutil.which("fc-match")
    if fc_match is None:
        return False
    found = subprocess.run(
        [fc_match, "-f", "%{family[0]}", family], capture_output=True, text=True, timeout=30
    ).stdout
    return found.strip() == family


def draws(ffmpeg: str, family: str, sample: str, workdir: Path) -> bool:
    text = _render(ffmpeg, f"{{\\fn{family}}}{sample}", workdir)
    missing = _render(ffmpeg, f"{{\\fn{family}}}{MISSING * len(sample)}", workdir)
    return any(text) and text != missing


def main() -> int:
    settings = get_settings()
    ffmpeg, font = settings.ffmpeg_path, settings.caption_font_family
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="peaksift-font-probe-") as tmp:
        workdir = Path(tmp)
        if not resolves(font):
            problems.append(f"the caption font {font} does not resolve by name")
        if not draws(ffmpeg, font, "Hg PeakSift", workdir):
            problems.append(f"Latin text does not draw with {font}")
        if not resolves("Noto Sans Arabic"):
            problems.append("Noto Sans Arabic does not resolve by name")
        if not draws(ffmpeg, font, "مرحبا", workdir):
            problems.append(f"Arabic text does not draw through {font} fallback")
    emoji = emoji_font(ffmpeg)
    if emoji not in EMOJI_FONT_CANDIDATES:
        problems.append("no monochrome emoji font draws emoji (emoji would be left out)")
    if problems:
        print("caption font probe FAILED: " + "; ".join(problems))
        return 1
    print(f"caption font probe: Latin ({font}), Arabic (Noto Sans Arabic), emoji ({emoji}) draw")
    return 0


if __name__ == "__main__":
    sys.exit(main())
