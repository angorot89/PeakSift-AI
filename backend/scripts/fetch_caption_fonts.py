"""Install the caption style fonts (run once per server, by an operator).

    python scripts/fetch_caption_fonts.py [--dir ./fonts]

Downloads each allow-listed font of ``app/services/clip_edit/caption_fonts.py`` and its licence
file from the google/fonts repository at a pinned commit, and refuses any file whose sha256
differs from the pinned digest. Files are written atomically into ``CAPTION_FONTS_DIR`` and
never committed (``backend/fonts/`` is git-ignored). PeakSift never downloads a font by itself:
not at import, not at startup, not in tests. A style whose font is not installed is shown as
unavailable and cannot be rendered.
"""

import argparse
import hashlib
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.clip_edit.caption_fonts import CAPTION_FONTS, GOOGLE_FONTS_RAW  # noqa: E402

MAX_BYTES = 2 * 1024 * 1024


def install(url: str, sha256: str, target: Path) -> str:
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == sha256:
        return "already installed"
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - pinned https URL
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("larger than expected")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("does not match the pinned sha256")
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        handle.write(data)
    os.chmod(handle.name, 0o644)
    os.replace(handle.name, target)
    return f"installed ({len(data)} bytes)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=get_settings().caption_fonts_dir)
    target = Path(parser.parse_args().dir)
    target.mkdir(parents=True, exist_ok=True)
    failed = False
    for font in CAPTION_FONTS.values():
        for path, sha256, name in (
            (font.repo_path, font.sha256, font.file_name),
            (font.licence_path, font.licence_sha256, font.licence_name),
        ):
            try:
                result = install(GOOGLE_FONTS_RAW + path, sha256, target / name)
            except (OSError, ValueError) as error:
                failed = True
                result = f"refused: {error}"
            print(f"{name}: {result}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
