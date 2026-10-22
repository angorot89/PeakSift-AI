"""Creator insights benchmark: how often the engine finds patterns that are not there, and how
often it finds ones that are. Engine only, synthetic, deterministic.

    python scripts/insights_benchmark.py [--libraries N]

Synthetic creator libraries are generated in memory (seeded), never written to a database —
synthetic insights can never appear as a creator's data. Each short gets random editing features
and log-normal first-week figures (σ is the spread of a creator's shorts: 0.5 is a steady
creator, 0.8 a volatile one).

- **Null libraries** have no real effect at all: any reported pattern is a false one. The share
  of libraries with at least one is the engine's practical false-positive rate (family-wise
  target ``ALPHA``: the Holm–Bonferroni correction across every comparison tested).
- **Effect libraries** give shorts with an opening hook ×1.5, ×2 or ×3 engaged views: the share
  where the engine reports it (in the right direction) is its detection rate. Small libraries
  are meant to say "No reliable pattern yet" rather than guess.

Exit status 1 when a safety gate fails: the false-positive rate over all null libraries above
6% (each setting is printed too; single settings of a few dozen libraries are noisy), a
statement outside the observational templates, or a library below the minimum sample that
reports anything.
"""

import argparse
import math
import random
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.performance import insights as engine  # noqa: E402

FEATURES = {
    "captions": ("on", "off"), "hook": ("with_hook", "no_hook"),
    "music": ("with_music", "no_music"), "visuals": ("with_visuals", "no_visuals"),
    "made_with": ("auto_edit", "editor"),
    "layout": ("smart_reframe", "blur_background", "center_crop"),
    "length": ("under_20s", "20_to_40s", "over_40s"),
    "caption_style": ("punch", "boxed", "minimal", "focus"),
}  # fmt: skip
FALSE_POSITIVE_GATE = 0.06
FORBIDDEN = re.compile(r"\b(will|viral|best|guarantee\w*|because|caus\w*|predict\w*)\b", re.I)
TEMPLATE = re.compile(
    r"^In your recent uploads, shorts .+ have tended to .+ \(\d+ vs \d+ shorts\)\.$"
)


def library(rng: random.Random, size: int, sigma: float, hook_effect: float = 1.0):
    shorts = []
    for _ in range(size):
        features = {name: rng.choice(values) for name, values in FEATURES.items()}
        engaged = 1000 * math.exp(rng.gauss(0, sigma))
        if features["hook"] == "with_hook":
            engaged *= hook_effect
        retention = 50 * math.exp(rng.gauss(0, sigma / 3))
        shorts.append(engine.Short(
            uuid.UUID(int=rng.getrandbits(128)), datetime(2026, 9, 1, tzinfo=UTC), features,
            {"engaged_views": engaged, "average_view_percentage": retention},
        ))  # fmt: skip
    return shorts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--libraries", type=int, default=200, help="libraries per setting")
    args = parser.parse_args()
    rng = random.Random(20261022)
    gates = True
    statements: list[str] = []
    worst = 0.0
    null_found = null_total = 0
    print(f"engine {engine.ENGINE_VERSION}: minimum {engine.MIN_SAMPLE} shorts, "
          f"{engine.MIN_GROUP} per side, ratio ≥ {engine.MIN_RATIO}, "
          f"family-wise α = {engine.ALPHA} (Holm–Bonferroni)")  # fmt: skip
    print("\nnull libraries (no real effect): share with any reported pattern")
    for sigma in (0.5, 0.8):
        for size in (12, 20, 40):
            found = [engine.find_patterns(library(rng, size, sigma))
                     for _ in range(args.libraries)]  # fmt: skip
            rate = sum(bool(f) for f in found) / len(found)
            worst = max(worst, rate)
            null_found += sum(bool(f) for f in found)
            null_total += len(found)
            statements += [p.statement for f in found for p in f]
            print(f"  σ={sigma} {size:>2} shorts: {rate:5.1%}")
    print("\neffect libraries: share reporting the hook pattern (right direction)")
    for sigma in (0.5, 0.8):
        for size in (12, 20, 40):
            cells = []
            for effect in (1.5, 2.0, 3.0):
                hits = 0
                for _ in range(args.libraries // 2):
                    patterns = engine.find_patterns(library(rng, size, sigma, effect))
                    statements += [p.statement for p in patterns]
                    hits += any(p.feature == "hook" and p.metric == "engaged_views"
                                and p.direction == "higher" for p in patterns)  # fmt: skip
                cells.append(f"×{effect:g} {hits / (args.libraries // 2):5.1%}")
            print(f"  σ={sigma} {size:>2} shorts: " + "  ".join(cells))
    small = [engine.find_patterns(library(rng, engine.MIN_SAMPLE - 1, 0.5, 3.0))
             for _ in range(50)]  # fmt: skip
    quiet_below_minimum = not any(small)
    bad = [s for s in statements if FORBIDDEN.search(s) or not TEMPLATE.match(s)]
    pooled = null_found / null_total
    print(
        f"\nfalse-positive rate: {pooled:.1%} over {null_total} null libraries "
        f"(gate ≤ {FALSE_POSITIVE_GATE:.0%}; worst single setting {worst:.1%})"
    )
    print(f"statements checked: {len(statements)}, outside the observational templates: {len(bad)}")
    print(f"below the minimum sample: {'quiet' if quiet_below_minimum else 'REPORTED PATTERNS'}")
    gates = pooled <= FALSE_POSITIVE_GATE and not bad and quiet_below_minimum
    print("\nsafety gates: " + ("PASS" if gates else "FAIL"))
    return 0 if gates else 1


if __name__ == "__main__":
    raise SystemExit(main())
