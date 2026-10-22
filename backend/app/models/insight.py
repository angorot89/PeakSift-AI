"""Creator insights: observed patterns among one creator's own published shorts.

An ``InsightSet`` is the latest computation for one creator and one data source (``youtube``,
or ``fake`` for simulated data — never mixed): which engine version produced it, a fingerprint
of its inputs (so unchanged data is never recomputed), how many shorts were comparable, and
whether there was enough to say anything (``insufficient``: "No reliable pattern yet").

A ``CreatorInsight`` is one pattern the deterministic engine found: for one editing feature and
value (e.g. captions ``punch`` style) and one figure on one window (first-week engaged views),
the medians of the shorts with it and of the creator's other comparable shorts, both group
sizes, the ratio, a consistency share and a confidence label (``limited`` / ``moderate`` — never
more). ``statement`` is fixed product copy filled from those numbers: observational ("has tended
to"), never causal, never a prediction. ``evidence`` lists only the creator's own short ids.

Recomputing replaces a set's insights; a creator's dismissal is kept by insight key. Insights
belong to the creator: deleting the user deletes them; nothing here is ever shared across users.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class InsightSetStatus(StrEnum):
    READY = "ready"  # computed; may still hold no insight (no pattern passed the checks)
    INSUFFICIENT = "insufficient"  # too few comparable shorts to look for patterns


class InsightConfidence(StrEnum):
    LIMITED = "limited"
    MODERATE = "moderate"


class InsightSet(Base):
    __tablename__ = "insight_sets"
    __table_args__ = (
        UniqueConstraint("user_id", "source", name="uq_insight_sets_user_source"),
        CheckConstraint("source IN ('youtube', 'fake')", name="ck_insight_sets_source"),
        CheckConstraint("status IN ('ready', 'insufficient')", name="ck_insight_sets_status"),
        CheckConstraint("sample_size >= 0", name="ck_insight_sets_sample"),
        CheckConstraint("length(input_fingerprint) = 64", name="ck_insight_sets_fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(16))
    engine_version: Mapped[str] = mapped_column(String(32))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    sample_size: Mapped[int] = mapped_column(Integer)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    insights: Mapped[list["CreatorInsight"]] = relationship(
        back_populates="insight_set", cascade="all, delete-orphan", passive_deletes=True,
        order_by="CreatorInsight.rank",
    )  # fmt: skip

    def __repr__(self) -> str:
        return f"InsightSet(id={self.id!r}, status={self.status!r})"


class CreatorInsight(Base):
    __tablename__ = "creator_insights"
    __table_args__ = (
        UniqueConstraint("set_id", "key", name="uq_creator_insights_key"),
        CheckConstraint(
            "confidence IN ('limited', 'moderate')", name="ck_creator_insights_confidence"
        ),
        CheckConstraint("direction IN ('higher', 'lower')", name="ck_creator_insights_direction"),
        CheckConstraint(
            "group_size >= 1 AND comparison_size >= 1", name="ck_creator_insights_sizes"
        ),
        CheckConstraint(
            "consistency >= 0 AND consistency <= 1", name="ck_creator_insights_consistency"
        ),
        CheckConstraint("rank >= 1", name="ck_creator_insights_rank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("insight_sets.id", ondelete="CASCADE"), index=True
    )
    # "feature=value|metric|window": stable across recomputations (dismissals follow it).
    key: Mapped[str] = mapped_column(String(160))
    rank: Mapped[int] = mapped_column(Integer)
    feature: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(64))
    metric: Mapped[str] = mapped_column(String(32))
    window: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(8))
    group_size: Mapped[int] = mapped_column(Integer)
    comparison_size: Mapped[int] = mapped_column(Integer)
    group_median: Mapped[float] = mapped_column(Float)
    comparison_median: Mapped[float] = mapped_column(Float)
    ratio: Mapped[float | None] = mapped_column(Float)
    consistency: Mapped[float] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(16))
    statement: Mapped[str] = mapped_column(String(500))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    insight_set: Mapped[InsightSet] = relationship(back_populates="insights")

    def __repr__(self) -> str:
        return f"CreatorInsight(id={self.id!r}, key={self.key!r})"
