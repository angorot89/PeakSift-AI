"""The semantic match benchmark: does PeakSift find the visual that shows what a B-roll
suggestion asks for — and stay quiet when nothing in the library fits?

A benchmark library is a set of assets, each with the concepts it really shows (a two-scene
video shows two), and vectors exactly as indexing makes them (one per image, one per sampled
video frame). Queries are grouped as **direct** ("bridge"), **related** ("bridge structure"),
**contextual** ("weak joint in a bridge") and **negative** (a concept no asset shows).

Every query is scored the way search scores it: an asset's similarity is its best frame's cosine
similarity with the query (inside the model's prompt template), tiered by the model's thresholds.
Reported, never blended into one "accuracy":

- **Top-1 / Top-3 relevant** — positive queries whose highest-ranked (any of the 3 highest)
  assets show the concept: ranking quality, independent of thresholds;
- **found / strong** — positive queries whose best relevant asset reaches *possible* / *strong*;
- **false strong / false possible** — (query, asset that does not show it) pairs at that tier,
  over every query: what Auto Edit could wrongly place (strong) or offer (possible);
- **quiet on negatives** — negative queries with no asset at *possible* or above.

``calibrate`` searches a threshold grid for the most permissive cut-offs that keep zero false
strong matches and every negative query quiet (then the most found / strong; ties → the more
conservative cut-off). The chosen values are versioned per model in ``search.THRESHOLDS``.
"""

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.services.semantic.search import Thresholds

QUERY_KINDS = ("direct", "related", "contextual", "negative")


@dataclass(frozen=True)
class BenchmarkAsset:
    name: str
    concepts: frozenset[str]
    vectors: tuple[np.ndarray, ...]  # unit vectors: the image, or each sampled frame
    times: tuple[float | None, ...] = ()


@dataclass(frozen=True)
class BenchmarkQuery:
    text: str
    concept: str | None  # None: a negative query (no asset shows it)
    kind: str


# The standard query set: six concepts a creator's library might hold, and five it does not.
QUERIES: tuple[BenchmarkQuery, ...] = tuple(
    BenchmarkQuery(text, concept, kind)
    for concept, items in {
        "bridge": [("bridge", "direct"), ("bridge structure", "related"),
                   ("weak joint in a bridge", "contextual"),
                   ("suspension bridge cables", "related")],
        "rocket": [("rocket", "direct"), ("rocket launch", "related"),
                   ("smoke rising from the launch pad", "contextual"),
                   ("spacecraft liftoff", "related")],
        "city": [("city skyline", "direct"), ("downtown skyscrapers at night", "related"),
                 ("the city where the startup began", "contextual")],
        "microphone": [("microphone", "direct"), ("podcast recording", "related"),
                       ("speaking into a studio mic", "contextual")],
        "food": [("salad", "direct"), ("healthy food", "related"),
                 ("what I eat before training", "contextual")],
        "car": [("car interior", "direct"), ("steering wheel", "related"),
                ("driving to work in the morning", "contextual")],
        None: [("underwater coral reef", "negative"), ("a cat sleeping on a sofa", "negative"),
               ("birthday party with balloons", "negative"), ("medieval castle", "negative"),
               ("surgeons in an operating room", "negative")],
    }.items()
    for text, kind in items
)  # fmt: skip


@dataclass
class QueryResult:
    query: BenchmarkQuery
    ranking: list[tuple[str, float, float | None, bool]]  # name, similarity, best time, relevant


@dataclass
class Report:
    results: list[QueryResult]
    thresholds: Thresholds
    metrics: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "thresholds": {"strong": self.thresholds.strong, "possible": self.thresholds.possible,
                           "version": self.thresholds.version},
            "metrics": self.metrics,
            "queries": [
                {"query": r.query.text, "kind": r.query.kind, "concept": r.query.concept,
                 "top3": [(n, round(s, 4), t, rel) for n, s, t, rel in r.ranking[:3]]}
                for r in self.results
            ],
        }  # fmt: skip


def rank(assets: Sequence[BenchmarkAsset], query: np.ndarray, concept: str | None):
    """Best-frame similarity per asset, highest first (the search's own aggregation)."""
    scored = []
    for asset in assets:
        sims = [float(np.dot(vector, query)) for vector in asset.vectors]
        best = int(np.argmax(sims))
        time = asset.times[best] if asset.times else None
        scored.append((asset.name, sims[best], time, concept in asset.concepts))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def tier(similarity: float, thresholds: Thresholds) -> str | None:
    if similarity >= thresholds.strong:
        return "strong"
    if similarity >= thresholds.possible:
        return "possible"
    return None


def measure(results: Iterable[QueryResult], thresholds: Thresholds) -> dict[str, int]:
    m = {"positive_queries": 0, "negative_queries": 0, "top1_relevant": 0, "top3_relevant": 0,
         "found": 0, "strong": 0, "false_strong": 0, "false_possible": 0,
         "quiet_on_negatives": 0}  # fmt: skip
    for result in results:
        tiers = [(tier(sim, thresholds), relevant) for _, sim, _, relevant in result.ranking]
        m["false_strong"] += sum(t == "strong" and not rel for t, rel in tiers)
        m["false_possible"] += sum(t == "possible" and not rel for t, rel in tiers)
        if result.query.concept is None:
            m["negative_queries"] += 1
            m["quiet_on_negatives"] += all(t is None for t, _ in tiers)
            continue
        m["positive_queries"] += 1
        m["top1_relevant"] += bool(result.ranking and result.ranking[0][3])
        m["top3_relevant"] += any(rel for *_, rel in result.ranking[:3])
        best = max((sim for _, sim, _, rel in result.ranking if rel), default=None)
        if best is not None:
            m["found"] += tier(best, thresholds) is not None
            m["strong"] += tier(best, thresholds) == "strong"
    return m


def evaluate(
    assets: Sequence[BenchmarkAsset],
    embed_query: Callable[[str], np.ndarray],
    thresholds: Thresholds,
    queries: Sequence[BenchmarkQuery] = QUERIES,
) -> Report:
    results = [
        QueryResult(query, rank(assets, embed_query(thresholds.prompt.format(query=query.text)),
                                query.concept))
        for query in queries
    ]  # fmt: skip
    return Report(results, thresholds, measure(results, thresholds))


def calibrate(
    report: Report, strong_grid: Iterable[float], possible_grid: Iterable[float]
) -> list[tuple[float, float, dict[str, int], bool]]:
    """Every (strong, possible) pair with its metrics and whether it passes the safety gates
    (no false strong match, every negative query quiet), best candidate first."""
    rows = []
    for strong in strong_grid:
        for possible in possible_grid:
            if possible >= strong:
                continue
            t = Thresholds(strong, possible, report.thresholds.prompt, report.thresholds.version)
            m = measure(report.results, t)
            safe = m["false_strong"] == 0 and m["quiet_on_negatives"] == m["negative_queries"]
            rows.append((round(strong, 4), round(possible, 4), m, safe))
    rows.sort(key=lambda r: (not r[3], -r[2]["found"], -r[2]["strong"], r[2]["false_possible"],
                             -r[0], -r[1]))  # fmt: skip
    return rows


def load_manifest(directory: Path) -> list[dict]:
    """``manifest.json``: ``[{"file": "IMG_7834.jpg", "concept": "bridge"}, ...]`` or with
    ``"concepts": [...]`` for an asset that shows several (a two-scene video)."""
    entries = json.loads((directory / "manifest.json").read_text())
    for entry in entries:
        entry["concepts"] = entry.get("concepts") or [entry["concept"]]
    return entries
