"""Tiny generated video fixtures for integration tests. Nothing is checked into git."""

import shutil
import subprocess
from pathlib import Path

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def have_ffmpeg() -> bool:
    return FFMPEG is not None and FFPROBE is not None


def generate_video(
    target: Path, *, seconds: float = 1.0, fps: int = 30, audio: bool = True
) -> Path:
    """Render a small synthetic clip (64x64 test pattern, optional sine audio)."""
    assert FFMPEG, "ffmpeg is required to generate fixtures"
    command = [
        FFMPEG,
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={seconds}:size=64x64:rate={fps}",
    ]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    if target.suffix == ".webm":
        command += ["-c:v", "libvpx-vp9", "-b:v", "100k"]
        if audio:
            command += ["-c:a", "libopus"]
    else:
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
        if audio:
            command += ["-c:a", "aac"]
    command += ["-shortest", str(target)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return target
