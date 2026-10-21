"""The semantic match benchmark: its metrics (ranking, tiers, false matches, quiet negatives),
calibration that never trades safety for recall, manifests, and the CI run on the deterministic
fake provider (no weights, no media)."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from app.services.semantic.benchmark import (
    QUERIES,
    BenchmarkAsset,
    BenchmarkQuery,
    calibrate,
    evaluate,
    load_manifest,
    measure,
    rank,
)
from app.services.semantic.search import Thresholds

BACKEND = Path(__file__).resolve().parents[1]
T = Thresholds(strong=0.6, possible=0.4, prompt="{query}", version="t")


def unit(*values):
    vector = np.zeros(8)
    vector[: len(values)] = values
    return vector / np.linalg.norm(vector)


# Axes: 0 bridge, 1 rocket, 2 city, 3 coral reef, 4 mountain.
BRIDGE, ROCKET, REEF = unit(1), unit(0, 1), unit(0, 0, 0, 1)
ASSETS = [
    BenchmarkAsset("IMG_bridge.jpg", frozenset({"bridge"}), (unit(1, 0.1),)),
    BenchmarkAsset(
        "VID_two.mp4", frozenset({"city", "rocket"}), (unit(0, 0, 1), unit(0, 1, 0.1)), (0.5, 8.3)
    ),
    # Halfway between a bridge and a rocket (cosine 0.5 with each): never strong, at most possible.
    BenchmarkAsset("IMG_mountain.jpg", frozenset({"mountain"}), (unit(0.5, 0.5, 0, 0, 0.7071),)),
]
EMBED = {"bridge": BRIDGE, "rocket": ROCKET, "coral reef": REEF}


def test_rank_uses_each_assets_best_frame_and_its_time():
    ranking = rank(ASSETS, ROCKET, "rocket")
    name, similarity, time, relevant = ranking[0]
    assert (name, time, relevant) == ("VID_two.mp4", 8.3, True)
    assert similarity > 0.99


def test_metrics_count_ranking_tiers_false_matches_and_quiet_negatives():
    queries = [
        BenchmarkQuery("bridge", "bridge", "direct"),
        BenchmarkQuery("rocket", "rocket", "related"),
        BenchmarkQuery("coral reef", None, "negative"),
    ]
    report = evaluate(ASSETS, lambda text: EMBED[text], T, queries)
    m = report.metrics
    assert (m["positive_queries"], m["negative_queries"]) == (2, 1)
    assert m["top1_relevant"] == m["top3_relevant"] == m["found"] == m["strong"] == 2
    # The mountain picture is a possible (never strong) match for "bridge" and for "rocket".
    assert m["false_strong"] == 0 and m["false_possible"] == 2
    assert m["quiet_on_negatives"] == 1  # nothing shows a coral reef
    loose = Thresholds(strong=0.3, possible=0.2, prompt="{query}", version="t")
    assert measure(report.results, loose)["false_strong"] > 0


def test_calibration_never_trades_safety_for_recall():
    queries = [BenchmarkQuery("bridge", "bridge", "direct"),
               BenchmarkQuery("coral reef", None, "negative")]  # fmt: skip
    report = evaluate(ASSETS, lambda text: EMBED[text], T, queries)
    rows = calibrate(report, [0.5, 0.7, 0.9], [0.3, 0.5, 0.75, 0.95])
    safe = [row for row in rows if row[3]]
    assert safe and rows[: len(safe)] == safe  # every safe row ranks above every unsafe one
    strong, possible, metrics, _ = rows[0]
    assert metrics["false_strong"] == 0 and metrics["quiet_on_negatives"] == 1
    assert possible < strong


def test_the_standard_queries_cover_every_kind_and_five_negatives():
    kinds = {query.kind for query in QUERIES}
    assert kinds == {"direct", "related", "contextual", "negative"}
    assert sum(query.concept is None for query in QUERIES) == 5
    assert {"bridge", "rocket", "city", "microphone", "food", "car"} <= {
        query.concept for query in QUERIES if query.concept
    }


def test_manifests_accept_one_or_several_concepts(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps([
        {"file": "IMG_1.jpg", "concept": "bridge"},
        {"file": "VID_2.mp4", "concepts": ["city", "rocket"]},
    ]))  # fmt: skip
    entries = load_manifest(tmp_path)
    assert [e["concepts"] for e in entries] == [["bridge"], ["city", "rocket"]]


def test_the_ci_benchmark_passes_its_safety_gates_without_weights_or_media():
    result = subprocess.run(
        [sys.executable, "scripts/semantic_benchmark.py", "--calibrate"],
        cwd=BACKEND, capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout[-800:]
    assert "top-1 relevant 20" in result.stdout and "false strong matches 0" in result.stdout
    assert "negative queries quiet 5/5" in result.stdout and "safety gates: PASS" in result.stdout
