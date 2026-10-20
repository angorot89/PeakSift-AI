"""Auto Edit end to end on real FFmpeg (the CI matrix): a plan made by the rules — and one made
by a scripted model with every feature — becomes a normal edit configuration that the existing
renderer turns into a correct 1080 x 1920 short; and the whole flow (plan, apply, render) works
on object storage (moto, and the live MinIO CI requires) without touching local media."""

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.models import (
    AutoEditPlan,
    BrollAnalysis,
    BrollSuggestion,
    Video,
)
from app.services.auto_edit.config import AutoEditRequest
from app.services.auto_edit.fallback import FallbackAutoEditPlanner
from app.services.auto_edit.fingerprint import source_fingerprint
from app.services.auto_edit.pipeline import run_auto_edit_plan
from app.services.auto_edit.sources import gather
from app.services.broll.config import BrollConfig
from app.services.clip_edit.config import EditConfig
from app.services.ffprobe import probe, probe_audio
from tests.audio_fixtures import amplitude, decode
from tests.media_fixtures import generate_video, requires_ffmpeg, requires_libass
from tests.test_audio_edit_render import add_asset
from tests.test_auto_edit_contract import GOOD
from tests.test_auto_edit_pipeline import Recording
from tests.test_dynamic_caption_edits import add_completed_track
from tests.test_s3_media_regression import (  # noqa: F401  (the bucket fixture)
    _Reusable,
    bucket,
    candidate_for,
    files_under,
    objects,
)
from tests.test_smart_reframe_render import completed_analysis
from tests.test_visual_ci_matrix import prepared_edit, red_image, render, store_visual
from tests.test_visual_render import RED, close, pixel

pytestmark = requires_ffmpeg


@pytest.fixture
def settings() -> Settings:
    return Settings(**{**get_settings().model_dump(), "clip_render_preset": "ultrafast"})


