"""The B-roll suggestion job: clip-local transcript in, reviewed suggestions out, in one commit;
attempt ownership, claiming rules, the honest fallback and safe failures. A fake provider
stands in for the model (never a real one)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.models import (
    BrollAnalysis,
    BrollSuggestion,
    CaptionTrack,
    CaptionWord,
    Clip,
    TranscriptSegment,
)
from app.services.broll import pipeline
from app.services.broll.config import SUGGESTION_VERSION, BrollConfig
from app.services.broll.contract import (
    BrollProviderConfigurationError,
    BrollProviderUnavailableError,
    BrollResult,
)
from app.services.broll.pipeline import lines_from_words, run_broll_analysis
from app.services.broll.validation import RawSuggestion
from tests.test_clip_edit_model import make_clip

SAID = [  # absolute seconds in the source video; the clip covers 30-50 s
    (28.0, 31.0, "So here is the plan."),
    (31.0, 34.5, "NASA wants to return humans to the Moon."),
    (34.5, 38.0, "The new rocket launched from Florida."),
    (38.0, 42.0, "Honestly it is a huge success for everyone."),
    (42.0, 47.0, "Next they will build a base near the lunar south pole."),
    (55.0, 60.0, "This is outside the clip."),
]


class FakeProvider:
    name, model = "ollama", "llama3.2:3b"

    def __init__(self, suggestions=(), error=None):
        self.suggestions = tuple(suggestions)
        self.error = error
        self.requests = []

    def suggest(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return BrollResult(self.suggestions, self.name, self.model)


GOOD = (
    RawSuggestion(1.2, 4.0, "Moon surface", "Supports the Moon line", 85),
    RawSuggestion(4.6, 7.5, "rocket launch", "The rocket launched", 75),
    RawSuggestion(8.5, 11.0, "success", "vague", 99),  # refused: abstract
    RawSuggestion(12.0, 17.0, "lunar south pole", "The base", 70),
)


@pytest.fixture
def settings() -> Settings:
    return Settings(**{**get_settings().model_dump(), "broll_suggestion_provider": "ollama"})


@pytest.fixture
def clip(db_session) -> Clip:
    clip = make_clip(db_session)
    transcription = clip.video.transcription
    for index, (start, end, text) in enumerate(SAID):
        transcription.segments.append(
            TranscriptSegment(sequence_index=index, start_time=start, end_time=end, text=text)
        )
    db_session.commit()
    return clip


def queued(db, clip: Clip, settings: Settings, *, generation=1, task="task-1") -> BrollAnalysis:
    config = BrollConfig.from_settings(settings, generation=generation)
    analysis = BrollAnalysis(
        clip=clip, video_id=clip.video_id, config=config.snapshot(),
        config_fingerprint=config.fingerprint(), generation=generation,
        suggestion_version=config.suggestion_version, provider=config.provider, model=config.model,
        celery_task_id=task,
    )  # fmt: skip
    db.add(analysis)
    db.commit()
    return analysis


def stored(db, analysis_id) -> list[BrollSuggestion]:
    return list(
        db.scalars(
            select(BrollSuggestion)
            .where(BrollSuggestion.analysis_id == analysis_id)
            .order_by(BrollSuggestion.sequence_index)
        )
    )


def test_suggestions_are_reviewed_and_stored_in_clip_time(db_session, clip, settings):
    analysis = queued(db_session, clip, settings)
    provider = FakeProvider(GOOD)
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=provider, task_id="task-1"
    )
    db_session.refresh(analysis)
    assert analysis.status == "completed" and analysis.progress_percent == 100
    assert (analysis.suggestion_count, analysis.rejected_count) == (2, 2)  # vague + density
    assert analysis.provider == "ollama" and analysis.fallback_reason is None
    assert analysis.clip_duration_seconds == 20.0
    rows = stored(db_session, analysis.id)
    assert [(r.start_time, r.end_time, r.query, r.status) for r in rows] == [
        (1.2, 4.0, "Moon surface", "suggested"),
        (4.6, 7.5, "rocket launch", "suggested"),
    ]
    assert rows[0].provider == "ollama" and rows[0].provider_version == "llama3.2:3b"
    request = provider.requests[0]
    assert request.clip_duration == 20.0 and request.max_suggestions == 2
    assert request.title == "Moment"
    # Transcript lines overlapping the clip, shifted to clip-local time and bounded to it.
    assert [(line.start, line.end, line.text) for line in request.lines] == [
        (0.0, 1.0, "So here is the plan."),
        (1.0, 4.5, "NASA wants to return humans to the Moon."),
        (4.5, 8.0, "The new rocket launched from Florida."),
        (8.0, 12.0, "Honestly it is a huge success for everyone."),
        (12.0, 17.0, "Next they will build a base near the lunar south pole."),
    ]


def test_word_timing_is_preferred_when_the_clip_has_a_caption_track(db_session, clip, settings):
    track = CaptionTrack(
        clip=clip, video_id=clip.video_id, provider="faster_whisper", model="tiny",
        alignment_version="caption_alignment_v1", config={}, config_fingerprint="d" * 64,
        status="completed", completed_at=datetime.now(UTC),
    )  # fmt: skip
    db_session.add(track)
    db_session.flush()
    for index, (start, text) in enumerate(
        [(1.0, "NASA"), (1.4, "wants"), (1.8, "the"), (2.1, "Moon."), (3.5, "Rockets")]
    ):
        db_session.add(
            CaptionWord(
                track=track, sequence_index=index, start_time=start, end_time=start + 0.3, text=text
            )
        )
    db_session.commit()
    analysis = queued(db_session, clip, settings)
    provider = FakeProvider()
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=provider, task_id="task-1"
    )
    assert [(line.start, line.end, line.text) for line in provider.requests[0].lines] == [
        (1.0, 2.4, "NASA wants the Moon."),
        (3.5, 3.8, "Rockets"),
    ]


def test_lines_from_words_break_at_pauses_sentences_and_length():
    words = [
        CaptionWord(sequence_index=i, start_time=t, end_time=t + 0.2, text=w)
        for i, (t, w) in enumerate([(0, "a"), (0.3, "b."), (0.6, "c"), (2.0, "d"), (25.0, "late")])
    ]
    lines = lines_from_words(words, 20.0)
    assert [line.text for line in lines] == ["a b.", "c", "d"]


def test_an_unavailable_model_falls_back_to_keywords_and_says_so(db_session, clip, settings):
    analysis = queued(db_session, clip, settings)
    provider = FakeProvider(error=BrollProviderUnavailableError("down"))
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=provider, task_id="task-1"
    )
    db_session.refresh(analysis)
    assert analysis.status == "completed"
    assert analysis.provider == "keyword" and analysis.fallback_reason == "provider_unavailable"
    queries = [r.query for r in stored(db_session, analysis.id)]
    assert "NASA" in queries and all(
        r.provider == "keyword" for r in stored(db_session, analysis.id)
    )


def test_provider_failures_without_fallback_are_recorded_safely(db_session, clip, settings):
    settings = Settings(**{**settings.model_dump(), "broll_fallback_enabled": False})
    analysis = queued(db_session, clip, settings)
    down = BrollProviderUnavailableError("The local inference server is not reachable")
    provider = FakeProvider(error=down)
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=provider, task_id="task-1"
    )
    db_session.refresh(analysis)
    assert analysis.status == "failed" and analysis.error_code == "provider_unavailable"
    assert stored(db_session, analysis.id) == []


def test_a_configuration_error_never_falls_back(db_session, clip, settings):
    analysis = queued(db_session, clip, settings)
    provider = FakeProvider(error=BrollProviderConfigurationError("No local model is configured"))
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=provider, task_id="task-1"
    )
    db_session.refresh(analysis)
    assert analysis.status == "failed" and analysis.error_code == "provider_configuration"


def test_a_clip_with_nothing_said_completes_with_no_suggestions(db_session, settings):
    clip = make_clip(db_session)  # transcript completed but empty
    analysis = queued(db_session, clip, settings)
    provider = FakeProvider(GOOD)
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=provider, task_id="task-1"
    )
    db_session.refresh(analysis)
    assert analysis.status == "completed" and analysis.suggestion_count == 0
    assert provider.requests == []  # nothing to read: the provider is not called


@pytest.mark.parametrize("problem", ["no_transcript", "clip_not_ready", "bad_config"])
def test_input_problems_are_reported(db_session, clip, settings, problem):
    analysis = queued(db_session, clip, settings)
    if problem == "no_transcript":
        clip.video.transcription.status = "failed"
    elif problem == "clip_not_ready":
        clip.status = "failed"
    else:
        analysis.config = {"suggestion_version": "v0"}
    db_session.commit()
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=FakeProvider(GOOD), task_id="task-1"
    )
    db_session.refresh(analysis)
    expected = {"no_transcript": "transcript_unavailable", "clip_not_ready": "clip_not_ready",
                "bad_config": "config_invalid"}[problem]  # fmt: skip
    assert analysis.status == "failed" and analysis.error_code == expected


def test_unexpected_errors_are_generic(db_session, clip, settings):
    class Broken(FakeProvider):
        def suggest(self, request):
            raise RuntimeError("/private/secret/path exploded")

    analysis = queued(db_session, clip, settings)
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=Broken(), task_id="task-1"
    )
    db_session.refresh(analysis)
    assert analysis.error_code == "internal_error" and "/" not in analysis.error_message


def test_progress_is_stage_based_and_monotonic(monkeypatch, db_session, clip, settings):
    seen = []
    original = pipeline._heartbeat

    def spy(row, db, task_id=None):
        seen.append((row.status, row.progress_percent))
        original(row, db, task_id)

    monkeypatch.setattr(pipeline, "_heartbeat", spy)
    analysis = queued(db_session, clip, settings)
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=FakeProvider(GOOD), task_id="task-1"
    )
    assert seen == [("analyzing", 20), ("validating", 80), ("completed", 100)]


def test_a_completed_analysis_ignores_duplicate_delivery(db_session, clip, settings):
    analysis = queued(db_session, clip, settings)
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=FakeProvider(GOOD), task_id="task-1"
    )
    again = FakeProvider(GOOD)
    run_broll_analysis(analysis.id, db_session, settings=settings, provider=again, task_id="task-1")
    assert again.requests == [] and len(stored(db_session, analysis.id)) == 2


def test_a_failed_analysis_needs_an_explicit_retry(db_session, clip, settings):
    analysis = queued(db_session, clip, settings)
    analysis.status = "failed"
    db_session.commit()
    provider = FakeProvider(GOOD)
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=provider, task_id="task-1"
    )
    assert provider.requests == []


def test_a_live_analysis_is_not_run_twice_but_a_stale_one_is_reclaimed(db_session, clip, settings):
    analysis = queued(db_session, clip, settings)
    analysis.status, analysis.heartbeat_at = "analyzing", datetime.now(UTC)
    db_session.commit()
    provider = FakeProvider(GOOD)
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=provider, task_id="task-1"
    )
    assert provider.requests == []
    analysis.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=settings.broll_stale_after_seconds + 5
    )
    db_session.commit()
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=provider, task_id="task-1"
    )
    db_session.refresh(analysis)
    assert len(provider.requests) == 1 and analysis.status == "completed"


def test_a_task_for_an_older_attempt_is_ignored(db_session, clip, settings):
    analysis = queued(db_session, clip, settings, task="task-2")
    provider = FakeProvider(GOOD)
    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=provider, task_id="task-1"
    )
    assert provider.requests == []


def test_a_stalled_worker_cannot_write_after_a_retry_took_over(db_session, clip, settings):
    analysis = queued(db_session, clip, settings)

    class TakenOver(FakeProvider):
        def suggest(self, request):
            # While the model "thinks", a retry takes the analysis over with a new token.
            db_session.execute(
                BrollAnalysis.__table__.update()
                .where(BrollAnalysis.id == analysis.id)
                .values(celery_task_id="task-2", attempt=2)
            )
            db_session.commit()
            return super().suggest(request)

    run_broll_analysis(
        analysis.id, db_session, settings=settings, provider=TakenOver(GOOD), task_id="task-1"
    )
    db_session.expire_all()
    fresh = db_session.get(BrollAnalysis, analysis.id)
    assert fresh.status == "analyzing" and fresh.suggestion_count is None
    assert stored(db_session, analysis.id) == []


def test_a_deleted_clip_stops_the_job_quietly(db_session, clip, settings):
    analysis = queued(db_session, clip, settings)
    analysis_id = analysis.id

    class Deleting(FakeProvider):
        def suggest(self, request):
            db_session.execute(Clip.__table__.delete().where(Clip.id == clip.id))
            db_session.commit()
            return super().suggest(request)

    assert run_broll_analysis(
        analysis_id, db_session, settings=settings, provider=Deleting(GOOD), task_id="task-1"
    )
    db_session.expire_all()
    assert db_session.get(BrollAnalysis, analysis_id) is None


def test_the_configuration_is_versioned_and_regeneration_is_a_new_fingerprint(settings):
    first = BrollConfig.from_settings(settings)
    assert first.suggestion_version == SUGGESTION_VERSION and first.generation == 1
    assert first.fingerprint() == BrollConfig.from_settings(settings).fingerprint()
    assert BrollConfig.from_settings(settings, generation=2).fingerprint() != first.fingerprint()
    assert BrollConfig.from_snapshot(first.snapshot()) == first
    with pytest.raises(ValueError):
        BrollConfig.from_snapshot({"suggestion_version": SUGGESTION_VERSION})
    keyword = Settings(**{**settings.model_dump(), "broll_suggestion_provider": "keyword"})
    assert BrollConfig.from_settings(keyword).model == "proper_names_v1"


def test_the_worker_task_takes_only_an_id(monkeypatch):
    from app.workers import broll_tasks

    calls = []
    monkeypatch.setattr(broll_tasks, "run_broll_analysis", lambda *a, **k: calls.append((a, k)))
    broll_tasks.suggest_broll_task.apply(args=["not-a-uuid"])
    assert calls == []
    analysis_id = uuid.uuid4()
    broll_tasks.suggest_broll_task.apply(args=[str(analysis_id)], task_id="t-9")
    assert calls[0][0][0] == analysis_id and calls[0][1]["task_id"] == "t-9"
