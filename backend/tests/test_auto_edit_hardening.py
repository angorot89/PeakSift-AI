"""Auto Edit hardening: the edge cases a senior review asked about — missing clip files, no
transcript at all, video-only libraries, several music tracks, tampered or cross-project
configurations, re-applying a plan whose version was deleted, clashing visuals, and the
planner's HTTP client lifecycle."""

import json
import uuid
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.models import AudioAsset, AutoEditPlan, ClipEdit, VisualAsset
from app.services.auto_edit.contract import BrollOption, VisualOption
from app.services.auto_edit.ollama import OllamaAutoEditPlanner
from app.services.auto_edit.recipes import current_recipe
from app.services.auto_edit.sources import gather
from app.services.auto_edit.validation import validate_plan
from app.services.storage import LocalStorageProvider, StorageUnavailable
from tests.test_auto_edit_api import clip_ctx, plan_now
from tests.test_auto_edit_api import fake_queues as fake_queues  # noqa: F401 - autouse fixture
from tests.test_auto_edit_api import storage as api_storage
from tests.test_auto_edit_contract import GOOD
from tests.test_auto_edit_ollama import settings as ollama_settings
from tests.test_auto_edit_pipeline import (
    Recording,
    build_world,
    make_plan,
    pipeline_settings,
    run,
    stored,
)
from tests.test_auto_edit_validation import ctx as validation_ctx
from tests.test_auto_edit_validation import proposal
from tests.test_clip_edit_api import PASSWORD, sign_up


@pytest.fixture
def settings():
    return pipeline_settings()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "media")


@pytest.fixture
def world(db_session, settings, storage, tmp_path):
    return build_world(db_session, settings, storage, tmp_path)


# --- missing media ------------------------------------------------------------------------------


