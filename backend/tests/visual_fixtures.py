"""Generated visual fixtures (never committed media): images drawn with Pillow, videos rendered
by FFmpeg. Colours and shapes are known, so renders can be checked pixel by pixel."""

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from app.core.config import get_settings

PIL_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}


def ffmpeg() -> str:
    return get_settings().ffmpeg_path


def make_image(
    path: Path,
    size: tuple[int, int] = (320, 180),
    *,
    color: tuple[int, ...] = (200, 40, 40),
    mode: str = "RGB",
    marker: bool = True,
    **save: object,
) -> Path:
    """A solid image (optionally with a white marker square in the top-left quarter)."""
    image = Image.new(mode, size, color)
    if marker and mode in ("RGB", "RGBA"):
        draw = ImageDraw.Draw(image)
        w, h = size
        draw.rectangle((w // 16, h // 16, w // 4, h // 4), fill=(255, 255, 255, 255)[: len(mode)])
    image.save(path, PIL_FORMATS[path.suffix.lower()], **save)
    return path


def make_transparent_png(path: Path, size: tuple[int, int] = (200, 200)) -> Path:
    """A green disc on a fully transparent background."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((10, 10, size[0] - 10, size[1] - 10), fill=(30, 200, 60, 255))
    image.save(path, "PNG")
    return path


def make_video(
    path: Path,
    *,
    size: str = "320x180",
    seconds: float = 2.0,
    fps: int = 30,
    audio: bool = False,
    source: str | None = None,
    extra_filters: str | None = None,
) -> Path:
    """A synthetic clip (test pattern by default). MP4/MOV use H.264, WebM uses VP9."""
    pattern = source or f"testsrc2=size={size}:rate={fps}:duration={seconds}"
    command = [ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", pattern]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}"]
    if extra_filters:
        command += ["-vf", extra_filters]
    if path.suffix == ".webm":
        command += ["-c:v", "libvpx-vp9", "-b:v", "200k", "-deadline", "realtime"]
        if audio:
            command += ["-c:a", "libopus"]
    else:
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
        if audio:
            command += ["-c:a", "aac"]
    command += ["-t", f"{seconds}", str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    return path


def rotate_metadata(source: Path, target: Path, degrees: int) -> Path:
    """Copy ``source`` with a display-rotation matrix (what phones write), pixels unchanged."""
    subprocess.run(
        [ffmpeg(), "-v", "error", "-y", "-display_rotation", str(degrees), "-i", str(source),
         "-c", "copy", str(target)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    return target
