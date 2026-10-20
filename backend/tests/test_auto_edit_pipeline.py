"""The Auto Edit planning job on real database rows and local storage: it consumes completed
analyses (never starts them), gives the planner handles not ids, validates on the server,
falls back honestly, writes the result in one commit, and stays fenced and idempotent."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    AudioAsset,
    AutoEditPlan,
    BrollAnalysis,
    BrollSuggestion,
    Clip,
    TranscriptSegment,
    VisualAsset,
)
from app.services.auto_edit.config import AutoEditRequest
from app.services.auto_edit.contract import (
    PlannerResult,
    PlannerUnavailableError,
    parse_proposal,
)
from app.services.auto_edit.fingerprint import source_fingerprint
from app.services.auto_edit.pipeline import run_auto_edit_plan
from app.services.auto_edit.sources import gather
from app.services.broll.config import BrollConfig
from app.services.caption_timing.config import CaptionTimingConfig
from app.services.reframe.config import ReframeConfig
from app.services.storage import LocalStorageProvider, StorageUnavailable, generate_key
from app.workers.auto_edit_tasks import plan_auto_edit_task
from tests.test_auto_edit_contract import GOOD, UUID
from tests.test_caption_track_model import make_track
from tests.test_clip_edit_model import make_clip
from tests.test_reframe_model import make_analysis as make_reframe

SAID = [
    (30.0, 34.0, "Then she added the second weight and the entire thing folded."),
    (34.0, 40.2, "Here is the lesson I learned about every bridge."),
    (40.2, 42.7, "A structure is only as strong as its weakest joint."),
    (42.7, 50.0, "We had reinforced the middle and forgotten the corners."),
]


def pipeline_settings() -> Settings:
    return Settings(**{**get_settings().model_dump(), "auto_edit_planner_provider": "ollama",
                       "auto_edit_fallback_enabled": True})  # fmt: skip


@pytest.fixture
def settings() -> Settings:
    return pipeline_settings()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "media")


def stored(storage: LocalStorageProvider, tmp_path: Path, extension: str, category: str) -> str:
    key = generate_key(extension, category)
    source = tmp_path / f"{uuid.uuid4().hex}.{extension}"
    source.write_bytes(b"x")
    storage.put_file(source, key)
    return key


@pytest.fixture
def world(db_session: Session, settings, storage, tmp_path):
    return build_world(db_session, settings, storage, tmp_path)


def build_world(db_session: Session, settings, storage, tmp_path):
    """A clip with transcript, word timing, framing, B-roll suggestions, assets and audio."""
    clip = make_clip(db_session)
    clip.storage_key = stored(storage, tmp_path, "mp4", "clips")
    clip.width, clip.height = 1280, 720
    transcription = clip.video.transcription
    for index, (start, end, text) in enumerate(SAID):
        transcription.segments.append(
            TranscriptSegment(sequence_index=index, start_time=start, end_time=end, text=text)
        )
    db_session.commit()
    make_track(db_session, clip, CaptionTimingConfig.from_settings(settings, language_hint=None),
               status="completed")  # fmt: skip
    make_reframe(db_session, clip, ReframeConfig.from_settings(settings), status="completed",
                 confidence_level="high", overall_confidence=0.9)  # fmt: skip
    config = BrollConfig.from_settings(settings)
    analysis = BrollAnalysis(
        clip=clip, video_id=clip.video_id, config=config.snapshot(),
        config_fingerprint=config.fingerprint(), suggestion_version=config.suggestion_version,
        provider="ollama", model=config.model, status="completed", suggestion_count=2,
    )  # fmt: skip
    db_session.add(analysis)
    db_session.flush()
    joint = BrollSuggestion(analysis=analysis, clip_id=clip.id, sequence_index=0, start_time=10.2,
                            end_time=12.7, query="bridge joint", reason="Shows the weak joint",
                            provider="ollama", provider_version="m")  # fmt: skip
    vague = BrollSuggestion(
        analysis=analysis, clip_id=clip.id, sequence_index=1, start_time=3.0, end_time=5.0,
        query="lesson board", reason="The lesson", provider="ollama", provider_version="m",
        status="dismissed",
    )  # fmt: skip
    db_session.add_all([joint, vague])
    project_id = clip.video.project_id
    bridge = VisualAsset(
        project_id=project_id, kind="image", display_name="toothpick-bridge.jpg",
        storage_key=stored(storage, tmp_path, "jpg", "visuals"), content_type="image/jpeg",
        file_size=1, sha256="a" * 64, width=1600, height=900, codec="jpeg", container="jpeg",
        description="Bridge model", tags=["bridge", "joint"],
    )  # fmt: skip
    music = AudioAsset(
        project_id=project_id, kind="music", display_name="calm.mp3",
        storage_key=stored(storage, tmp_path, "mp3", "audio"), content_type="audio/mpeg",
        file_size=1, sha256="b" * 64, container="mp3", codec="mp3", duration_seconds=8.0,
        sample_rate=44100, channels=2, waveform_peaks=[],
    )  # fmt: skip
    whoosh = AudioAsset(
        project_id=project_id, kind="sfx", display_name="whoosh.wav",
        storage_key=stored(storage, tmp_path, "wav", "audio"), content_type="audio/wav",
        file_size=1, sha256="c" * 64, container="wav", codec="pcm_s16le", duration_seconds=0.8,
        sample_rate=44100, channels=2, waveform_peaks=[],
    )  # fmt: skip
    db_session.add_all([bridge, music, whoosh])
    db_session.commit()
    return {"clip": clip, "joint": joint, "bridge": bridge, "music": music, "whoosh": whoosh}


def make_plan(db, clip, settings, storage, *, recipe="punchy", music=None, task="task-1"):
    request = AutoEditRequest.from_settings(settings, recipe=recipe, music_asset_id=music)
    sources = gather(clip, db, settings, storage, request).sources
    row = AutoEditPlan(
        clip=clip, video_id=clip.video_id, recipe=request.recipe,
        recipe_version=request.recipe_version, planner_version=request.planner_version,
        planner_provider=request.provider, planner_model=request.model,
        config=request.snapshot(),
        source_fingerprint=source_fingerprint(sources, request.snapshot()),
        celery_task_id=task,
    )  # fmt: skip
    db.add(row)
    db.commit()
    return row


class Recording:
    name, model = "ollama", "llama3.2:3b"

    def __init__(self, data=GOOD, error=None, during=None):
        self.data, self.error, self.during = data, error, during
        self.contexts = []

    def plan(self, context):
        self.contexts.append(context)
        if self.during:
            self.during()
        if self.error:
            raise self.error
        return PlannerResult(parse_proposal(self.data, provider="test"), self.name, self.model)


def run(db, row, settings, storage, planner, task="task-1"):
    run_auto_edit_plan(row.id, db, settings=settings, planner=planner, storage=storage,
                       task_id=task)  # fmt: skip
    db.expire_all()
    return db.get(AutoEditPlan, row.id)


def test_a_plan_becomes_ready_with_a_normal_edit_configuration(
    db_session, world, settings, storage
):
    row = make_plan(db_session, world["clip"], settings, storage, music=str(world["music"].id))
    audio = {"use_music": True, "music_level": "low", "ducking": "medium",
             "transition_sounds": True}  # fmt: skip
    planner = Recording({**GOOD, "audio": audio})
    plan = run(db_session, row, settings, storage, planner)
    assert plan.status == "ready" and plan.progress_percent == 100
    assert plan.planner_provider == "ollama" and plan.fallback_reason is None
    snapshot = plan.configuration_snapshot
    assert snapshot["layout"] == "smart_reframe"
    assert snapshot["captions"]["timing"] == "aligned_word"
    (element,) = snapshot["visuals"]["elements"]
    assert element["asset_id"] == str(world["bridge"].id)
    assert snapshot["audio"]["music"]["asset_id"] == str(world["music"].id)
    assert snapshot["audio"]["music"]["gain_db"] == -20.0
    assert snapshot["audio"]["sfx"][0]["asset_id"] == str(world["whoosh"].id)
    assert plan.explanation_snapshot["used_suggestions"] == [str(world["joint"].id)]
    assert plan.confidence_summary["planner"] == "local_ai"
    assert plan.confidence_summary["framing"] == "high" and plan.confidence_summary["word_timing"]
    assert plan.configuration_fingerprint and plan.completed_at is not None


def test_the_planner_sees_handles_and_completed_inputs_only(db_session, world, settings, storage):
    row = make_plan(db_session, world["clip"], settings, storage)
    planner = Recording()
    run(db_session, row, settings, storage, planner)
    (context,) = planner.contexts
    view = json.dumps(context.planner_view())
    assert not UUID.search(view)
    assert [option.query for option in context.broll] == ["bridge joint"]  # dismissed: never
    assert context.broll[0].strong_matches == ("visual_asset_1",)
    assert context.music is None  # no explicit choice → no music offered
    assert [s.name for s in context.sound_effects] == ["whoosh.wav"]
    assert context.capabilities.smart_reframe and context.capabilities.word_timing


def test_assets_missing_from_storage_are_never_offered(db_session, world, settings, storage):
    storage.delete(world["bridge"].storage_key)
    row = make_plan(db_session, world["clip"], settings, storage)
    planner = Recording()
    plan = run(db_session, row, settings, storage, planner)
    assert planner.contexts[0].visual_assets == ()
    assert plan.status == "ready" and "visuals" not in plan.configuration_snapshot


def test_a_chosen_track_that_vanished_is_explained(db_session, world, settings, storage):
    row = make_plan(db_session, world["clip"], settings, storage, music=str(world["music"].id))
    storage.delete(world["music"].storage_key)
    plan = run(db_session, row, settings, storage, Recording())
    assert plan.explanation_snapshot["notes"][0].startswith("The music you chose")


def test_the_rules_stand_in_when_the_model_cannot_answer(db_session, world, settings, storage):
    row = make_plan(db_session, world["clip"], settings, storage)
    plan = run(db_session, row, settings, storage,
               Recording(error=PlannerUnavailableError("down")))  # fmt: skip
    assert plan.status == "ready" and plan.planner_provider == "fallback"
    assert plan.fallback_reason == "planner_unavailable"
    assert plan.confidence_summary["planner"] == "rules"
    assert plan.configuration_snapshot["visuals"]["elements"][0]["asset_id"] == str(
        world["bridge"].id
    )


def test_without_the_fallback_a_model_failure_fails_the_plan(db_session, world, settings, storage):
    settings = Settings(**{**settings.model_dump(), "auto_edit_fallback_enabled": False})
    row = make_plan(db_session, world["clip"], settings, storage)
    plan = run(db_session, row, settings, storage,
               Recording(error=PlannerUnavailableError("down")))  # fmt: skip
    assert plan.status == "failed" and plan.error_code == "planner_unavailable"
    assert plan.configuration_snapshot is None


def test_a_systemically_invalid_model_plan_is_replaced_by_the_rules(
    db_session, world, settings, storage, monkeypatch
):
    from app.services.auto_edit import pipeline
    from app.services.auto_edit.validation import PlanRejected, validate_plan

    calls = []

    def flaky(proposal, context, recipe):
        calls.append(proposal)
        if len(calls) == 1:
            raise PlanRejected("The plan does not form a valid edit configuration")
        return validate_plan(proposal, context, recipe)

    monkeypatch.setattr(pipeline, "validate_plan", flaky)
    row = make_plan(db_session, world["clip"], settings, storage)
    plan = run(db_session, row, settings, storage, Recording())
    assert plan.status == "ready" and plan.fallback_reason == "plan_invalid"
    assert plan.planner_provider == "fallback" and len(calls) == 2


def test_a_configuration_mistake_fails_and_is_not_hidden(db_session, world, settings, storage):
    settings = Settings(**{**settings.model_dump(), "auto_edit_ollama_model": "",
                           "ollama_clip_models": ""})  # fmt: skip
    row = make_plan(db_session, world["clip"], settings, storage)
    run_auto_edit_plan(row.id, db_session, settings=settings, storage=storage, task_id="task-1")
    db_session.expire_all()
    plan = db_session.get(AutoEditPlan, row.id)
    assert plan.status == "failed" and plan.error_code == "planner_configuration"


def test_a_clip_with_nothing_prepared_still_gets_a_plan(db_session, settings, storage, tmp_path):
    clip = make_clip(db_session)
    clip.storage_key = stored(storage, tmp_path, "mp4", "clips")
    db_session.commit()
    row = make_plan(db_session, clip, settings, storage, recipe="minimal")
    plan = run(db_session, row, settings, storage,
               Recording(error=PlannerUnavailableError("down")))  # fmt: skip
    assert plan.status == "ready"
    snapshot = plan.configuration_snapshot
    assert snapshot["layout"] == "blur_background" and snapshot["captions"]["enabled"] is False
    assert "visuals" not in snapshot
    assert snapshot["hook"]["text"] == "h"  # the candidate's own hook, never invented text


def test_a_clip_that_is_not_ready_fails_safely(db_session, world, settings, storage):
    row = make_plan(db_session, world["clip"], settings, storage)
    world["clip"].status = "failed"
    db_session.commit()
    plan = run(db_session, row, settings, storage, Recording())
    assert plan.status == "failed" and plan.error_code == "clip_not_ready"


def test_storage_outage_is_not_mistaken_for_missing_assets(db_session, world, settings, storage):
    row = make_plan(db_session, world["clip"], settings, storage)

    class Down(LocalStorageProvider):
        def exists(self, key):
            raise StorageUnavailable("down")

    plan = run(db_session, row, settings, Down(storage.root), Recording())
    assert plan.status == "failed" and plan.error_code == "storage_unavailable"


def test_progress_stages_are_honest(db_session, world, settings, storage):
    row = make_plan(db_session, world["clip"], settings, storage)
    seen = []

    def look():
        db_session.refresh(row)
        seen.append((row.status, row.progress_percent))

    run(db_session, row, settings, storage, Recording(during=look))
    assert seen == [("planning", 35)]


def test_an_old_worker_cannot_write_after_a_retry_took_over(db_session, world, settings, storage):
    row = make_plan(db_session, world["clip"], settings, storage)

    def take_over():
        db_session.execute(AutoEditPlan.__table__.update().where(AutoEditPlan.id == row.id)
                           .values(celery_task_id="task-2", attempt=2))  # fmt: skip
        db_session.commit()

    plan = run(db_session, row, settings, storage, Recording(during=take_over))
    assert plan.status == "planning" and plan.configuration_snapshot is None
    assert plan.celery_task_id == "task-2"


def test_a_clip_deleted_mid_plan_stops_the_job(db_session, world, settings, storage):
    row = make_plan(db_session, world["clip"], settings, storage)

    def delete_clip():
        db_session.execute(Clip.__table__.delete().where(Clip.id == world["clip"].id))
        db_session.commit()

    plan_id = row.id
    planner = Recording(during=delete_clip)
    run_auto_edit_plan(plan_id, db_session, settings=settings, planner=planner, storage=storage,
                       task_id="task-1")  # fmt: skip
    db_session.expire_all()
    assert db_session.get(AutoEditPlan, plan_id) is None


def test_duplicate_and_stale_tasks(db_session, world, settings, storage):
    row = make_plan(db_session, world["clip"], settings, storage)
    first = Recording()
    run(db_session, row, settings, storage, first)
    again = Recording()
    plan = run(db_session, row, settings, storage, again)  # a duplicate delivery
    assert plan.status == "ready" and again.contexts == []
    other = make_plan(db_session, world["clip"], Settings(**{**settings.model_dump()}), storage,
                      recipe="clean")  # fmt: skip
    other.status, other.heartbeat_at = "planning", datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    reclaimed = run(db_session, other, settings, storage, Recording())
    assert reclaimed.status == "ready"


def test_the_task_takes_only_an_id(db_session):
    assert plan_auto_edit_task.name == "peaksift.plan_auto_edit"
    assert plan_auto_edit_task.run("not-a-uuid") is None  # logged and ignored
