"""Content strategy from the creator's own data (V1.6) — no web trends, no predictions.

``project_strategy`` reads one project and the creator's own history and returns:

- **notes**: short, grounded observations — moments not used yet, which kinds of moment this
  source has compared with what the creator has published recently, and what the creator's own
  patterns (``CreatorInsight``) say about length, style or kind of moment. When the history is too
  small, it says so; it never turns a weak signal into advice to "go viral".
- **moments**: for each ranked, not dismissed moment, whether it was already made into a clip
  or a Short, or published — so ideas are not suggested twice ("Similar to a Short you've already
  published").
- **fallback ideas**: idea cards built only from those moments (title, time, angle from its
  category, why from its reason, a suggested style) — what PeakSift offers itself when the local
  assistant cannot answer.

Every sentence is assembled from stored rows; patterns keep their observational wording.
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CandidateDecision,
    Clip,
    ClipCandidate,
    ClipDetectionRun,
    ClipEdit,
    CreatorInsight,
    InsightSet,
    Project,
    PublishedContent,
    Video,
)

ANGLES = (
    "Lesson",
    "Story",
    "Mistake",
    "Reaction",
    "Surprise",
    "Explanation",
    "Comparison",
    "Opinion",
)
CATEGORY_ANGLE = {
    "insight": "Lesson",
    "explanation": "Explanation",
    "story": "Story",
    "emotional": "Story",
    "conflict": "Story",
    "reaction": "Reaction",
    "humor": "Reaction",
    "hot_take": "Opinion",
}
CATEGORY_STYLE = {
    "humor": "punchy",
    "reaction": "punchy",
    "hot_take": "punchy",
    "story": "story",
    "emotional": "story",
    "conflict": "story",
    "insight": "clean",
    "explanation": "clean",
}
STYLES = ("clean", "punchy", "story", "minimal")
CATEGORY_WORD = {
    "insight": "insight",
    "explanation": "explanation",
    "story": "story",
    "emotional": "emotional",
    "conflict": "conflict",
    "reaction": "reaction",
    "humor": "funny",
    "hot_take": "hot-take",
    "other": "other",
}
RELEVANT_FEATURES = {"length", "clip_category", "recipe", "caption_style"}
RECENT_PUBLISHED = 10
MAX_MOMENTS = 8


@dataclass
class MomentFacts:
    candidate_id: uuid.UUID
    rank: int
    title: str
    category: str
    start: float
    end: float
    rationale: str
    clip_id: uuid.UUID | None = None
    made: bool = False  # a clip or a Short exists from this moment
    published: bool = False  # a Short from this moment was published

    @property
    def note(self) -> str | None:
        if self.published:
            return "Similar to a Short you've already published."
        if self.made:
            return "You've already made a clip from this moment."
        return None


@dataclass
class Strategy:
    notes: list[str] = field(default_factory=list)
    moments: list[MomentFacts] = field(default_factory=list)


def _clock(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60}:{total % 60:02d}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def project_strategy(db: Session, project: Project, source: str) -> Strategy:
    """``source``: "youtube" or "fake" — patterns of the server's current data source only."""
    strategy = Strategy()
    video = db.scalar(
        select(Video)
        .where(Video.project_id == project.id)
        .order_by(Video.created_at.desc(), Video.id.desc())
        .limit(1)
    )
    run = None
    if video is not None:
        run = db.scalar(
            select(ClipDetectionRun)
            .where(ClipDetectionRun.video_id == video.id, ClipDetectionRun.status == "completed")
            .order_by(ClipDetectionRun.created_at.desc())
            .limit(1)
        )
    if run is not None:
        strategy.moments = _moments(db, run)
    unused = [m for m in strategy.moments if not m.made]
    if strategy.moments:
        if unused:
            kinds = sorted({CATEGORY_WORD.get(m.category, m.category) for m in unused})
            strategy.notes.append(
                f"You have {_plural(len(unused), 'moment')} in this video you haven't used yet"
                + (f" ({', '.join(kinds)})." if len(kinds) > 1 else ".")
            )
        else:
            strategy.notes.append("You've already made clips from every ranked moment here.")
    strategy.notes += _history_notes(db, project, unused, source)
    return strategy


