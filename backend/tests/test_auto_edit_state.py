"""Attempt ownership for Auto Edit plans: claiming, stale takeover, fencing of an old worker,
stage-based progress, failure recording, the one-commit result and applying exactly once."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import AutoEditPlan, AutoEditStatus
from app.services.auto_edit import state
from app.services.clip_edit.config import EditConfig
from tests.test_auto_edit_model import CONFIGURATION, make_plan
from tests.test_clip_edit_model import make_clip, make_edit


@pytest.fixture
def settings() -> Settings:
    return Settings(**{**get_settings().model_dump(), "auto_edit_stale_after_seconds": 60})


@pytest.fixture
def plan(db_session: Session) -> AutoEditPlan:
    plan = make_plan(db_session, make_clip(db_session))
    db_session.commit()
    return plan


def take_over(db: Session, plan: AutoEditPlan, task: str = "task-2") -> None:
    """What the retry endpoint does: a new attempt token, committed elsewhere."""
    db.execute(
        AutoEditPlan.__table__.update()
        .where(AutoEditPlan.id == plan.id)
        .values(celery_task_id=task, attempt=AutoEditPlan.attempt + 1)
    )
    db.commit()


def finish(db: Session, plan: AutoEditPlan, task: str | None = "task-1") -> None:
    state.finish(
        plan,
        db,
        configuration=CONFIGURATION.snapshot(),
        configuration_fingerprint=CONFIGURATION.fingerprint(),
        explanations={"layout": "Blur background keeps the whole frame."},
        confidence={"framing": None},
        provider="ollama",
        model="llama3.2:3b",
        fallback_reason=None,
        task_id=task,
    )


def test_claiming_a_queued_plan_starts_it_honestly(db_session, plan, settings):
    assert state.claim(plan, db_session, settings, "task-1")
    db_session.refresh(plan)
    assert plan.status == "analyzing" and plan.progress_percent == state.CLAIMED_PROGRESS
    assert plan.started_at is not None and plan.heartbeat_at is not None


@pytest.mark.parametrize("status", ["ready", "failed"])
def test_finished_or_failed_plans_are_not_claimed_by_a_stray_task(
    db_session, plan, settings, status
):
    if status == "ready":
        finish(db_session, plan)
    else:
        plan.status = "failed"
        db_session.commit()
    assert not state.claim(plan, db_session, settings, "task-1")
    db_session.refresh(plan)
    assert plan.status == status


def test_a_task_of_an_older_attempt_is_ignored(db_session, plan, settings):
    take_over(db_session, plan)
    db_session.refresh(plan)
    assert not state.claim(plan, db_session, settings, "task-1")
    assert plan.status == "queued"


def test_a_live_plan_is_not_run_twice_but_a_stale_one_is_reclaimed(db_session, plan, settings):
    plan.status, plan.heartbeat_at = "planning", datetime.now(UTC)
    db_session.commit()
    assert not state.is_stale(plan, settings)
    assert not state.claim(plan, db_session, settings, "task-1")
    plan.heartbeat_at = datetime.now(UTC) - timedelta(seconds=61)
    db_session.commit()
    assert state.is_stale(plan, settings)
    assert state.claim(plan, db_session, settings, "task-1")
    assert plan.status == "analyzing"


def test_queued_ready_and_applied_plans_are_never_stale(plan, settings):
    old = datetime.now(UTC) - timedelta(days=1)
    for status in ("queued", "ready", "applied", "failed"):
        plan.status, plan.heartbeat_at = status, old
        assert not state.is_stale(plan, settings)


def test_progress_is_stage_based(db_session, plan, settings):
    state.claim(plan, db_session, settings, "task-1")
    seen = []
    for stage in (AutoEditStatus.ANALYZING, AutoEditStatus.PLANNING, AutoEditStatus.VALIDATING):
        state.advance(plan, db_session, stage, "task-1")
        db_session.refresh(plan)
        seen.append((plan.status, plan.progress_percent))
    assert seen == [("analyzing", 15), ("planning", 35), ("validating", 85)]
    finish(db_session, plan)
    db_session.refresh(plan)
    assert (plan.status, plan.progress_percent) == ("ready", 100)
    assert plan.configuration_snapshot == CONFIGURATION.snapshot()
    assert plan.completed_at is not None


def test_an_old_worker_cannot_write_after_a_retry_took_over(db_session, plan, settings):
    state.claim(plan, db_session, settings, "task-1")
    take_over(db_session, plan)
    with pytest.raises(state.PlanSuperseded):
        state.advance(plan, db_session, AutoEditStatus.PLANNING, "task-1")
    with pytest.raises(state.PlanSuperseded):
        finish(db_session, plan, task="task-1")
    state.fail(plan, db_session, "provider_error", "boom", task_id="task-1")  # ignored
    db_session.expire_all()
    stored = db_session.get(AutoEditPlan, plan.id)
    assert stored.status == "analyzing" and stored.celery_task_id == "task-2"
    assert stored.configuration_snapshot is None and stored.error_code is None


def test_the_new_attempt_still_owns_and_finishes(db_session, plan, settings):
    take_over(db_session, plan)
    db_session.refresh(plan)
    assert state.claim(plan, db_session, settings, "task-2")
    finish(db_session, plan, task="task-2")
    db_session.refresh(plan)
    assert plan.status == "ready"


def test_a_deleted_plan_stops_the_worker(db_session, plan, settings):
    state.claim(plan, db_session, settings, "task-1")
    db_session.execute(AutoEditPlan.__table__.delete().where(AutoEditPlan.id == plan.id))
    db_session.commit()
    with pytest.raises(state.PlanSuperseded):
        state.heartbeat(plan, db_session, "task-1")


def test_a_failure_is_recorded_and_bounded(db_session, plan, settings):
    state.claim(plan, db_session, settings, "task-1")
    state.fail(plan, db_session, "x" * 80, "y" * 900, task_id="task-1")
    db_session.refresh(plan)
    assert plan.status == "failed" and len(plan.error_code) == 64
    assert len(plan.error_message) == 500 and plan.completed_at is not None
    assert plan.configuration_snapshot is None


def test_a_retry_after_failure_clears_the_previous_result(db_session, plan, settings):
    state.claim(plan, db_session, settings, "task-1")
    finish(db_session, plan)
    # A later attempt (for example after the result was invalidated) starts clean.
    plan.status = "queued"
    db_session.commit()
    assert state.claim(plan, db_session, settings, "task-1")
    db_session.refresh(plan)
    assert plan.configuration_snapshot is None and plan.explanation_snapshot is None


def test_applying_records_the_edit_once_and_never_changes_the_plan(db_session, plan, settings):
    state.claim(plan, db_session, settings, "task-1")
    finish(db_session, plan)
    edit = make_edit(db_session, plan.clip, CONFIGURATION)
    other = make_edit(
        db_session, plan.clip, EditConfig.create(layout="fit", captions_enabled=False)
    )
    applied = state.mark_applied(plan, db_session, edit.id)
    first_applied_at = applied.applied_at
    assert applied.status == "applied" and applied.clip_edit_id == edit.id
    again = state.mark_applied(plan, db_session, other.id)  # a double click
    assert again.clip_edit_id == edit.id and again.applied_at == first_applied_at
    assert again.configuration_snapshot == CONFIGURATION.snapshot()


@pytest.mark.parametrize("status", ["queued", "planning", "failed"])
def test_only_a_ready_plan_can_be_applied(db_session, plan, status):
    plan.status = status
    db_session.commit()
    edit = make_edit(db_session, plan.clip, CONFIGURATION)
    with pytest.raises(state.PlanNotReady):
        state.mark_applied(plan, db_session, edit.id)
    db_session.refresh(plan)
    assert plan.status == status and plan.clip_edit_id is None