@pytest.fixture
def storage():
    from app.services.storage import LocalStorageProvider

    return LocalStorageProvider(Path(get_settings().media_root))


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in sorted(Path(get_settings().media_root).rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()


def broll_for(db, clip, settings, start, end, query):
    config = BrollConfig.from_settings(settings)
    analysis = BrollAnalysis(
        clip_id=clip.id, video_id=clip.video_id, config=config.snapshot(),
        config_fingerprint=config.fingerprint(), suggestion_version=config.suggestion_version,
        provider="ollama", model=config.model, status="completed", suggestion_count=1,
    )  # fmt: skip
    db.add(analysis)
    db.flush()
    db.add(
        BrollSuggestion(
            analysis_id=analysis.id, clip_id=clip.id, sequence_index=0, start_time=start,
            end_time=end, query=query, reason="Shows it", provider="ollama", provider_version="m",
        )
    )  # fmt: skip
    db.commit()


def prepared(db, storage, settings):
    """A 3 s clip with strong framing, word timing, a B-roll suggestion and a tagged image,
    a music track and a transition sound."""
    edit = prepared_edit(db, storage)
    clip = edit.clip
    analysis = completed_analysis(db, clip, points=3)
    analysis.confidence_level = "high"
    add_completed_track(db, clip)
    project = clip.video.project_id
    red = store_visual(db, storage, project, "image", red_image)
    red.tags, red.description = ["bridge", "joint"], "The weak joint"
    broll_for(db, clip, settings, 1.0, 2.5, "bridge joint")
    music = add_asset(db, storage, project, "music", "0.4*sin(2*PI*200*t)", 10)
    whoosh = add_asset(db, storage, project, "sfx", "0.6*sin(2*PI*3000*t)", 0.3)
    whoosh.display_name = "whoosh.wav"
    db.commit()
    return edit, {"red": red, "music": music, "whoosh": whoosh}


def planned(db, edit, settings, storage, planner, *, recipe, music=None) -> AutoEditPlan:
    request = AutoEditRequest.from_settings(settings, recipe=recipe, music_asset_id=music)
    sources = gather(edit.clip, db, settings, storage, request).sources
    row = AutoEditPlan(
        clip_id=edit.clip.id, video_id=edit.clip.video_id, recipe=request.recipe,
        recipe_version=request.recipe_version, planner_version=request.planner_version,
        planner_provider=request.provider, planner_model=request.model,
        config=request.snapshot(),
        source_fingerprint=source_fingerprint(sources, request.snapshot()),
        celery_task_id="task-1",
    )  # fmt: skip
    db.add(row)
    db.commit()
    run_auto_edit_plan(row.id, db, settings=settings, planner=planner, storage=storage,
                       task_id="task-1")  # fmt: skip
    db.refresh(row)
    assert row.status == "ready", (row.error_code, row.error_message)
    return row


@requires_libass
def test_a_rules_plan_renders_as_a_normal_edit(db_session, settings, storage):
    edit, assets = prepared(db_session, storage, settings)
    plan = planned(db_session, edit, settings, storage, FallbackAutoEditPlanner(), recipe="clean",
                   music=str(assets["music"].id))  # fmt: skip
    config = EditConfig.from_snapshot(plan.configuration_snapshot)
    assert config.layout.value == "smart_reframe" and config.caption_timing.value == "aligned_word"
    assert config.audio.music.asset_id == str(assets["music"].id)
    result, out = render(db_session, edit, settings, storage, config)
    meta, audio = probe(out), probe_audio(out)
    assert (meta.width, meta.height, meta.video_codec, meta.audio_codec) == (1080, 1920, "h264",
                                                                               "aac")  # fmt: skip
    assert abs(meta.duration_seconds - 3.0) <= 0.1 and (audio.channels, audio.sample_rate) == (
        2, 48000
    )  # fmt: skip
    assert close(pixel(out, 540, 960, t=1.75), RED)  # the matched cutaway, at its moment
    assert result.caption_cue_count and result.caption_cue_count > 0
    assert amplitude(decode(out), 0.2, 2.8, 200) > 0.002  # the chosen music, ducked but there
    assert result.audio_loudness_lufs is not None


@requires_libass
def test_a_model_plan_with_every_feature_renders(db_session, settings, storage):
    edit, assets = prepared(db_session, storage, settings)
    proposal = json.loads(json.dumps(GOOD))
    proposal["audio"] = {"use_music": True, "music_level": "medium", "ducking": "medium",
                         "transition_sounds": True}  # fmt: skip
    proposal["hook"]["text"] = "h"  # the candidate's own hook in this fixture
    plan = planned(db_session, edit, settings, storage, Recording(proposal), recipe="punchy",
                   music=str(assets["music"].id))  # fmt: skip
    config = EditConfig.from_snapshot(plan.configuration_snapshot)
    assert config.hook is not None and config.visuals is not None
    (cue,) = config.audio.sfx
    assert cue.asset_id == str(assets["whoosh"].id) and cue.at_seconds == pytest.approx(0.95)
    result, out = render(db_session, edit, settings, storage, config)
    samples = decode(out)
    assert amplitude(samples, 0.95, 1.2, 3000) > 0.005  # the transition sound at the cutaway
    assert amplitude(samples, 1.6, 2.4, 3000) < amplitude(samples, 0.95, 1.2, 3000)
    assert close(pixel(out, 540, 960, t=1.75), RED)
    assert sorted(p.name for p in out.parent.iterdir()) == ["edited.mp4"]


def test_plan_apply_and_render_on_object_storage(
    bucket,  # noqa: F811
    client: TestClient,
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("app.workers.auto_edit_tasks.SessionLocal", lambda: _Reusable(db_session))
    monkeypatch.setattr(
        "app.services.auto_edit.pipeline.get_planner", lambda *a: FallbackAutoEditPlanner()
    )
    media_root = Path(get_settings().media_root)
    before = files_under(media_root)
    account = {"email": "auto-edit-bucket@example.com", "password": "correct horse battery"}
    assert client.post("/auth/register", json=account).status_code == 201
    project_id = client.post("/projects", json={"name": "Bucket auto edit"}).json()["id"]
    source = generate_video(tmp_path / "source.mp4", seconds=6.0)
    upload = {"file": ("s.mp4", source.read_bytes(), "video/mp4")}
    video_id = client.post(f"/projects/{project_id}/videos", files=upload).json()["id"]
    video = db_session.get(Video, uuid.UUID(video_id))
    run, candidate = candidate_for(db_session, video, start=1.0, end=4.0)
    clip_url = (f"/projects/{project_id}/videos/{video_id}/clip-detection/{run.id}"
                f"/candidates/{candidate.id}/clip")  # fmt: skip
    assert client.post(clip_url).status_code == 201
    clip = client.get(clip_url).json()
    assert clip["status"] == "ready", clip
    red_image(tmp_path / "joint.png")
    response = client.post(
        f"/projects/{project_id}/visual-assets",
        files={"file": ("joint.png", (tmp_path / "joint.png").read_bytes(), "image/png")},
    )
    asset = response.json()
    assert client.patch(f"/projects/{project_id}/visual-assets/{asset['id']}",
                        json={"tags": ["bridge", "joint"]}).status_code == 200  # fmt: skip
    from app.models import Clip

    # 2.5 s: long enough for the Story recipe's minimum hold.
    broll_for(db_session, db_session.get(Clip, uuid.UUID(clip["id"])), get_settings(), 0.5, 3.0,
              "bridge joint")  # fmt: skip

    base = f"/projects/{project_id}/videos/{video_id}/clips/{clip['id']}/auto-edits"
    created = client.post(base, json={"recipe": "story"})
    assert created.status_code == 201, created.text
    plan = client.get(f"{base}/{created.json()['id']}").json()
    assert plan["status"] == "ready", plan
    assert plan["configuration"]["visuals"]["elements"][0]["asset_id"] == asset["id"]
    applied = client.post(f"{base}/{plan['id']}/apply")
    assert applied.status_code == 200, applied.text
    edit = applied.json()["edit"]
    edits = f"/projects/{project_id}/videos/{video_id}/clips/{clip['id']}/edits"
    edit = client.get(f"{edits}/{edit['id']}").json()
    assert edit["status"] == "ready", edit
    assert f"edits/{edit['id']}/edited.mp4" in objects(bucket)
    assert files_under(media_root) == before  # nothing went to local media
