"""B-roll and visual overlay render probe: the V1.1 visual matrix on this FFmpeg.

Generates every fixture it needs (nothing is downloaded or committed): a 16:9 base clip with
sound, a landscape and a portrait image, a transparent PNG, a landscape and a portrait B-roll
video. It then renders each case through the real ``compose_short`` into a 1080 × 1920 short:
image and video cutaways (fill and fit), picture-in-picture, a transparent overlay, a fade,
several elements in sequence, and captions and the hook on top of a cutaway. Each short is
checked: pixels where the element should (and should not) be, the clip's duration and frame
rate, H.264 video and AAC audio. Used by CI (Ubuntu FFmpeg) and the acceptance checklist; it
needs no database, no model and no network, and writes only to a temporary directory.

    python scripts/visual_render_probe.py
"""

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from PIL import Image, ImageDraw  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.clip_edit.caption_styles import build_ass_document  # noqa: E402
from app.services.clip_edit.captions import Cue  # noqa: E402
from app.services.clip_edit.composition import (  # noqa: E402
    CAPTIONS_FILENAME,
    RenderOptions,
    compose_short,
    supports_visuals,
)
from app.services.clip_edit.config import CaptionPosition, CaptionStyle, Layout  # noqa: E402
from app.services.clip_edit.hook import HookConfig, hook_ass  # noqa: E402
from app.services.ffprobe import probe  # noqa: E402
from app.services.visuals.compositor import VisualLayer  # noqa: E402
from app.services.visuals.config import VisualElement  # noqa: E402

SECONDS, FPS = 3.0, 25
GREY, RED, GREEN, BLUE, YELLOW = (
    (128, 128, 128), (255, 0, 0), (30, 200, 60), (0, 0, 255), (255, 255, 0)
)  # fmt: skip


def run(ffmpeg: str, *args: str) -> None:
    subprocess.run([ffmpeg, "-v", "error", "-y", *args], check=True, capture_output=True,
                   timeout=120)  # fmt: skip


