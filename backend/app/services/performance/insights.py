"""Creator insights: a deterministic engine over one creator's own comparable shorts.

No model, no randomness, no other creators' data. Given the creator's recent shorts whose first
week is complete (``normalization``), of one data source, the engine compares — for each
editing feature recorded in the provenance (made with Auto Edit or by hand, recipe, framing,
captions and their style, an opening hook, added visuals, music, length, clip category) and each
of its values — the shorts **with** that value against the creator's other comparable shorts
**without** it, on two first-week figures: engaged views and average % viewed.

A pattern is reported only when all of these hold:

- at least ``MIN_SAMPLE`` comparable shorts overall, and ``MIN_GROUP`` on **each** side;
- it is **unlikely to be chance**: a two-sided Mann–Whitney U test (rank-based, so one huge
  short cannot carry it; exact for small samples) passes at ``ALPHA`` after a Holm–Bonferroni
  correction across **every comparison tested** for the creator — testing many features at once
  would otherwise find "patterns" in pure noise (measured: ``scripts/insights_benchmark.py``);
- one median is at least ``MIN_RATIO`` (1.2×) the other — measured symmetrically, so "with X
  higher" and "without X lower" are the same pattern with the same size;
- it is **consistent**: at least ``MIN_CONSISTENCY`` of the group lies on the same side of the
  other shorts' median (not one outlier pulling a median);
- it is **stable**: leaving out any single short, on either side, keeps the difference.

At most ``MAX_INSIGHTS`` are kept (largest differences first). Confidence is ``limited``, or
``moderate`` with ``MODERATE_FROM`` shorts on each side and a corrected p-value under
``MODERATE_P`` — never higher: these are the creator's own uploads, and other things changed too.

Statements are fixed templates filled with the numbers: "In your recent uploads, shorts … have
tended to …". They describe what was observed — never a cause, a promise or a prediction.
"""

import hashlib
import json
import logging
import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CreatorInsight, InsightSet, InsightSetStatus
from app.services.performance import normalization, summary

logger = logging.getLogger(__name__)

ENGINE_VERSION = "insights_v1"
MIN_SAMPLE = 10
MIN_GROUP = 5
MIN_RATIO = 1.2
MIN_EFFECT = math.log(MIN_RATIO)
MIN_CONSISTENCY = 0.6
ALPHA = 0.05  # family-wise, after the Holm–Bonferroni correction
MODERATE_FROM = 8
MODERATE_P = 0.01
EXACT_MAX_PAIRS = 900  # exact Mann–Whitney distribution up to n1·n2 pairs (no ties)
MAX_INSIGHTS = 5
RECENT_LIMIT = 50
WINDOW = normalization.PRIMARY_WINDOW
METRICS = ("engaged_views", "average_view_percentage")

# feature → value → how the statement names the shorts that have it.
PHRASES: dict[str, dict[str, str]] = {
    "made_with": {"auto_edit": "made with Auto Edit", "editor": "edited by hand in the editor"},
    "captions": {"on": "with captions", "off": "without captions"},
    "hook": {"with_hook": "with an opening hook", "no_hook": "without an opening hook"},
    "visuals": {"with_visuals": "with added B-roll or overlays",
                "no_visuals": "without added visuals"},
    "music": {"with_music": "with background music", "no_music": "without background music"},
    "length": {"under_20s": "under 20 seconds long", "20_to_40s": "20–40 seconds long",
               "over_40s": "over 40 seconds long"},
}  # fmt: skip


def _phrase(feature: str, value: str) -> str:
    if feature in PHRASES:
        return PHRASES[feature][value]
    readable = value.replace("_", " ")
    return {
        "recipe": f"made with the “{readable}” recipe",
        "layout": f"framed with “{readable}”",
        "caption_style": f"with “{readable}” captions",
        "clip_category": f"from “{readable}” clip candidates",
    }[feature]


