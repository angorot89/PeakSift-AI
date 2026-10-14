"""Dynamic caption render probe: word-synced captions and a hook, rendered end to end.

Renders a generated 4 s source with audio through the real ``compose_short`` with a caption_v2
document (known words ONE / TWO / THREE, the Punch preset, bottom placement) and an opening
hook, then checks the MP4 and its frames:

- 1080 × 1920, H.264 video, AAC audio, the source duration;
- during each word, that word (and only one) is drawn in the active colour, left to right;
- the hook is drawn during its seconds and gone afterwards;
- every drawn pixel stays inside the General Social safe area (outline allowance).

Used by CI and the acceptance checklist; no model, no network, writes only to a temporary
directory.

    python scripts/dynamic_caption_probe.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.services.clip_edit.caption_v2 import PRESETS_V2, build_dynamic_ass, rules_for  # noqa: E402
from app.services.clip_edit.composition import (  # noqa: E402
    CAPTIONS_FILENAME,
    RenderOptions,
    compose_short,
)
from app.services.clip_edit.config import (  # noqa: E402
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    CaptionPosition,
    DynamicPreset,
    Layout,
)
from app.services.clip_edit.dynamic_cues import SourceWord, build_word_cues  # noqa: E402
from app.services.clip_edit.hook import HookConfig, hook_ass  # noqa: E402
from app.services.clip_edit.safe_area import GENERAL_SOCIAL, caption_placement  # noqa: E402

SECONDS = 4.0
BACKGROUND = (0x2B, 0x3A, 0x55)
WORDS = [SourceWord("ONE", 0.5, 1.0), SourceWord("TWO", 1.0, 1.5), SourceWord("THREE", 1.5, 2.0)]
HOOK_SECONDS = 1.5
OUTLINE_ALLOWANCE = 30  # outlines, shadows and the hook box may reach past the text box


def frame_at(ffmpeg: str, video: Path, t: float) -> np.ndarray:
    raw = subprocess.run(
        [
            ffmpeg, "-v", "error", "-nostdin", "-ss", f"{t:.2f}", "-i", str(video),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        capture_output=True, check=True, timeout=60,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, np.uint8).reshape(OUTPUT_HEIGHT, OUTPUT_WIDTH, 3).astype(int)


def mask(frame: np.ndarray, rgb: str | tuple[int, int, int], tolerance: int) -> np.ndarray:
    target = np.array(
        [int(rgb[i : i + 2], 16) for i in (1, 3, 5)] if isinstance(rgb, str) else list(rgb)
    )
    return np.abs(frame - target).max(axis=2) <= tolerance


def main() -> int:
    settings = get_settings()
    preset = DynamicPreset.PUNCH
    style = PRESETS_V2[preset]
    place = caption_placement(CaptionPosition.BOTTOM)
    cues = build_word_cues(WORDS, clip_duration=SECONDS, rules=rules_for(preset, place.margin_h))
    hook = HookConfig.create(
        text="PROBE HOOK", style="headline", position="top", duration=HOOK_SECONDS
    )
    hook_style, hook_event = hook_ass(hook, font_family=settings.caption_font_family)
    document = build_dynamic_ass(
        cues,
        preset=preset,
        alignment=place.alignment,
        margin_v=place.margin_v,
        margin_h=place.margin_h,
        font_family=settings.caption_font_family,
        extra_styles=[hook_style],
        extra_events=[hook_event],
    )
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="peaksift-dynamic-caption-probe-") as tmp:
        workspace = Path(tmp)
        source, target = workspace / "source.mp4", workspace / "short.mp4"
        colour = "0x{:02X}{:02X}{:02X}".format(*BACKGROUND)
        subprocess.run(
            [
                settings.ffmpeg_path, "-v", "error", "-y",
                "-f", "lavfi", "-i", f"color=c={colour}:s=1280x720:r=25:d={SECONDS}",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={SECONDS}",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(source),
            ],
            check=True, capture_output=True, timeout=120,
        )  # fmt: skip
        (workspace / CAPTIONS_FILENAME).write_text(document, encoding="utf-8")
        options = RenderOptions(
            ffmpeg_path=settings.ffmpeg_path,
            ffprobe_path=settings.ffprobe_path,
            preset="ultrafast",
            timeout_seconds=300,
        )
        short = compose_short(
            source,
            target,
            layout=Layout.CENTER_CROP,
            options=options,
            workspace=workspace,
            captions=True,
            caption_font=settings.caption_font_family,
        )
        if (short.width, short.height) != (OUTPUT_WIDTH, OUTPUT_HEIGHT):
            problems.append(f"size {short.width}x{short.height}")
        if abs(short.duration_seconds - SECONDS) > 0.3:
            problems.append(f"duration {short.duration_seconds:.2f}s")
        if short.video_codec != "h264":
            problems.append(f"video codec {short.video_codec}")
        if short.audio_codec != "aac":
            problems.append(f"audio codec {short.audio_codec}")

        frames = [frame_at(settings.ffmpeg_path, target, t) for t in (0.8, 1.3, 1.8, 3.0)]
        bottom_edge = OUTPUT_HEIGHT - place.margin_v
        centres = []
        for name, frame in zip(("ONE", "TWO", "THREE"), frames[:3], strict=True):
            captions = frame[OUTPUT_HEIGHT // 2 :]
            active = mask(captions, style.active, 60)
            if active.sum() < 500 or mask(captions, style.text, 60).sum() < 500:
                problems.append(f"{name}: the active and other words are not both drawn")
                continue
            centres.append(np.nonzero(active)[1].mean())
        if len(centres) == 3 and not centres[0] + 40 < centres[1] < centres[2] - 40:
            problems.append(f"the emphasis does not move left to right ({centres})")
        top_band = slice(0, OUTPUT_HEIGHT // 3)
        if (~mask(frames[0][top_band], BACKGROUND, 40)).sum() < 500:
            problems.append("the hook is not drawn during its seconds")
        if (~mask(frames[3][top_band], BACKGROUND, 40)).sum() > 50:
            problems.append("the hook is still drawn after its seconds")
        px = GENERAL_SOCIAL.px()
        for t, frame in zip((0.8, 1.3, 1.8), frames[:3], strict=True):
            ys, xs = np.nonzero(~mask(frame, BACKGROUND, 40))
            if not len(ys):
                problems.append(f"nothing drawn at {t}s")
                continue
            inside = (
                ys.min() >= px["top"] - OUTLINE_ALLOWANCE
                and ys.max() <= bottom_edge + OUTLINE_ALLOWANCE
                and xs.min() >= px["left"] - OUTLINE_ALLOWANCE
                and xs.max() <= OUTPUT_WIDTH - px["right"] + OUTLINE_ALLOWANCE
            )
            if not inside:
                problems.append(
                    f"drawn outside the safe area at {t}s "
                    f"(x {xs.min()}-{xs.max()}, y {ys.min()}-{ys.max()})"
                )
    if problems:
        print("dynamic caption probe FAILED: " + "; ".join(problems))
        return 1
    print(
        "dynamic caption probe: 1080x1920 H.264 + AAC, "
        f"{short.duration_seconds:.2f}s, active word moves ONE→TWO→THREE, "
        "hook shown then gone, all text inside the safe area"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
