"""Tiny generated video fixtures for integration tests. Nothing is checked into git."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def have_ffmpeg() -> bool:
    return FFMPEG is not None and FFPROBE is not None


# Integration tests skip on machines without ffmpeg, but CI sets REQUIRE_FFMPEG=1 so a
# missing binary there is a failure rather than a silently skipped test.
requires_ffmpeg = pytest.mark.skipif(
    not have_ffmpeg() and not os.environ.get("REQUIRE_FFMPEG"),
    reason="ffmpeg/ffprobe not installed",
)


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


def have_libass() -> bool:
    """Whether the *configured* FFmpeg (``FFMPEG_PATH``) can burn in captions."""
    from app.core.config import get_settings
    from app.services.clip_edit.composition import supports_captions

    return supports_captions(get_settings().ffmpeg_path)


# Caption rendering needs libass. CI sets REQUIRE_LIBASS=1 so a build without it fails loudly
# instead of skipping; locally the tests skip with a clear reason.
requires_libass = pytest.mark.skipif(
    not os.environ.get("REQUIRE_LIBASS") and not (have_ffmpeg() and have_libass()),
    reason="the configured FFmpeg has no libass (subtitles filter)",
)