def features(provenance: dict, duration_seconds: float | None) -> dict[str, str]:
    """The categorical editing features of one short (unknown ones are left out)."""
    p = provenance or {}
    auto = p.get("auto_edit") or {}
    captions = p.get("captions") or {}
    hook = p.get("hook") or {}
    visuals = p.get("visuals") or {}
    audio = p.get("audio") or {}
    candidate = p.get("candidate") or {}
    found: dict[str, str] = {}
    if "used" in auto:
        found["made_with"] = "auto_edit" if auto["used"] else "editor"
        if auto["used"] and p.get("recipe") and p["recipe"] != "manual":
            found["recipe"] = str(p["recipe"])
    if p.get("layout"):
        found["layout"] = str(p["layout"])
    if "enabled" in captions:
        found["captions"] = "on" if captions["enabled"] else "off"
        if captions["enabled"] and captions.get("preset"):
            found["caption_style"] = str(captions["preset"])
    if "enabled" in hook:
        found["hook"] = "with_hook" if hook["enabled"] else "no_hook"
    if "count" in visuals:
        found["visuals"] = "with_visuals" if visuals["count"] else "no_visuals"
    if "music" in audio:
        found["music"] = "with_music" if audio["music"] else "no_music"
    duration = duration_seconds if duration_seconds is not None else p.get("duration_seconds")
    if duration is not None:
        found["length"] = (
            "under_20s" if duration < 20 else "20_to_40s" if duration <= 40 else "over_40s"
        )
    if candidate.get("category"):
        found["clip_category"] = str(candidate["category"])
    return {k: v[:64] for k, v in found.items()}


@dataclass(frozen=True)
class Short:
    content_id: uuid.UUID
    published_at: datetime
    features: dict[str, str]
    figures: dict[str, float]  # metric → first-week value (only known ones)


@dataclass
class Finding:
    feature: str
    value: str
    metric: str
    direction: str
    group: list[Short]
    comparison: list[Short]
    group_median: float
    comparison_median: float
    ratio: float | None
    consistency: float
    effect: float
    statement: str = ""
    confidence: str = "limited"
    p_adjusted: float = 1.0
    rank: int = 0
    evidence: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.feature}={self.value}|{self.metric}|{WINDOW}"


def _effect(group_median: float, comparison_median: float) -> float:
    """Log ratio of the medians (symmetric: ×2 and ×½ are the same size); a zero median on
    either side counts as no measurable effect."""
    if comparison_median <= 0 or group_median <= 0:
        return 0.0
    return math.log(group_median / comparison_median)


def _holds(group_median: float, comparison_median: float, higher: bool) -> bool:
    effect = _effect(group_median, comparison_median)
    return abs(effect) >= MIN_EFFECT and (effect > 0) == higher


def _fmt(metric: str, value: float) -> str:
    if metric == "average_view_percentage":
        return f"{value:.0f}%"
    return f"{value:,.0f}"


def _statement(finding: Finding) -> str:
    who = _phrase(finding.feature, finding.value)
    if finding.metric == "engaged_views":
        what = "more" if finding.direction == "higher" else "fewer"
        tendency = f"have tended to get {what} engaged views in their first week"
    else:
        what = "larger" if finding.direction == "higher" else "smaller"
        tendency = (
            f"have tended to be watched for a {what} share of their length in their first week"
        )
    return (
        f"In your recent uploads, shorts {who} {tendency}: median "
        f"{_fmt(finding.metric, finding.group_median)} vs "
        f"{_fmt(finding.metric, finding.comparison_median)} for your other shorts "
        f"({len(finding.group)} vs {len(finding.comparison)} shorts)."
    )


# --- the significance test ---------------------------------------------------------------------


@cache
def _u_counts(n1: int, n2: int) -> tuple[int, ...]:
    """How many orderings of n1 + n2 distinct values give each U statistic (0 … n1·n2)."""
    if n1 == 0 or n2 == 0:
        return (1,)
    counts = [0] * (n1 * n2 + 1)
    # The largest value belongs to sample 1 (adding n2 to U) or to sample 2 (adding nothing).
    for u, ways in enumerate(_u_counts(n1 - 1, n2)):
        counts[u + n2] += ways
    for u, ways in enumerate(_u_counts(n1, n2 - 1)):
        counts[u] += ways
    return tuple(counts)


def mann_whitney_p(a: list[float], b: list[float]) -> float:
    """Two-sided p-value of the Mann–Whitney U test: exact without ties for small samples,
    otherwise the normal approximation with tie and continuity corrections."""
    n1, n2 = len(a), len(b)
    pooled = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks: list[float] = [0.0] * len(pooled)
    ties = 0.0
    i = 0
    while i < len(pooled):
        j = i
        while j + 1 < len(pooled) and pooled[j + 1][0] == pooled[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        size = j - i + 1
        ties += size**3 - size
        i = j + 1
    rank_sum = sum(r for r, (_, group) in zip(ranks, pooled, strict=True) if group == 0)
    u = rank_sum - n1 * (n1 + 1) / 2
    if ties == 0 and n1 * n2 <= EXACT_MAX_PAIRS:
        counts = _u_counts(n1, n2)
        total = sum(counts)
        extreme = min(u, n1 * n2 - u)
        tail = sum(counts[: int(extreme) + 1]) / total
        return min(1.0, 2 * tail)
    mean = n1 * n2 / 2
    n = n1 + n2
    variance = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1)))
    if variance <= 0:
        return 1.0
    z = (abs(u - mean) - 0.5) / math.sqrt(variance)
    return min(1.0, math.erfc(max(z, 0.0) / math.sqrt(2)))


