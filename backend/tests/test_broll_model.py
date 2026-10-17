"""The B-roll suggestion domain: analyses per clip and configuration, suggestions with clip-local
intervals, allow-listed statuses, editorial scores, and cascades from clips."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ACTIVE_BROLL_ANALYSIS_STATUSES,
    BrollAnalysis,
    BrollAnalysisStatus,
    BrollSuggestion,
    BrollSuggestionStatus,
    Clip,
)
from tests.test_clip_edit_model import make_clip


def make_analysis(db: Session, clip: Clip, **overrides) -> BrollAnalysis:
    fields = {
        "clip": clip,
        "video_id": clip.video_id,
        "config": {"suggestion_version": "broll_suggest_v1", "generation": 1},
        "config_fingerprint": uuid.uuid4().hex * 2,
        "suggestion_version": "broll_suggest_v1",
        "provider": "ollama",
        "model": "llama3.2:3b",
        "celery_task_id": "task-1",
    }
    fields.update(overrides)
    analysis = BrollAnalysis(**fields)
    db.add(analysis)
    db.flush()
    return analysis


def make_suggestion(db: Session, analysis: BrollAnalysis, index: int = 0, **overrides):
    fields = {
        "analysis": analysis,
        "clip_id": analysis.clip_id,
        "sequence_index": index,
        "start_time": 3.2,
        "end_time": 5.8,
        "query": "Moon / spacecraft footage",
        "reason": "Supports the line about returning humans to the Moon",
        "score": 82,
        "provider": "ollama",
        "provider_version": "llama3.2:3b",
    }
    fields.update(overrides)
    suggestion = BrollSuggestion(**fields)
    db.add(suggestion)
    db.flush()
    return suggestion


def test_an_analysis_and_its_suggestions_are_stored(db_session):
    clip = make_clip(db_session)
    analysis = make_analysis(db_session, clip)
    make_suggestion(db_session, analysis, 1, start_time=10.0, end_time=12.5, query="Rocket launch")
    make_suggestion(db_session, analysis, 0)
    db_session.commit()
    stored = db_session.get(BrollAnalysis, analysis.id)
    assert stored.status == "queued" and stored.attempt == 1 and stored.generation == 1
    assert stored.progress_percent == 0 and stored.fallback_reason is None
    assert [s.query for s in stored.suggestions] == ["Moon / spacecraft footage", "Rocket launch"]
    assert stored.suggestions[0].status == "suggested"
    assert [a.id for a in clip.broll_analyses] == [analysis.id]


def test_statuses_are_allow_lists():
    assert {s.value for s in BrollAnalysisStatus} == {
        "queued", "analyzing", "validating", "completed", "failed"
    }  # fmt: skip
    assert set(ACTIVE_BROLL_ANALYSIS_STATUSES) == {"queued", "analyzing", "validating"}
    assert {s.value for s in BrollSuggestionStatus} == {"suggested", "accepted", "dismissed"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "running"},
        {"progress_percent": 101},
        {"attempt": 0},
        {"generation": 0},
        {"suggestion_count": -1},
        {"rejected_count": -2},
    ],
)
def test_analysis_constraints(db_session, overrides):
    clip = make_clip(db_session)
    with pytest.raises(IntegrityError):
        make_analysis(db_session, clip, **overrides)
    db_session.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_time": -0.5},
        {"end_time": 3.2},  # not after the start
        {"query": ""},
        {"reason": ""},
        {"score": 101},
        {"score": -1},
        {"status": "used"},
        {"sequence_index": -1},
    ],
)
def test_suggestion_constraints(db_session, overrides):
    analysis = make_analysis(db_session, make_clip(db_session))
    with pytest.raises(IntegrityError):
        make_suggestion(db_session, analysis, **overrides)
    db_session.rollback()


def test_a_suggestion_may_have_no_score(db_session):
    analysis = make_analysis(db_session, make_clip(db_session))
    make_suggestion(db_session, analysis, score=None)
    db_session.commit()


def test_one_analysis_per_clip_and_configuration(db_session):
    clip, other = make_clip(db_session), make_clip(db_session)
    fingerprint = "c" * 64
    make_analysis(db_session, clip, config_fingerprint=fingerprint)
    make_analysis(db_session, other, config_fingerprint=fingerprint)  # another clip: fine
    db_session.commit()
    with pytest.raises(IntegrityError):
        make_analysis(db_session, clip, config_fingerprint=fingerprint)
    db_session.rollback()


def test_suggestion_order_is_unique_per_analysis(db_session):
    analysis = make_analysis(db_session, make_clip(db_session))
    make_suggestion(db_session, analysis, 0)
    with pytest.raises(IntegrityError):
        make_suggestion(db_session, analysis, 0)
    db_session.rollback()


def test_deleting_a_clip_deletes_its_analyses_and_suggestions(db_session):
    clip = make_clip(db_session)
    analysis = make_analysis(db_session, clip)
    make_suggestion(db_session, analysis)
    db_session.commit()
    db_session.execute(text("DELETE FROM clips WHERE id = :id"), {"id": clip.id})
    db_session.commit()
    db_session.expire_all()
    assert db_session.scalar(select(BrollAnalysis)) is None
    assert db_session.scalar(select(BrollSuggestion)) is None