def test_a_missing_clip_file_is_refused_by_the_api(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    api_storage().delete(ctx["clip"].storage_key)
    response = client.post(ctx["base"], json={"recipe": "clean"})
    assert response.status_code == 409 and "clip file is missing" in response.json()["detail"]
    assert db_session.scalar(select(func.count()).select_from(AutoEditPlan)) == 0


def test_a_storage_outage_is_503_not_missing(client, db_session, monkeypatch):
    sign_up(client)
    ctx = clip_ctx(db_session)

    def down(self, key):
        raise StorageUnavailable("down")

    monkeypatch.setattr("app.services.storage.LocalStorageProvider.exists", down)
    assert client.post(ctx["base"], json={"recipe": "clean"}).status_code == 503


def test_a_clip_file_removed_before_planning_fails_the_plan_safely(
    db_session,
    world,
    settings,
    storage,
):
    row = make_plan(db_session, world["clip"], settings, storage)
    storage.delete(world["clip"].storage_key)
    plan = run(db_session, row, settings, storage, Recording())
    assert plan.status == "failed" and plan.error_code == "clip_missing"
    assert "storage" not in plan.error_message and "/" not in plan.error_message


# --- inputs that are not there ------------------------------------------------------------------


def test_a_clip_whose_transcript_is_not_usable_still_gets_a_plan(
    db_session,
    world,
    settings,
    storage,
):
    # A generated clip always has a transcription row (deleting it would delete the clip);
    # the real case is a transcript that is no longer completed, and no word timing.
    world["clip"].video.transcription.status = "failed"
    for track in world["clip"].caption_tracks:
        db_session.delete(track)
    db_session.commit()
    row = make_plan(db_session, world["clip"], settings, storage, recipe="clean")
    planner = Recording()
    plan = run(db_session, row, settings, storage, planner)
    assert plan.status == "ready"
    context = planner.contexts[0]
    assert context.lines == () and not context.capabilities.phrase_timing
    assert not context.capabilities.word_timing
    assert plan.configuration_snapshot["captions"]["enabled"] is False


def test_several_music_tracks_are_never_chosen_without_the_creator(
    db_session,
    world,
    settings,
    storage,
    tmp_path,
):
    other = AudioAsset(
        project_id=world["clip"].video.project_id, kind="music", display_name="upbeat.mp3",
        storage_key=stored(storage, tmp_path, "mp3", "audio"), content_type="audio/mpeg",
        file_size=1, sha256="e" * 64, container="mp3", codec="mp3", duration_seconds=30.0,
        sample_rate=44100, channels=2, waveform_peaks=[],
    )  # fmt: skip
    db_session.add(other)
    db_session.commit()
    row = make_plan(db_session, world["clip"], settings, storage)
    audio = {"use_music": True, "music_level": "medium", "ducking": "medium",
             "transition_sounds": False}  # fmt: skip
    planner = Recording({**GOOD, "audio": audio})
    plan = run(db_session, row, settings, storage, planner)
    assert planner.contexts[0].music is None
    assert plan.configuration_snapshot["audio"]["music"] is None


def test_a_video_only_library_can_fill_a_moment(db_session, world, settings, storage, tmp_path):
    db_session.delete(world["bridge"])
    db_session.add(
        VisualAsset(
            project_id=world["clip"].video.project_id, kind="video", display_name="joint.mp4",
            storage_key=stored(storage, tmp_path, "mp4", "visuals"),
            content_type="video/mp4", file_size=1, sha256="f" * 64, width=1280, height=720,
            duration_seconds=8.0, fps=30.0, codec="h264", container="mp4",
            tags=["bridge", "joint"],
        )
    )  # fmt: skip
    db_session.commit()
    row = make_plan(db_session, world["clip"], settings, storage)
    plan = run(db_session, row, settings, storage, Recording())
    (element,) = plan.configuration_snapshot["visuals"]["elements"]
    assert element["mode"] == "cutaway" and element.get("asset_offset_seconds", 0) == 0
    assert element.get("loop", False) is False


# --- applying -----------------------------------------------------------------------------------


def test_a_tampered_cross_project_asset_is_refused_at_apply(client, db_session, tmp_path):
    sign_up(client)
    ctx = clip_ctx(db_session)
    plan_id = client.post(ctx["base"], json={"recipe": "punchy"}).json()["id"]
    plan_now(db_session, plan_id)
    sign_up(client, "someone-else@example.com")
    other = clip_ctx(db_session, "someone-else@example.com")
    key = f"visuals/{uuid.uuid4().hex}.jpg"
    foreign = VisualAsset(
        project_id=other["video"].project_id, kind="image", display_name="theirs.jpg",
        storage_key=key, content_type="image/jpeg", file_size=1, sha256="9" * 64, width=10,
        height=10, codec="jpeg", container="jpeg",
    )  # fmt: skip
    db_session.add(foreign)
    row = db_session.get(AutoEditPlan, uuid.UUID(plan_id))
    snapshot = json.loads(json.dumps(row.configuration_snapshot))
    snapshot["visuals"] = {"version": "visuals_v1", "elements": [
        {"asset_id": str(foreign.id), "mode": "cutaway", "start_seconds": 1.0, "end_seconds": 3.0,
         "fit": "fill"}]}  # fmt: skip
    row.configuration_snapshot = snapshot
    db_session.commit()
    client.post("/auth/logout")
    sign_in = client.post("/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    assert sign_in.status_code == 200
    response = client.post(f"{ctx['base']}/{plan_id}/apply")
    assert response.status_code == 409
    assert db_session.scalar(select(func.count()).select_from(ClipEdit)) == 0


def test_reapplying_a_plan_whose_version_was_deleted_explains_itself(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    plan_id = client.post(ctx["base"], json={"recipe": "minimal"}).json()["id"]
    plan_now(db_session, plan_id, data={**GOOD, "visuals": []})
    edit_id = client.post(f"{ctx['base']}/{plan_id}/apply").json()["edit"]["id"]
    assert client.delete(f"{ctx['edits']}/{edit_id}").status_code == 200
    response = client.post(f"{ctx['base']}/{plan_id}/apply")
    assert response.status_code == 409 and "version was deleted" in response.json()["detail"]
    plan = client.get(f"{ctx['base']}/{plan_id}").json()
    assert plan["status"] == "applied" and plan["clip_edit_id"] is None
    assert db_session.scalar(select(func.count()).select_from(ClipEdit)) == 0  # nothing new


# --- validation details -------------------------------------------------------------------------


def test_clashing_visuals_are_explained_as_clashes():
    recipe = replace(current_recipe("punchy"), min_gap_seconds=0.0)
    first = BrollOption("suggestion_1", 10.2, 12.7, "bridge joint", "Joint", ("visual_asset_1",))
    second = BrollOption("suggestion_2", 11.0, 13.5, "bridge model", "Model", ("visual_asset_2",))
    model = VisualOption(
        "visual_asset_2", "image", "model.jpg", "", ("bridge", "model"), "landscape"
    )
    context = validation_ctx(
        broll=(first, second),
        visual_assets=(validation_ctx().visual_assets[0], model),
        visual_ids={"visual_asset_1": str(uuid.uuid4()), "visual_asset_2": str(uuid.uuid4())},
        suggestion_ids={"suggestion_1": str(uuid.uuid4()), "suggestion_2": str(uuid.uuid4())},
    )
    both = [
        {"suggestion": "suggestion_1", "asset": "visual_asset_1", "mode": "cutaway"},
        {"suggestion": "suggestion_2", "asset": "visual_asset_2", "mode": "cutaway"},
    ]
    plan = validate_plan(proposal(visuals=both), context, recipe)
    assert len(plan.configuration.visuals.elements) == 1
    assert any("overlap another" in note for note in plan.explanations["notes"])


# --- the planner's HTTP client --------------------------------------------------------------------


def test_the_planner_closes_its_own_http_client(monkeypatch):
    closed = []

    class Client(httpx.Client):
        def close(self):
            closed.append(True)
            super().close()

    def reply(request):
        return httpx.Response(200, json={"message": {"content": json.dumps(GOOD)}})

    monkeypatch.setattr(
        "app.services.auto_edit.ollama.httpx.Client",
        lambda base_url: Client(base_url=base_url, transport=httpx.MockTransport(reply)),
    )
    planner = OllamaAutoEditPlanner(ollama_settings(), "llama3.2:3b")
    context = validation_ctx()
    planner.plan(context)
    planner.plan(context)  # a planner can be used again: each plan has its own client
    assert closed == [True, True]


def test_gathering_never_offers_assets_of_another_project(
    db_session,
    world,
    settings,
    storage,
    tmp_path,
):
    from app.services.auto_edit.config import AutoEditRequest
    from tests.test_clip_edit_model import make_clip

    other = make_clip(db_session)
    db_session.add(
        VisualAsset(
            project_id=other.video.project_id, kind="image", display_name="bridge-joint.jpg",
            storage_key=stored(storage, tmp_path, "jpg", "visuals"),
            content_type="image/jpeg", file_size=1, sha256="8" * 64, width=10, height=10,
            codec="jpeg", container="jpeg", tags=["bridge", "joint"],
        )
    )  # fmt: skip
    db_session.commit()
    request = AutoEditRequest.from_settings(settings, recipe="punchy")
    gathered = gather(world["clip"], db_session, settings, storage, request)
    assert [a.name for a in gathered.context.visual_assets] == ["toothpick-bridge.jpg"]


@pytest.mark.parametrize("recipe", ["clean", "punchy", "story", "minimal"])
def test_every_recipe_validates_a_real_model_style_answer(recipe):
    plan = validate_plan(proposal(), validation_ctx(recipe), current_recipe(recipe))
    assert plan.configuration.fingerprint()
