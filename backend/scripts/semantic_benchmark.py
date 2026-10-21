"""Semantic match benchmark (CI: the deterministic fake; acceptance: the real local model).

    python scripts/semantic_benchmark.py
    python scripts/semantic_benchmark.py --model-dir ./models/clip-vit-b-32 --media DIR \\
        [--calibrate] [--json report.json]

Without ``--model-dir`` it runs the deterministic fake provider on generated pictures (one per
concept, no weights, no media): CI checks the benchmark machinery and the safety gates. With
the real model it reads ``DIR/manifest.json`` (``[{"file": …, "concept"|"concepts": …}]``) —
images and videos the operator is entitled to use (the documented set is public-domain / CC0
photos and videos made from them) — indexes them exactly as PeakSift does (canonical pixels,
bounded video frames) and evaluates the standard queries with the model's current thresholds.
``--calibrate`` also prints the threshold grid. Similarities are ranking signals, not
probabilities; nothing is sent anywhere.

Exit status 1 when a safety gate fails: any false strong match, any negative query with a
match, or — in fake mode — any positive query whose first result is not relevant.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.semantic.benchmark import (  # noqa: E402
    BenchmarkAsset,
    calibrate,
    evaluate,
    load_manifest,
    tier,
)
from app.services.semantic.fake import CONCEPTS, FakeEmbeddingProvider  # noqa: E402
from app.services.semantic.images import canonical_rgb  # noqa: E402
from app.services.semantic.search import thresholds_for  # noqa: E402

FAKE_CONCEPTS = {  # benchmark concept → the fake palette's concept (its colour)
    "bridge": "bridge", "rocket": "rocket", "city": "city", "microphone": "microphone",
    "food": "kitchen", "car": "car",
}  # fmt: skip
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}


def fake_library(provider: FakeEmbeddingProvider) -> list[BenchmarkAsset]:
    assets = []
    for concept, palette in FAKE_CONCEPTS.items():
        image = Image.new("RGB", (160, 90), CONCEPTS[palette][0])
        ImageDraw.Draw(image).rectangle((20, 20, 60, 50), fill=(250, 250, 250))
        (vector,) = provider.embed_images([image])
        assets.append(BenchmarkAsset(f"IMG_{concept}.png", frozenset({concept}), (vector,)))
    return assets


def real_library(provider, media: Path) -> list[BenchmarkAsset]:
    from app.services.semantic.sampling import sample_video

    settings = get_settings()
    assets = []
    for entry in load_manifest(media):
        path = media / entry["file"]
        if path.suffix.lower() in VIDEO_SUFFIXES:
            duration = _duration(path, settings.ffprobe_path)
            with tempfile.TemporaryDirectory() as work:
                frames = sample_video(
                    path,
                    duration,
                    Path(work),
                    ffmpeg_path=settings.ffmpeg_path,
                    max_frames=settings.semantic_video_max_frames,
                    timeout=60,
                )
            images = [canonical_rgb(frame.image) for frame in frames]
            times = tuple(frame.time for frame in frames)
        else:
            with Image.open(path) as opened:
                opened.load()
                images = [canonical_rgb(opened)]
            times = (None,)
        vectors = tuple(provider.embed_images(images))
        assets.append(BenchmarkAsset(entry["file"], frozenset(entry["concepts"]), vectors, times))
    return assets


def _duration(path: Path, ffprobe: str) -> float:
    import subprocess

    out = subprocess.run(  # noqa: S603 - argument list, no shell
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=30, check=True,
    )  # fmt: skip
    return float(out.stdout.strip())


def print_report(report, assets) -> None:
    print(f"{len(assets)} assets · thresholds strong ≥ {report.thresholds.strong}, possible ≥ "
          f"{report.thresholds.possible} ({report.thresholds.version})\n")  # fmt: skip
    for result in report.results:
        top = ", ".join(
            f"{name}{'' if time is None else f'@{time:.1f}s'} {sim:.3f}"
            f"{'' if not tier(sim, report.thresholds) else ' ' + tier(sim, report.thresholds)}"
            f"{' ✓' if relevant else ''}"
            for name, sim, time, relevant in result.ranking[:3]
        )
        print(f"[{result.query.kind:10}] {result.query.text:36} → {top}")
    m = report.metrics
    print(
        f"\npositive queries {m['positive_queries']}: top-1 relevant {m['top1_relevant']}, top-3 "
        f"relevant {m['top3_relevant']}, found (≥ possible) {m['found']}, strong {m['strong']}"
        f"\nfalse strong matches {m['false_strong']} · false possible matches "
        f"{m['false_possible']} · negative queries quiet {m['quiet_on_negatives']}/"
        f"{m['negative_queries']}"
    )  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-dir")
    parser.add_argument("--media", type=Path)
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.model_dir:
        if not args.media:
            parser.error("--media is required with --model-dir")
        from app.services.semantic.clip_onnx import CLIP_IDENTITY, ClipOnnxProvider

        provider = ClipOnnxProvider(args.model_dir)
        thresholds = thresholds_for(CLIP_IDENTITY)
        assets = real_library(provider, args.media)
    else:
        from app.services.semantic.fake import FAKE_IDENTITY

        provider = FakeEmbeddingProvider()
        thresholds = thresholds_for(FAKE_IDENTITY)
        assets = fake_library(provider)
    report = evaluate(assets, provider.embed_text, thresholds)
    print_report(report, assets)
    if args.calibrate:
        strong_grid = [round(0.2 + i * 0.005, 3) for i in range(25)] if args.model_dir else [
            round(0.3 + i * 0.05, 2) for i in range(12)]  # fmt: skip
        possible_grid = [round(0.18 + i * 0.005, 3) for i in range(20)] if args.model_dir else [
            round(0.1 + i * 0.05, 2) for i in range(12)]  # fmt: skip
        rows = calibrate(report, strong_grid, possible_grid)
        print("\ncalibration (best first): strong possible | found strong false-strong "
              "false-possible quiet | safe")  # fmt: skip
        for strong, possible, m, safe in rows[:12]:
            print(f"  {strong:.3f} {possible:.3f} | {m['found']:3} {m['strong']:3} "
                  f"{m['false_strong']:3} {m['false_possible']:3} {m['quiet_on_negatives']:3} | "
                  f"{'safe' if safe else 'UNSAFE'}")  # fmt: skip
    if args.json:
        args.json.write_text(json.dumps(report.as_dict(), indent=1))
    m = report.metrics
    gates = m["false_strong"] == 0 and m["quiet_on_negatives"] == m["negative_queries"]
    if not args.model_dir:
        gates = gates and m["top1_relevant"] == m["positive_queries"]
    print("\nsafety gates: " + ("PASS" if gates else "FAIL"))
    return 0 if gates else 1


if __name__ == "__main__":
    raise SystemExit(main())
