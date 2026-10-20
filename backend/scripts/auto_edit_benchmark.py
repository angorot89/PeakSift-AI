"""Auto Edit quality check: plan six representative clips with every recipe and describe the
results (see app/services/auto_edit/benchmark.py). Descriptive QA — no score is computed.

    python scripts/auto_edit_benchmark.py                 # the deterministic rules
    python scripts/auto_edit_benchmark.py --planner ollama  # the configured local model
    python scripts/auto_edit_benchmark.py --planner ollama --json results.json

With ``--planner ollama`` the model's failures fall back to the rules exactly as in production,
and the report shows when that happened. Needs no database, no media and no network beyond the
operator's local model server.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.services.auto_edit.benchmark import CASES, evaluate  # noqa: E402
from app.services.auto_edit.fallback import FallbackAutoEditPlanner  # noqa: E402
from app.services.auto_edit.planners import get_planner, planner_model  # noqa: E402
from app.services.auto_edit.recipes import RECIPE_ORDER  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--planner", choices=["fallback", "ollama"], default="fallback")
    parser.add_argument("--json", type=Path, help="also write the rows as JSON")
    args = parser.parse_args()
    settings = get_settings()
    if args.planner == "ollama":
        model = planner_model(settings)
        planner = get_planner(settings, "ollama", model)
        print(f"Planner: local model {model} (rules stand in when it cannot answer)")
    else:
        planner = FallbackAutoEditPlanner()
        print("Planner: PeakSift's deterministic rules")
    rows = []
    header = (
        f"{'case':24} {'recipe':8} {'by':8} {'layout':15} {'captions':22} {'hook':>4} "
        f"{'vis':>3} {'rel':>4} {'sfx':>3} {'mus':>3} {'dens':>5} {'deg':>3} {'hal':>3}"
    )
    print(header)
    started = time.monotonic()
    for case in CASES:
        for recipe in RECIPE_ORDER:
            report = evaluate(case, recipe.value, planner)
            rows.append(report.row())
            hook = "—" if report.hook is None else ("yes" if report.hook_grounded else "NO")
            relevance = "—" if report.visual_relevance is None else f"{report.visual_relevance:.0%}"
            planner_label = "rules*" if report.fallback_reason else report.planner[:8]
            layout = report.layout or "INVALID"
            print(
                f"{case.name:24} {recipe.value:8} {planner_label:8} {layout:15} "
                f"{report.captions or 'off':22} {hook:>4} {report.visuals:>3} {relevance:>4} "
                f"{report.sound_effects:>3} {'yes' if report.music else 'no':>3} "
                f"{report.effect_density:>5} {report.degraded:>3} {report.hallucinated:>3}"
            )
    elapsed = time.monotonic() - started
    invalid = sum(not r["valid"] for r in rows)
    ungrounded = sum(r["hook_grounded"] is False for r in rows)
    hallucinated = sum(r["hallucinated"] for r in rows)
    fallbacks = sum(bool(r["fallback_reason"]) for r in rows)
    print(
        f"\n{len(rows)} plans in {elapsed:.0f}s · invalid {invalid} · ungrounded hooks "
        f"{ungrounded} · hallucinated/mismatched assets removed {hallucinated} · rules stood in "
        f"{fallbacks} time(s)"
    )
    print("hook: grounded in the clip; rel: visuals whose asset matches its suggestion; dens:")
    print("visuals + effects per 10 s; deg: choices the server replaced; hal: invented or")
    print("mismatched handles the server removed; rules*: the local model could not answer.")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1))
    return 1 if invalid else 0


if __name__ == "__main__":
    sys.exit(main())
