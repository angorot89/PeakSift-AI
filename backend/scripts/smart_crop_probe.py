"""Smart reframe render probe: render the deepest crop path the app allows on this FFmpeg.

The moving crop is an FFmpeg expression tree (see ``app/services/clip_edit/smart_crop.py``);
expression depth limits differ between FFmpeg builds. This renders a generated landscape
source with a ``MAX_SEGMENTS``-segment path through the real ``compose_short`` and checks the
result is a 1080 × 1920 MP4 of the right length with its audio. Used by CI (Ubuntu FFmpeg)
and the acceptance checklist; it needs no model, no network and writes only to a temporary
directory.

    python scripts/smart_crop_probe.py
"""

import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.services.clip_edit.composition import RenderOptions, compose_short  # noqa: E402
from app.services.clip_edit.config import Layout  # noqa: E402
from app.services.clip_edit.smart_crop import MAX_SEGMENTS, CropPoint  # noqa: E402

WIDTH, HEIGHT, SECONDS = 1280, 720, 4.0


def main() -> int:
    settings = get_settings()
    crop_width = HEIGHT * 9 / 16 / WIDTH
    half = crop_width / 2
    # MAX_SEGMENTS segments: a sweep across the frame and back, a keyframe every 4 ms.
    points = [
        CropPoint(
            timestamp=SECONDS * i / MAX_SEGMENTS,
            center_x=half + (1 - 2 * half) * (0.5 - 0.5 * math.cos(2 * math.pi * i / MAX_SEGMENTS)),
            center_y=0.5,
            crop_width=crop_width,
            crop_height=1.0,
        )
        for i in range(MAX_SEGMENTS + 1)
    ]
    with tempfile.TemporaryDirectory(prefix="peaksift-smart-crop-probe-") as tmp:
        source, target = Path(tmp) / "source.mp4", Path(tmp) / "short.mp4"
        subprocess.run(
            [
                settings.ffmpeg_path, "-v", "error", "-y",
                "-f", "lavfi", "-i", f"testsrc2=s={WIDTH}x{HEIGHT}:r=25:d={SECONDS}",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={SECONDS}",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(source),
            ],
            check=True, capture_output=True, timeout=120,
        )  # fmt: skip
        options = RenderOptions(
            ffmpeg_path=settings.ffmpeg_path,
            ffprobe_path=settings.ffprobe_path,
            preset="ultrafast",
            timeout_seconds=300,
        )
        short = compose_short(
            source, target, layout=Layout.SMART_REFRAME, options=options, crop_points=points
        )
    problems = []
    if (short.width, short.height) != (1080, 1920):
        problems.append(f"size {short.width}x{short.height}")
    if abs(short.duration_seconds - SECONDS) > 0.5:
        problems.append(f"duration {short.duration_seconds:.2f}s")
    if short.audio_codec != "aac":
        problems.append("audio missing")
    if problems:
        print("smart crop probe FAILED: " + ", ".join(problems))
        return 1
    print(f"smart crop probe: {MAX_SEGMENTS}-segment path rendered 1080x1920, audio kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