def holm(p_values: list[float], alpha: float = ALPHA) -> list[float | None]:
    """Holm–Bonferroni: the adjusted p-value of each test that passes, None for the others."""
    order = sorted(range(len(p_values)), key=lambda i: p_values[i])
    adjusted: list[float | None] = [None] * len(p_values)
    running = 0.0
    for rank, index in enumerate(order):
        value = min(1.0, p_values[index] * (len(p_values) - rank))
        running = max(running, value)
        if running > alpha:
            break
        adjusted[index] = running
    return adjusted


def _sides(feature: str, value: str, metric: str, shorts: list[Short]):
    known = [s for s in shorts if metric in s.figures and feature in s.features]
    group = [s for s in known if s.features[feature] == value]
    comparison = [s for s in known if s.features[feature] != value]
    if len(group) < MIN_GROUP or len(comparison) < MIN_GROUP:
        return None
    return group, comparison


def _examine(feature: str, value: str, metric: str, shorts: list[Short]) -> Finding | None:
    sides = _sides(feature, value, metric, shorts)
    if sides is None:
        return None
    group, comparison = sides
    group_values = [s.figures[metric] for s in group]
    comparison_median = statistics.median(s.figures[metric] for s in comparison)
    group_median = statistics.median(group_values)
    effect = _effect(group_median, comparison_median)
    if abs(effect) < MIN_EFFECT:
        return None
    higher = effect > 0
    on_side = sum((v > comparison_median) if higher else (v < comparison_median)
                  for v in group_values)  # fmt: skip
    consistency = on_side / len(group_values)
    if consistency < MIN_CONSISTENCY:
        return None
    # Stable: leaving out any single short, on either side, must keep the difference.
    comparison_values = [s.figures[metric] for s in comparison]
    for index in range(len(group_values)):
        rest = group_values[:index] + group_values[index + 1 :]
        if not _holds(statistics.median(rest), comparison_median, higher):
            return None
    for index in range(len(comparison_values)):
        rest = comparison_values[:index] + comparison_values[index + 1 :]
        if not _holds(group_median, statistics.median(rest), higher):
            return None
    return Finding(
        feature=feature, value=value, metric=metric, direction="higher" if higher else "lower",
        group=group, comparison=comparison, group_median=float(group_median),
        comparison_median=float(comparison_median),
        ratio=round(group_median / comparison_median, 2) if comparison_median else None,
        consistency=round(consistency, 2), effect=effect,
    )  # fmt: skip


def _tests(shorts: list[Short]) -> list[tuple[str, str, str]]:
    """Every comparison the creator's data allows: each feature value against the rest, on
    each figure, with enough shorts on both sides. A two-valued feature is one comparison (its
    two phrasings are the same test), named by its first-listed value."""
    values = sorted({(f, v) for s in shorts for f, v in s.features.items()})
    tests = []
    for feature, value in values:
        two_valued = list(PHRASES.get(feature, {}))
        if len(two_valued) == 2 and value != two_valued[0]:
            if (feature, two_valued[0]) in values:
                continue
        for metric in METRICS:
            if _sides(feature, value, metric, shorts) is not None:
                tests.append((feature, value, metric))
    return tests


def find_patterns(shorts: list[Short]) -> list[Finding]:
    """The comparisons that pass the corrected significance test and every other check,
    largest differences first."""
    if len(shorts) < MIN_SAMPLE:
        return []
    tests = _tests(shorts)
    p_values = []
    for feature, value, metric in tests:
        group, comparison = _sides(feature, value, metric, shorts)
        p_values.append(mann_whitney_p([s.figures[metric] for s in group],
                                       [s.figures[metric] for s in comparison]))  # fmt: skip
    candidates: list[Finding] = []
    for (feature, value, metric), adjusted in zip(tests, holm(p_values), strict=True):
        if adjusted is None:
            continue
        found = _examine(feature, value, metric, shorts)
        if found is not None:
            found.p_adjusted = adjusted
            candidates.append(found)
    candidates.sort(key=lambda f: (-round(abs(f.effect), 9), f.feature, f.value, f.metric))
    kept = candidates[:MAX_INSIGHTS]
    for rank, finding in enumerate(kept, start=1):
        finding.rank = rank
        smaller = min(len(finding.group), len(finding.comparison))
        strong = smaller >= MODERATE_FROM and finding.p_adjusted < MODERATE_P
        finding.confidence = "moderate" if strong else "limited"
        finding.statement = _statement(finding)
        finding.evidence = {
            "group": [str(s.content_id) for s in finding.group],
            "comparison": [str(s.content_id) for s in finding.comparison],
            "tests": len(tests),
            "p_adjusted": round(finding.p_adjusted, 4),
        }
    return kept


