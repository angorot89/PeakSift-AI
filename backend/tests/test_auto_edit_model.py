"""The Auto Edit domain: plans per clip and source fingerprint, allow-listed statuses and recipes,
results that must be complete once ready, the applied state, and cascades."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ACTIVE_AUTO_EDIT_STATUSES,
    FINISHED_AUTO_EDIT_STATUSES,
    AutoEditPlan,
    AutoEditRecipe,
    AutoEditStatus,
    Clip,
    ClipEdit,
)
from app.services.clip_edit.config import EditConfig
from tests.test_clip_edit_model import make_clip, make_edit

CONFIGURATION = EditConfig.create(
    layout="blur_background", captions_enabled=True, caption_style="bold", caption_position="bottom"
)


def make_plan(db: Session, clip: Clip, **overrides) -> AutoEditPlan:
    fields = {
        "clip": clip,
        "video_id": clip.video_id,
        "recipe": "punchy",
        "recipe_version": "punchy_v1",
        "planner_version": "auto_edit_planner_v1",
        "planner_provider": "ollama",
        "planner_model": "llama3.2:3b",
        "config": {"recipe": "punchy", "generation": 1},
        "source_fingerprint": uuid.uuid4().hex * 2,
        "celery_task_id": "task-1",
    }
    fields.update(overrides)
    plan = AutoEditPlan(**fields)
    db.add(plan)
    db.flush()
    return plan


def ready(**overrides) -> dict:
    return {
        "status": "ready",
        "configuration_snapshot": CONFIGURATION.snapshot(),
        "configuration_fingerprint": CONFIGURATION.fingerprint(),
        "explanation_snapshot": {"layout": "Blur background keeps the whole frame."},
        "confidence_summary": {"framing": None, "word_timing": False},
        **overrides,
    }


def test_a_plan_is_stored_with_honest_defaults(db_session):
    clip = make_clip(db_session)
    plan = make_plan(db_session, clip)
    db_session.commit()
    stored = db_session.get(AutoEditPlan, plan.id)
    assert stored.status == "queued" and stored.progress_percent == 0
    assert stored.attempt == 1 and stored.generation == 1
    assert stored.configuration_snapshot is None and stored.explanation_snapshot is None
    assert stored.clip_edit_id is None and stored.applied_at is None
    assert stored.fallback_reason is None
    assert [p.id for p in clip.auto_edit_plans] == [plan.id]


def test_statuses_and_recipes_are_allow_lists():
    assert {s.value for s in AutoEditStatus} == {
        "queued", "analyzing", "planning", "validating", "ready", "applied", "failed"
    }  # fmt: skip
    assert set(ACTIVE_AUTO_EDIT_STATUSES) == {"queued", "analyzing", "planning", "validating"}
    assert set(FINISHED_AUTO_EDIT_STATUSES) == {"ready", "applied"}
    assert {r.value for r in AutoEditRecipe} == {"clean", "punchy", "story", "minimal"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "done"},
        {"recipe": "viral"},
        {"progress_percent": 101},
        {"progress_percent": -1},
        {"attempt": 0},
        {"generation": 0},
        # ready without its result
        {"status": "ready"},
        ready(configuration_fingerprint=None),
        ready(explanation_snapshot=None),
        # applied needs applied_at, and applied_at means applied
        ready(status="applied"),
        ready(applied_at=datetime.now(UTC)),
    ],
)
def test_plan_constraints(db_session, overrides):
    clip = make_clip(db_session)
    with pytest.raises(IntegrityError):
        make_plan(db_session, clip, **overrides)
    db_session.rollback()


def test_a_ready_and_an_applied_plan_hold_their_result(db_session):
    clip = make_clip(db_session)
    edit = make_edit(db_session, clip, CONFIGURATION)
    make_plan(db_session, clip, **ready())
    applied = make_plan(
        db_session,
        clip,
        **ready(status="applied", applied_at=datetime.now(UTC)),
        clip_edit_id=edit.id,
    )
    db_session.commit()
    assert applied.clip_edit.id == edit.id
    assert applied.configuration_snapshot == CONFIGURATION.snapshot()


def test_one_plan_per_clip_and_source_fingerprint(db_session):
    clip, other = make_clip(db_session), make_clip(db_session)
    fingerprint = "a" * 64
    make_plan(db_session, clip, source_fingerprint=fingerprint)
    make_plan(db_session, other, source_fingerprint=fingerprint)  # another clip: fine
    db_session.commit()
    with pytest.raises(IntegrityError):
        make_plan(db_session, clip, source_fingerprint=fingerprint)
    db_session.rollback()


def test_a_clip_keeps_every_generation(db_session):
    clip = make_clip(db_session)
    first = make_plan(db_session, clip, generation=1)
    second = make_plan(db_session, clip, generation=2)
    db_session.commit()
    assert {p.id for p in clip.auto_edit_plans} == {first.id, second.id}


def test_deleting_a_clip_deletes_its_plans(db_session):
    clip = make_clip(db_session)
    make_plan(db_session, clip)
    db_session.commit()
    db_session.execute(text("DELETE FROM clips WHERE id = :id"), {"id": clip.id})
    db_session.commit()
    db_session.expire_all()
    assert db_session.scalar(select(AutoEditPlan)) is None


def test_deleting_the_applied_edit_keeps_the_plan_and_its_history(db_session):
    clip = make_clip(db_session)
    edit = make_edit(db_session, clip, CONFIGURATION)
    plan = make_plan(
        db_session,
        clip,
        **ready(status="applied", applied_at=datetime.now(UTC)),
        clip_edit_id=edit.id,
    )
    db_session.commit()
    db_session.delete(edit)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(AutoEditPlan, plan.id)
    assert stored.clip_edit_id is None
    assert stored.status == "applied" and stored.applied_at is not None
    assert stored.configuration_snapshot == CONFIGURATION.snapshot()
    assert db_session.get(Clip, clip.id) is not None
    assert db_session.scalar(select(ClipEdit)) is None
