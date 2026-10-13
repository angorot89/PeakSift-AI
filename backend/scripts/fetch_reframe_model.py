"""Fetch the smart-reframing face detector model (run once per server, by an operator).

    python scripts/fetch_reframe_model.py [--path ./models/face_detection_yunet_2023mar.onnx]

Downloads OpenCV Zoo's YuNet face detector (MIT license, © 2020 Shiqi Yu) from a pinned URL
and refuses it unless its sha256 matches the pinned digest. The file is written atomically
and never committed (``*.onnx`` and ``backend/models/`` are git-ignored). PeakSift never
downloads a model by itself: not at import, not at startup, not in tests.
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
from app.services.reframe.yunet import MODEL_SHA256  # noqa: E402

MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/"
    "main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
MAX_BYTES = 5 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=get_settings().reframe_model_path)
    target = Path(parser.parse_args().path)
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == MODEL_SHA256:
        print("Face detector model already installed and verified.")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(MODEL_URL, timeout=120) as response:  # noqa: S310 - pinned https URL
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        print("Refusing: the download is larger than expected.", file=sys.stderr)
        return 1
    digest = hashlib.sha256(data).hexdigest()
    if digest != MODEL_SHA256:
        print("Refusing: the downloaded file does not match the pinned sha256.", file=sys.stderr)
        return 1
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        handle.write(data)
    os.chmod(handle.name, 0o644)
    os.replace(handle.name, target)
    print(f"Installed and verified the face detector model ({len(data)} bytes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
