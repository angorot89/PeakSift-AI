"""The creator performance profile Auto Edit may use: weak, symbolic hints from insights.

Only when the creator turns it on for a plan. The profile is a snapshot of the creator's current
insight set (``insights.py``) for the server's data source: the insights they have not hidden,
about choices an Auto Edit planner actually makes — caption style, captions on or off, an
opening hook, added visuals, framing. Music is never among them (Auto Edit never picks music on
its own), nor are facts a plan cannot change (length, clip category, recipe).

Each hint is symbolic: a feature, a value, which figure tended higher or lower, the confidence
label and both group sizes — never ids, titles, transcripts or raw metrics — plus fixed product
copy for the review page. The snapshot is stored in the plan's request, so the plan's
fingerprint changes when the profile does and the job always plans with what the creator saw.

How hints are used is decided by the planners and bounded by the recipe: the recipe's intent
and the clip come first; the server validator is unchanged.
"""

import uuid

from sqlalchemy.orm import Session

from app.services.performance.insights import PHRASES, _phrase, ensure_insights

PROFILE_VERSION = "performance_profile_v1"
PLANNER_FEATURES = ("caption_style", "captions", "hook", "visuals", "layout")


def _text(insight) -> str:
    figure = "engaged views" if insight.metric == "engaged_views" else "average % viewed"
    trend = "higher" if insight.direction == "higher" else "lower"
    evidence = "moderate evidence" if insight.confidence == "moderate" else "limited evidence"
    return (
        f"Your shorts {_phrase(insight.feature, insight.value)} have tended to have {trend} "
        f"first-week {figure} ({evidence}, {insight.group_size} vs {insight.comparison_size} "
        "shorts)."
    )


def creator_profile(db: Session, user_id: uuid.UUID, source: str) -> dict | None:
    """The profile snapshot for a plan request, or None when no usable hint exists."""
    insight_set = ensure_insights(db, user_id, source)
    hints = [
        {
            "feature": insight.feature,
            "value": insight.value,
            "metric": insight.metric,
            "direction": insight.direction,
            "confidence": insight.confidence,
            "group_size": insight.group_size,
            "comparison_size": insight.comparison_size,
            "text": _text(insight),
        }
        for insight in insight_set.insights
        if insight.dismissed_at is None and insight.feature in PLANNER_FEATURES
    ]
    if not hints:
        return None
    return {
        "version": PROFILE_VERSION,
        "source": source,
        "sample_size": insight_set.sample_size,
        "hints": hints,
    }


def favours(hints, feature: str, value: str) -> dict | None:
    """The hint saying shorts with ``feature=value`` tended higher (or, for a two-valued
    feature, that the other value tended lower), if any."""
    twin = [v for v in PHRASES.get(feature, {}) if v != value]
    for hint in hints:
        if hint["feature"] != feature:
            continue
        if hint["value"] == value and hint["direction"] == "higher":
            return hint
        if len(PHRASES.get(feature, {})) == 2 and hint["value"] in twin:
            if hint["direction"] == "lower":
                return hint
    return None
