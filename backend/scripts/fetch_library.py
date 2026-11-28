"""Install PeakSift's built-in starter library (run once per server, by an operator).

    python scripts/fetch_library.py [--dir ./library] [--archive path/to/archive.tar.gz]

Downloads the library release archive from its pinned URL (or uses a local copy), refuses it
unless its sha256 matches the pinned digest, extracts only the files ``library_manifest.json``
lists (regular files, no links, no paths outside the target) and verifies each against its own
sha256 before anything replaces an installed library. Files are never committed
(``backend/library/`` is git-ignored); PeakSift never downloads the library by itself.
"""

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.library import MANIFEST_PATH, items, manifest  # noqa: E402

RELEASE_URL = (
    "https://github.com/angorot89/PeakSift-AI/releases/download/library-v1/"
    "peaksift-library-v1.tar.gz"
)
RELEASE_SHA256 = "83c3fa96769705b5e99bfce4287e0ff384bc359057ca7241df55ad05b3d19776"
MAX_BYTES = 200 * 1024 * 1024


def _download(target: Path) -> None:
    with urllib.request.urlopen(RELEASE_URL, timeout=300) as response:  # noqa: S310 - pinned
        with target.open("wb") as handle:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError("the download is larger than expected")
                handle.write(chunk)


def install(archive: Path, target: Path) -> int:
    if hashlib.sha256(archive.read_bytes()).hexdigest() != RELEASE_SHA256:
        raise ValueError("the archive does not match the pinned sha256")
    version = manifest()["version"]
    wanted = {f"{version}/{item.file}": item for item in items()}
    wanted.update({f"{version}/{name}": None for name in manifest()["licences"]})
    wanted[f"{version}/manifest.json"] = None
    staging = Path(tempfile.mkdtemp(dir=target.parent, prefix=".library-"))
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name not in wanted:
                    continue  # anything unexpected is ignored, never written
                if not member.isfile():
                    raise ValueError(f"{member.name} is not a regular file")
                out = staging / member.name.split("/", 1)[1]
                out.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, out.open("wb") as sink:  # type: ignore[union-attr]
                    shutil.copyfileobj(source, sink)
        for name, item in wanted.items():
            path = staging / name.split("/", 1)[1]
            if not path.is_file():
                raise ValueError(f"{name} is missing from the archive")
            if item is not None and hashlib.sha256(path.read_bytes()).hexdigest() != item.sha256:
                raise ValueError(f"{name} does not match its pinned sha256")
        if json.loads((staging / "manifest.json").read_text()) != json.loads(
            MANIFEST_PATH.read_text()
        ):
            raise ValueError("the archive's manifest differs from this version's catalogue")
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
        return len(items())
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", help="where to install (default: LIBRARY_DIR)")
    parser.add_argument("--archive", help="a local copy of the release archive")
    args = parser.parse_args()
    if args.dir:
        target = Path(args.dir)
    else:
        from app.core.config import get_settings

        target = Path(get_settings().library_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as work:
            archive = Path(args.archive) if args.archive else Path(work) / "library.tar.gz"
            if not args.archive:
                _download(archive)
            count = install(archive, target.resolve())
    except (OSError, ValueError, tarfile.TarError) as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 1
    print(f"Installed and verified the library ({count} items).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
