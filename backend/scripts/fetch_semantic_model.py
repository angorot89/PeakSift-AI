"""Fetch the semantic visual-search model (run once per server, by an operator).

    python scripts/fetch_semantic_model.py [--dir ./models/clip-vit-b-32]

Downloads OpenAI's CLIP ViT-B/32 (MIT license) as ONNX exports published by Qdrant for
fastembed — the image encoder, the text encoder and the tokenizer — from pinned repository
revisions, and refuses each file unless its size and sha256 match the pinned values. Files are
streamed to a temporary file next to the target and renamed into place only when verified; they
are never committed (``*.onnx`` and ``backend/models/`` are git-ignored). PeakSift never
downloads a model by itself: not at import, not at startup, not in tests, not in CI.
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
from app.services.semantic.clip_onnx import MODEL_FILES, file_matches  # noqa: E402

CHUNK = 1024 * 1024


def fetch(name: str, target: Path) -> None:
    pinned = MODEL_FILES[name]
    digest = hashlib.sha256()
    size = 0
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        try:
            with urllib.request.urlopen(pinned.url, timeout=120) as response:  # noqa: S310
                while chunk := response.read(CHUNK):
                    size += len(chunk)
                    if size > pinned.size:
                        raise ValueError("larger than expected")
                    digest.update(chunk)
                    handle.write(chunk)
            if size != pinned.size or digest.hexdigest() != pinned.sha256:
                raise ValueError("does not match the pinned size and sha256")
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise
    os.chmod(handle.name, 0o644)
    os.replace(handle.name, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=get_settings().semantic_model_dir)
    directory = Path(parser.parse_args().dir)
    directory.mkdir(parents=True, exist_ok=True)
    for name in MODEL_FILES:
        target = directory / name
        if file_matches(target, MODEL_FILES[name]):
            print(f"{name}: already installed and verified.")
            continue
        try:
            fetch(name, target)
        except ValueError as error:
            print(f"Refusing {name}: the download {error}.", file=sys.stderr)
            return 1
        print(f"{name}: installed and verified ({MODEL_FILES[name].size} bytes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