# --- the creator's set -------------------------------------------------------------------------


def comparable_shorts(db: Session, user_id: uuid.UUID, source: str) -> list[Short]:
    """The creator's most recent shorts of ``source`` with a complete first week."""
    contents = summary.user_contents(db, user_id)
    counters = summary.latest_counters(db, [c.id for c in contents])
    sources = {content_id: c.source for content_id, c in counters.items()}
    compared = normalization.compare(db, contents, sources, source)
    shorts = []
    for content in contents:
        week = compared.windows.get(content.id, {}).get(WINDOW)
        if sources.get(content.id) != source or week is None or not week.complete:
            continue
        figures = {m: float(getattr(week, m)) for m in METRICS if getattr(week, m) is not None}
        shorts.append(
            Short(content.id, content.published_at,
                  features(content.provenance, content.duration_seconds), figures)
        )  # fmt: skip
    shorts.sort(key=lambda s: s.published_at, reverse=True)
    return shorts[:RECENT_LIMIT]


def fingerprint(shorts: list[Short]) -> str:
    payload = [ENGINE_VERSION] + sorted(
        [str(s.content_id), s.features, {k: round(v, 4) for k, v in s.figures.items()}]
        for s in shorts
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def now() -> datetime:
    return datetime.now(UTC)


def current_set(db: Session, user_id: uuid.UUID, source: str) -> InsightSet | None:
    return db.scalar(
        select(InsightSet).where(InsightSet.user_id == user_id, InsightSet.source == source)
    )


def ensure_insights(
    db: Session, user_id: uuid.UUID, source: str, *, at: datetime | None = None
) -> InsightSet:
    """The creator's insight set for ``source``, recomputed only when its inputs changed.
    Dismissed insights stay dismissed (by key) across recomputations."""
    shorts = comparable_shorts(db, user_id, source)
    digest = fingerprint(shorts)
    existing = current_set(db, user_id, source)
    if existing is not None and existing.input_fingerprint == digest:
        return existing
    dismissed = (
        {i.key: i.dismissed_at for i in existing.insights if i.dismissed_at} if existing else {}
    )
    findings = find_patterns(shorts)
    insight_set = existing or InsightSet(user_id=user_id, source=source)
    insight_set.engine_version = ENGINE_VERSION
    insight_set.input_fingerprint = digest
    insight_set.status = (
        InsightSetStatus.READY if len(shorts) >= MIN_SAMPLE else InsightSetStatus.INSUFFICIENT
    )
    insight_set.sample_size = len(shorts)
    insight_set.computed_at = at or now()
    insight_set.insights.clear()
    db.add(insight_set)
    db.flush()  # the old rows go before new ones with the same keys arrive
    for finding in findings:
        insight_set.insights.append(
            CreatorInsight(
                key=finding.key, rank=finding.rank, feature=finding.feature,
                value=finding.value, metric=finding.metric, window=WINDOW,
                direction=finding.direction, group_size=len(finding.group),
                comparison_size=len(finding.comparison), group_median=finding.group_median,
                comparison_median=finding.comparison_median, ratio=finding.ratio,
                consistency=finding.consistency, confidence=finding.confidence,
                statement=finding.statement, evidence=finding.evidence,
                dismissed_at=dismissed.get(finding.key),
            )
        )  # fmt: skip
    try:
        db.commit()
    except IntegrityError:  # computed concurrently for the same creator: use that one
        db.rollback()
        return current_set(db, user_id, source)
    logger.info("Insights for a creator: %d from %d shorts", len(findings), len(shorts))
    return insight_set


def owned_insight(db: Session, insight_id: uuid.UUID, user_id: uuid.UUID) -> CreatorInsight | None:
    return db.scalar(
        select(CreatorInsight)
        .join(InsightSet, InsightSet.id == CreatorInsight.set_id)
        .where(CreatorInsight.id == insight_id, InsightSet.user_id == user_id)
    )
