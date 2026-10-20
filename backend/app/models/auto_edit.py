"""Auto Edit: an editable creative plan for a generated clip, made from what PeakSift knows.

An ``AutoEditPlan`` belongs to a ``Clip``. It records one planning run: the creator's recipe
(Clean, Punchy, Story, Minimal — a versioned set of preferences and bounds), the planner that
proposed the choices (a local model, or the deterministic fallback when the model could not
answer, which ``fallback_reason`` then says), and — once ``ready`` — the result:

- ``configuration_snapshot``: an ordinary short-form edit configuration (the same normalized
  snapshot a ``ClipEdit`` stores), so applying a plan needs no special renderer;
- ``explanation_snapshot``: short, creator-facing reasons per section (framing, captions,
  hook, visuals, audio) and notes about anything that was left out. Product explanations
  only — never a prompt or a model's reasoning;
- ``confidence_summary``: what the plan was based on (framing confidence, word timing,
  B-roll method), in plain values.

``(clip_id, source_fingerprint)`` is unique: the fingerprint covers every input that matters
(the clip, its transcript, word timing, framing, B-roll suggestions, the project's assets,
the recipe and its version, the planner, an explicit music choice and the generation), so the
same request with the same inputs returns the existing plan, while changed inputs — or a
deliberate regeneration — make a new one. Old plans are kept.

Applying a plan creates (or reuses) a normal ``ClipEdit``; the plan becomes ``applied`` with a
reference to it and is never changed afterwards. Deleting that edit keeps the plan (the
reference becomes empty); deleting the clip deletes its plans.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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

if TYPE_CHECKING:
    from app.models.clip import Clip
    from app.models.clip_edit import ClipEdit


class AutoEditStatus(StrEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"  # gathering what PeakSift knows about the clip
    PLANNING = "planning"  # the planner is choosing options
    VALIDATING = "validating"  # the server checks every choice against what exists
    READY = "ready"  # a validated plan the creator can review
    APPLIED = "applied"  # turned into a normal edit; never changed again
    FAILED = "failed"


ACTIVE_AUTO_EDIT_STATUSES = (
    AutoEditStatus.QUEUED,
    AutoEditStatus.ANALYZING,
    AutoEditStatus.PLANNING,
    AutoEditStatus.VALIDATING,
)
FINISHED_AUTO_EDIT_STATUSES = (AutoEditStatus.READY, AutoEditStatus.APPLIED)


class AutoEditRecipe(StrEnum):
    """The creator's intent; each is a versioned set of preferences (see auto_edit/recipes)."""

    CLEAN = "clean"
    PUNCHY = "punchy"
    STORY = "story"
    MINIMAL = "minimal"


ERROR_MESSAGE_MAX_LENGTH = 500


class AutoEditPlan(Base):
    __tablename__ = "auto_edit_plans"
    __table_args__ = (
        UniqueConstraint("clip_id", "source_fingerprint", name="uq_auto_edit_plans_source"),
        CheckConstraint(
            "status IN ('queued', 'analyzing', 'planning', 'validating', 'ready', 'applied', "
            "'failed')",
            name="ck_auto_edit_plans_status",
        ),
        CheckConstraint(
            "recipe IN ('clean', 'punchy', 'story', 'minimal')", name="ck_auto_edit_plans_recipe"
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_auto_edit_plans_progress",
        ),
        CheckConstraint("attempt >= 1", name="ck_auto_edit_plans_attempt"),
        CheckConstraint("generation >= 1", name="ck_auto_edit_plans_generation"),
        # A plan the creator can review or has applied always carries its full result.
        CheckConstraint(
            "status NOT IN ('ready', 'applied') OR (configuration_snapshot IS NOT NULL "
            "AND configuration_fingerprint IS NOT NULL AND explanation_snapshot IS NOT NULL)",
            name="ck_auto_edit_plans_result",
        ),
        CheckConstraint(
            "(status = 'applied') = (applied_at IS NOT NULL)", name="ck_auto_edit_plans_applied"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    clip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clips.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(16), default=AutoEditStatus.QUEUED)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    # > 1 marks a deliberate "try another plan"; earlier generations are kept.
    generation: Mapped[int] = mapped_column(Integer, default=1)

    recipe: Mapped[str] = mapped_column(String(16))
    recipe_version: Mapped[str] = mapped_column(String(32))  # e.g. "punchy_v1"
    planner_version: Mapped[str] = mapped_column(String(32))
    # Who chose the options: the configured planner, or the deterministic fallback when the
    # configured one could not answer (``fallback_reason`` then says why).
    planner_provider: Mapped[str] = mapped_column(String(64))
    planner_model: Mapped[str] = mapped_column(String(128))
    fallback_reason: Mapped[str | None] = mapped_column(String(64))

    # The server-side request snapshot the job runs with (recipe, versions, planner, an
    # explicit music choice, generation) — never free user input — and the fingerprint of
    # everything the plan depends on.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_fingerprint: Mapped[str] = mapped_column(String(64))

    # The result (once ready): a normal edit configuration snapshot and its fingerprint, the
    # creator-facing explanations, and what the plan was based on. None is SQL NULL (not JSON
    # null), so the database can insist that a ready plan holds its result.
    configuration_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    configuration_fingerprint: Mapped[str | None] = mapped_column(String(64))
    explanation_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    confidence_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    # The normal edit an applied plan became (empty again if that edit is deleted).
    clip_edit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("clip_edits.id", ondelete="SET NULL"), index=True
    )

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))
    # Attempt-ownership token (fencing), committed before the job is enqueued. Internal.
    celery_task_id: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    clip: Mapped["Clip"] = relationship(back_populates="auto_edit_plans")
    clip_edit: Mapped["ClipEdit | None"] = relationship()

    def __repr__(self) -> str:
        return (
            f"AutoEditPlan(id={self.id!r}, clip_id={self.clip_id!r}, recipe={self.recipe!r}, "
            f"status={self.status!r})"
        )