def _moments(db: Session, run: ClipDetectionRun) -> list[MomentFacts]:
    rows = db.scalars(
        select(ClipCandidate)
        .where(
            ClipCandidate.run_id == run.id, ClipCandidate.decision != CandidateDecision.DISMISSED
        )
        .order_by(ClipCandidate.rank)
        .limit(MAX_MOMENTS)
    ).all()
    clips = (
        {
            c.candidate_id: c
            for c in db.scalars(select(Clip).where(Clip.candidate_id.in_([r.id for r in rows])))
        }
        if rows
        else {}
    )
    published_clips = (
        set(
            db.scalars(
                select(ClipEdit.clip_id)
                .join(PublishedContent, PublishedContent.edit_id == ClipEdit.id)
                .where(ClipEdit.clip_id.in_([c.id for c in clips.values()]))
            )
        )
        if clips
        else set()
    )
    facts = []
    for row in rows:
        clip = clips.get(row.id)
        facts.append(
            MomentFacts(
                candidate_id=row.id,
                rank=row.rank,
                title=row.title,
                category=row.category,
                start=row.start_time,
                end=row.end_time,
                rationale=row.rationale,
                clip_id=clip.id if clip else None,
                made=clip is not None,
                published=clip is not None and clip.id in published_clips,
            )
        )
    return facts


def _history_notes(db: Session, project: Project, unused: list[MomentFacts], source: str):
    notes: list[str] = []
    recent = db.scalars(
        select(PublishedContent)
        .where(PublishedContent.user_id == project.user_id)
        .order_by(PublishedContent.published_at.desc())
        .limit(RECENT_PUBLISHED)
    ).all()
    if not recent:
        notes.append(
            "You haven't published from PeakSift yet, so there is no performance history to "
            "learn from."
        )
        return notes
    kinds = Counter(((c.provenance or {}).get("candidate") or {}).get("category") for c in recent)
    kinds.pop(None, None)
    if kinds:
        top, count = kinds.most_common(1)[0]
        different = next((m for m in unused if m.category != top), None)
        if count >= 3 and different is not None:
            notes.append(
                f"You've published {count} {CATEGORY_WORD.get(top, top)} Shorts recently. This "
                f"video also has a {CATEGORY_WORD.get(different.category, different.category)} "
                f"moment: “{different.title}”."
            )
    insight_set = db.scalar(
        select(InsightSet).where(InsightSet.user_id == project.user_id, InsightSet.source == source)
    )
    if insight_set is None or insight_set.status == "insufficient":
        from app.services.performance.insights import MIN_SAMPLE

        sample = insight_set.sample_size if insight_set else 0
        notes.append(
            f"Your current sample isn't large enough to recommend a length, style or kind of "
            f"moment yet ({sample} of {MIN_SAMPLE} comparable Shorts)."
        )
        return notes
    relevant = db.scalars(
        select(CreatorInsight)
        .where(
            CreatorInsight.set_id == insight_set.id,
            CreatorInsight.dismissed_at.is_(None),
            CreatorInsight.feature.in_(RELEVANT_FEATURES),
        )
        .order_by(CreatorInsight.rank)
        .limit(2)
    ).all()
    for insight in relevant:
        notes.append(f"{insight.statement} This is an observed pattern, not a prediction.")
    if not relevant:
        notes.append("No reliable pattern about length, style or kind of moment yet.")
    return notes


def fallback_ideas(strategy: Strategy, limit: int = 3) -> list[MomentFacts]:
    """Idea material without the model: unused moments first, best ranked first."""
    unused = [m for m in strategy.moments if not m.made]
    used = [m for m in strategy.moments if m.made]
    return (unused + used)[:limit]


def idea_card(moment: MomentFacts) -> dict:
    return {
        "kind": "idea",
        "title": moment.title[:100],
        "time": f"{_clock(moment.start)}–{_clock(moment.end)}",
        "angle": CATEGORY_ANGLE.get(moment.category),
        "why": (moment.rationale or "")[:200] or None,
        "style": CATEGORY_STYLE.get(moment.category, "clean"),
        "note": moment.note,
    }
