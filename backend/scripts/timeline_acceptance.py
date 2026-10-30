"""Editor timeline release gate: a rendered Short matches the timing its editor showed, against a
running PeakSift (real renders).

    TIMELINE_ACCEPTANCE_EMAIL=… TIMELINE_ACCEPTANCE_PASSWORD=… \\
        python scripts/timeline_acceptance.py --api http://localhost:8000 \\
        --project <id> --video <id> --clip <id> --edit <id>

Signs in as a dedicated acceptance creator (credentials from the environment only), reads the
version's saved configuration — the timing the editor's timeline showed — downloads the rendered
Short and checks, with FFmpeg and the frames themselves:

1. every **cutaway**: the frame matches the visual asset in the middle, at its start and end (just
   inside, past any fade) and does not match it just before and just after;
2. every **sound effect**: a burst of high-frequency energy begins within 0.1 s of its time;
3. **captions** (word-synced): at the middle of two caption lines of the editor's caption preview,
   the rendered frame shows that line's words (Tesseract OCR; at least half of its longer words).

Prints each check and exits 1 when any fails.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from PIL import Image, ImageOps

FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")
TESSERACT = os.environ.get("TESSERACT_PATH", "tesseract")
failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {what}")
    if not ok:
        failures.append(what)


def frame(video: Path, t: float, out: Path) -> Image.Image:
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
         str(out)],
        check=True, timeout=60,
    )  # fmt: skip
    return Image.open(out).convert("RGB")


def patch_mean(image: Image.Image, box: tuple[float, float, float, float]) -> tuple[float, ...]:
    w, h = image.size
    crop = image.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
    pixels = list(crop.resize((16, 16)).get_flattened_data())
    return tuple(sum(p[i] for p in pixels) / len(pixels) for i in range(3))


def distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


def hf_levels(path: Path, start: float, length: float) -> list[float]:
    """Level above 10 kHz in 10 ms steps — where noisy effects (whooshes, hits) carry far more
    energy than speech or music."""
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path),
         "-af", "highpass=f=10000,highpass=f=10000,highpass=f=10000", "-ac", "1", "-ar", "44100",
         "-f", "s16le", "-"],
        capture_output=True, check=True, timeout=60,
    ).stdout  # fmt: skip
    samples = [
        int.from_bytes(raw[i : i + 2], "little", signed=True) for i in range(0, len(raw) - 1, 2)
    ]
    step = 441
    return [
        (sum(s * s for s in samples[i : i + step]) / step) ** 0.5
        for i in range(0, len(samples), step)
    ]


def onset(audio: Path, effect: Path, around: float) -> float | None:
    """Where the effect plays near `around`: the lag (within ±0.5 s) at which the render's
    high-frequency envelope best matches the effect file's own envelope (normalised
    cross-correlation). Measured above 10 kHz, where speech nearby is far quieter than the
    effect."""
    shape = hf_levels(effect, 0.0, 1.5)
    shape = shape[: max(1, len(shape))]
    start = max(0.0, around - 0.5)
    window = hf_levels(audio, start, 1.0 + len(shape) * 0.01 + 0.1)
    n = len(shape)
    mean_s = sum(shape) / n
    ds = [v - mean_s for v in shape]
    norm_s = sum(v * v for v in ds) ** 0.5 or 1.0
    best, when = -2.0, None
    for lag in range(0, max(0, len(window) - n) + 1):
        part = window[lag : lag + n]
        mean_p = sum(part) / n
        dp = [v - mean_p for v in part]
        norm_p = sum(v * v for v in dp) ** 0.5 or 1.0
        score = sum(a * b for a, b in zip(ds, dp, strict=True)) / (norm_s * norm_p)
        if score > best:
            best, when = score, start + lag * 0.01
    return when


def ocr_words(image: Image.Image, box: tuple[float, float, float, float], tmp: Path) -> set[str]:
    w, h = image.size
    crop = image.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
    gray = ImageOps.grayscale(crop)
    # Caption text is bright (white or the emphasis colour) with a dark outline: keep the bright.
    binary = gray.point(lambda v: 0 if v > 170 else 255)
    binary.save(tmp)
    text = subprocess.run(
        [TESSERACT, str(tmp), "stdout", "--psm", "6"], capture_output=True, text=True, timeout=60
    ).stdout
    return {word for word in re.findall(r"[a-z']{3,}", text.lower())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://localhost:8000")
    for name in ("project", "video", "clip", "edit"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    email = os.environ.get("TIMELINE_ACCEPTANCE_EMAIL")
    password = os.environ.get("TIMELINE_ACCEPTANCE_PASSWORD")
    if not email or not password:
        print("Set TIMELINE_ACCEPTANCE_EMAIL and TIMELINE_ACCEPTANCE_PASSWORD.", file=sys.stderr)
        return 2
    c = httpx.Client(base_url=args.api, timeout=300)
    if c.post("/auth/login", json={"email": email, "password": password}).status_code != 200:
        print("Sign-in failed.", file=sys.stderr)
        return 2
    base = f"/projects/{args.project}/videos/{args.video}/clips/{args.clip}"
    edit = c.get(f"{base}/edits/{args.edit}").json()
    if edit.get("status") != "ready":
        print("The version is not rendered.", file=sys.stderr)
        return 2
    config = edit["configuration"]
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        short = tmp / "short.mp4"
        short.write_bytes(c.get(f"/edits/{args.edit}/download").content)

        # 1. Cutaways: the frame is the asset inside the interval, and not outside it.
        center = (0.35, 0.40, 0.65, 0.60)
        for element in (config.get("visuals") or {}).get("elements", []):
            if element["mode"] != "cutaway":
                continue
            start, end = element["start_seconds"], element["end_seconds"]
            asset = tmp / "asset"
            asset.write_bytes(
                c.get(
                    f"/projects/{args.project}/visual-assets/{element['asset_id']}/content"
                ).content
            )
            try:
                reference = patch_mean(Image.open(asset).convert("RGB"), center)
            except OSError:
                reference = patch_mean(frame(asset, 0.5, tmp / "asset.png"), center)
            inside = [start + 0.35, (start + end) / 2, end - 0.35]
            outside = [t for t in (start - 0.35, end + 0.35) if 0 <= t <= edit["duration_seconds"]]
            near = [
                distance(patch_mean(frame(short, t, tmp / "f.png"), center), reference)
                for t in inside
            ]
            far = [
                distance(patch_mean(frame(short, t, tmp / "f.png"), center), reference)
                for t in outside
            ]
            check(
                max(near) < 40 and all(d > max(near) + 25 for d in far),
                f"cutaway {start:.2f}–{end:.2f} s is on screen exactly then "
                f"(inside {', '.join(f'{d:.0f}' for d in near)}; "
                f"outside {', '.join(f'{d:.0f}' for d in far)})",
            )

        # 2. Sound effects: the burst begins at its time.
        audio = tmp / "audio.wav"
        subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-i", str(short), "-vn", str(audio)],
            check=True,
            timeout=60,
        )
        for cue in (config.get("audio") or {}).get("sfx", []):
            if cue["at_seconds"] > edit["duration_seconds"] - 0.3:
                print(
                    f"SKIP sound effect at {cue['at_seconds']:.2f} s: it starts as the Short "
                    "ends, so it is cut"
                )
                continue
            effect = tmp / "effect"
            effect.write_bytes(
                c.get(f"/projects/{args.project}/audio-assets/{cue['asset_id']}/content").content
            )
            heard = onset(audio, effect, cue["at_seconds"])
            check(
                heard is not None and abs(heard - cue["at_seconds"]) <= 0.1,
                f"sound effect at {cue['at_seconds']:.2f} s is heard from "
                f"{heard if heard is None else round(heard, 2)} s",
            )

        # 3. Captions: the line the editor's timeline marks at a time is the line rendered there.
        captions = config.get("captions") or {}
        if captions.get("enabled") and captions.get("renderer"):
            params = {
                "style": captions["style"],
                "position": captions.get("position") or "bottom",
                "timing": captions.get("timing"),
            }
            if captions.get("track_id"):
                params["track_id"] = captions["track_id"]
            cues = c.get(f"{base}/caption-preview", params=params).json().get("cues", [])
            band = {"top": (0.05, 0.10, 0.95, 0.40), "center": (0.05, 0.35, 0.95, 0.65)}.get(
                params["position"], (0.05, 0.55, 0.95, 0.92)
            )
            for cue in (
                [cues[len(cues) // 3], cues[(2 * len(cues)) // 3]] if len(cues) >= 3 else cues
            ):
                words = {
                    w
                    for line in cue["lines"]
                    for word in line
                    for w in re.findall(r"[a-z']{4,}", word["text"].lower())
                }
                if not words:
                    continue
                seen = ocr_words(
                    frame(short, (cue["start"] + cue["end"]) / 2, tmp / "c.png"),
                    band,
                    tmp / "ocr.png",
                )
                found = words & seen
                check(
                    len(found) >= max(1, len(words) // 2),
                    f"caption at {cue['start']:.2f}–{cue['end']:.2f} s shows its line "
                    f"({len(found)}/{len(words)} words read)",
                )
    print("TIMELINE ACCEPTANCE " + ("FAILED" if failures else "PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