def fixtures(ffmpeg: str, work: Path) -> dict[str, tuple[Path, str, bool, tuple[int, int]]]:
    """name → (path, kind, has_alpha, (width, height)), all generated here."""
    run(ffmpeg, "-f", "lavfi", "-i", f"color=c=0x808080:s=1280x720:r={FPS}:d={SECONDS}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={SECONDS}", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
        str(work / "base.mp4"))  # fmt: skip
    Image.new("RGB", (1600, 900), RED).save(work / "landscape.png")
    portrait = Image.new("RGB", (900, 1600), BLUE)
    ImageDraw.Draw(portrait).rectangle((0, 0, 899, 1599), outline=(255, 255, 255), width=24)
    portrait.save(work / "portrait.png")
    badge = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(badge).ellipse((20, 20, 380, 380), fill=(*GREEN, 255))
    badge.save(work / "transparent.png")
    for name, size, colour in (("landscape.mp4", "1280x720", "0x0000FF"),
                               ("portrait.mp4", "720x1280", "0xFFFF00")):  # fmt: skip
        run(ffmpeg, "-f", "lavfi", "-i", f"color=c={colour}:s={size}:r=30:d=4", "-f", "lavfi",
            "-i", "sine=frequency=3000:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(work / name))  # fmt: skip
    return {
        "landscape.png": (work / "landscape.png", "image", False, (1600, 900)),
        "portrait.png": (work / "portrait.png", "image", False, (900, 1600)),
        "transparent.png": (work / "transparent.png", "image", True, (400, 400)),
        "landscape.mp4": (work / "landscape.mp4", "video", False, (1280, 720)),
        "portrait.mp4": (work / "portrait.mp4", "video", False, (720, 1280)),
    }


def pixel(ffmpeg: str, path: Path, x: int, y: int, t: float) -> tuple[float, float, float]:
    raw = subprocess.run(
        [ffmpeg, "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
         "-vf", f"crop=8:8:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True, timeout=60,
    ).stdout  # fmt: skip
    n = len(raw) // 3
    return tuple(sum(raw[i::3]) / n for i in range(3))  # type: ignore[return-value]


def white_pixels(ffmpeg: str, path: Path, y0: int, y1: int, t: float) -> int:
    """Near-white pixels in the band y0..y1 at time t (caption and hook text)."""
    raw = subprocess.run(
        [ffmpeg, "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
         "-vf", f"crop=1080:{y1 - y0}:0:{y0}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True, timeout=60,
    ).stdout  # fmt: skip
    return sum(1 for value in raw if value > 220)


def close(actual, expected, tolerance=60) -> bool:
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected, strict=True))


def main() -> int:
    settings = get_settings()
    ffmpeg = settings.ffmpeg_path
    if not supports_visuals(ffmpeg):
        print("FAIL this FFmpeg lacks a filter the visual compositor uses")
        return 1
    options = RenderOptions(preset="ultrafast", timeout_seconds=300, ffmpeg_path=ffmpeg,
                            ffprobe_path=settings.ffprobe_path)  # fmt: skip
    font = settings.caption_font_family
    failures = 0
    with tempfile.TemporaryDirectory(prefix="peaksift-visual-probe-") as directory:
        work = Path(directory)
        assets = fixtures(ffmpeg, work)

        def layer(name: str, **element) -> VisualLayer:
            path, kind, alpha, size = assets[name]
            data = {"asset_id": str(uuid.uuid4()), "mode": "cutaway", "start_seconds": 1.0,
                    "end_seconds": 2.0, **element}  # fmt: skip
            return VisualLayer(VisualElement.create(data), path, kind, alpha, *size)

        def text_layer(hook: bool) -> None:
            config = HookConfig.create(
                text="WATCH THIS", style="headline", position="top", duration=2.5
            )
            extra = hook_ass(config, font_family=font)
            cues = [] if hook else [Cue(0.0, SECONDS, "CAPTIONS ON TOP")]
            (work / CAPTIONS_FILENAME).write_text(
                build_ass_document(cues, style=CaptionStyle.BOLD, position=CaptionPosition.CENTER,
                                   font_family=font, extra_styles=[extra[0]] if hook else (),
                                   extra_events=[extra[1]] if hook else ()),
                encoding="utf-8",
            )  # fmt: skip

        # name, layers, checks [(x, y, t, colour, should_match)], text layer
        cases = [
            ("cutaway image (landscape, fill)", [layer("landscape.png", fit="fill")],
             [(540, 960, 1.5, RED, True), (8, 8, 1.5, RED, True),
              (540, 960, 0.5, GREY, True)], None),
            ("cutaway image (portrait, fit)", [layer("portrait.png", fit="fit")],
             [(540, 960, 1.5, BLUE, True), (540, 960, 2.5, GREY, True)], None),
            ("cutaway video (landscape, fill, offset)",
             [layer("landscape.mp4", fit="fill", asset_offset_seconds=1.0)],
             [(540, 960, 1.5, BLUE, True), (540, 960, 2.5, GREY, True)], None),
            ("cutaway video (portrait, fit)", [layer("portrait.mp4", fit="fit")],
             [(540, 960, 1.5, YELLOW, True)], None),
            ("picture-in-picture (video, bottom left)",
             [layer("landscape.mp4", mode="pip", position="bottom_left", size="medium")],
             [(97 + 244, 1498 - 140, 1.5, BLUE, True), (900, 400, 1.5, GREY, True)], None),
            ("transparent overlay (centre)",
             [layer("transparent.png", mode="overlay", position="center", size="small")],
             [(540, 960, 1.5, GREEN, True), (362, 782, 1.5, GREY, True)], None),
            ("fade (cross-fade cutaway)",
             [layer("landscape.png", fit="fill", transition="fade", transition_seconds=0.3)],
             [(540, 960, 1.5, RED, True), (540, 960, 1.16, RED, False)], None),
            ("several elements in sequence",
             [layer("landscape.png", start_seconds=0.4, end_seconds=1.0),
              layer("transparent.png", mode="overlay", position="center", start_seconds=1.2,
                    end_seconds=1.8),
              layer("portrait.mp4", start_seconds=2.0, end_seconds=2.6, fit="fill")],
             [(540, 960, 0.7, RED, True), (540, 960, 1.5, GREEN, True),
              (540, 960, 2.3, YELLOW, True)],
             None),
            ("captions on top of a cutaway",
             [layer("landscape.png", start_seconds=0.5, end_seconds=2.5)],
             [(540, 1500, 1.5, RED, True), ("text", 880, 1040, 1.5)], "captions"),
            ("hook on top of a cutaway",
             [layer("landscape.png", start_seconds=0.2, end_seconds=2.8)],
             [(540, 1500, 1.0, RED, True), ("text", 150, 500, 1.0)], "hook"),
        ]  # fmt: skip
        print(f"{'case':44} result  duration  fps  video/audio")
        for index, (name, layers, checks, text) in enumerate(cases):
            if text:
                text_layer(hook=text == "hook")
            out = work / f"case-{index}.mp4"
            problems: list[str] = []
            try:
                compose_short(
                    work / "base.mp4", out, layout=Layout.BLUR_BACKGROUND, options=options,
                    workspace=work, captions=bool(text), caption_font=font, visuals=layers,
                )  # fmt: skip
                meta = probe(out, ffprobe_path=settings.ffprobe_path)
                if abs((meta.duration_seconds or 0) - SECONDS) > 0.1:
                    problems.append(f"duration {meta.duration_seconds}")
                if round(meta.fps or 0) != FPS:
                    problems.append(f"fps {meta.fps}")
                shape = (meta.width, meta.height, meta.video_codec, meta.audio_codec)
                if shape != (1080, 1920, "h264", "aac"):
                    problems.append("format")
                for check in checks:
                    if check[0] == "text":  # text drawn over the B-roll in this band
                        _, y0, y1, t = check
                        if white_pixels(ffmpeg, out, y0, y1, t) < 300:
                            problems.append(f"no text in y {y0}-{y1} at {t}s")
                        continue
                    x, y, t, colour, should = check
                    if close(pixel(ffmpeg, out, x, y, t), colour) != should:
                        problems.append(f"pixel ({x},{y}) at {t}s")
                codecs = f"{meta.video_codec}/{meta.audio_codec}"
                summary = f"{meta.duration_seconds:.2f}s   {meta.fps:.0f}  {codecs}"
            except Exception as error:  # report every case, then fail
                problems.append(type(error).__name__)
                summary = "-"
            failures += bool(problems)
            print(f"{name:44} {'PASS' if not problems else 'FAIL'}    {summary}"
                  f"{'  ' + '; '.join(problems) if problems else ''}")  # fmt: skip
            (work / CAPTIONS_FILENAME).unlink(missing_ok=True)
    print(f"{len(cases) - failures}/{len(cases)} visual cases rendered correctly")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
