"""B-roll with every V1 feature, rendered end to end through the real job — and the visual
flow on object storage (moto, and the live MinIO CI requires): Smart Reframe + B-roll, audio
finishing + B-roll, the full V1 edit (Smart Reframe, word-synced captions, hook, music, effect)
+ a cutaway and a picture-in-picture. Fixtures are generated; nothing is downloaded."""

import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import ClipEditStatus, Video, VisualAsset
from app.services.clip_edit.config import EditConfig
from app.services.clip_edit.pipeline import run_clip_edit
from app.services.ffprobe import probe, probe_audio
from app.services.storage import LocalStorageProvider
from app.services.workspace import work_root
from tests.audio_fixtures import amplitude, decode
from tests.media_fixtures import generate_video, requires_ffmpeg, requires_libass
from tests.test_audio_edit_render import add_asset
from tests.test_clip_edit_pipeline import make_edit as make_pipeline_edit
from tests.test_dynamic_caption_edits import add_completed_track, use_config
from tests.test_s3_media_regression import (  # noqa: F401  (the bucket fixture)
    assert_range_served,
    bucket,
    candidate_for,
    files_under,
    objects,
)
from tests.test_smart_reframe_render import completed_analysis
from tests.test_visual_render import BLUE, GREY, RED, YELLOW, close, main_clip, pixel

pytestmark = requires_ffmpeg
FFMPEG = get_settings().ffmpeg_path


@pytest.fixture
def settings() -> Settings:
    return Settings(**{**get_settings().model_dump(), "clip_render_preset": "ultrafast"})


@pytest.fixture
def storage() -> LocalStorageProvider:
    return LocalStorageProvider(Path(get_settings().media_root))


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in sorted(Path(get_settings().media_root).rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()


def store_visual(db: Session, storage, project_id, kind: str, make) -> VisualAsset:
    extension = "png" if kind == "image" else "mp4"
    key = storage.generate_key(extension, category="visuals")
    path = storage.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    make(path)
    meta = probe(path) if kind == "video" else None
    width, height = (meta.width, meta.height) if meta else Image.open(path).size
    asset = VisualAsset(
        project_id=project_id, kind=kind, display_name=f"{kind}.{extension}", storage_key=key,
        content_type="image/png" if kind == "image" else "video/mp4",
        file_size=path.stat().st_size, sha256=uuid.uuid4().hex * 2, width=width, height=height,
        duration_seconds=meta.duration_seconds if meta else None, fps=meta.fps if meta else None,
        codec="png" if kind == "image" else "h264", container=extension,
        has_audio=bool(meta and meta.audio_codec),
    )  # fmt: skip
    db.add(asset)
    db.commit()
    return asset


def red_image(path: Path) -> None:
    Image.new("RGB", (400, 300), RED).save(path)


def yellow_image(path: Path) -> None:
    Image.new("RGB", (300, 300), YELLOW).save(path)


def noisy_blue_video(path: Path) -> None:
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x0000FF:s=320x180:r=30:d=3",
         "-f", "lavfi", "-i", "sine=frequency=3000:duration=3", "-af", "volume=6",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac",
         "-shortest", str(path)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip


def prepared_edit(db, storage, seconds=3.0):
    edit = make_pipeline_edit(db, storage, captions=False, layout="center_crop")
    main_clip(storage.path_for(edit.clip.storage_key), seconds=seconds)
    edit.clip.end_time = edit.clip.start_time + seconds
    edit.clip.duration_seconds = seconds
    db.commit()
    return edit


def cutaway(asset, start=1.0, end=2.0, **extra):
    return {"asset_id": str(asset.id), "mode": "cutaway", "start_seconds": start,
            "end_seconds": end, **extra}  # fmt: skip


def render(db, edit, settings, storage, config: EditConfig):
    edit = use_config(db, edit, config)
    result = run_clip_edit(
        edit.id, db, settings=settings, storage=storage, task_id=edit.celery_task_id
    )
    assert result.status == ClipEditStatus.READY, (result.error_code, result.error_message)
    return result, storage.path_for(result.storage_key)


def test_smart_reframe_with_a_cutaway(db_session, settings, storage):
    edit = prepared_edit(db_session, storage)
    analysis = completed_analysis(db_session, edit.clip, points=3)
    red = store_visual(db_session, storage, edit.clip.video.project_id, "image", red_image)
    config = EditConfig.create(
        layout="smart_reframe", reframe_analysis_id=analysis.id, captions_enabled=False,
        visuals={"elements": [cutaway(red, transition="fade", transition_seconds=0.2)]},
    )  # fmt: skip
    result, out = render(db_session, edit, settings, storage, config)
    assert close(pixel(out, 540, 960, t=1.5), RED) and close(pixel(out, 540, 960, t=0.5), GREY)
    assert abs(result.duration_seconds - 3.0) <= 0.1


def test_audio_finishing_with_a_noisy_video_broll(db_session, settings, storage):
    edit = prepared_edit(db_session, storage)
    project = edit.clip.video.project_id
    music = add_asset(db_session, storage, project, "music", "0.5*sin(2*PI*200*t)", 10)
    blue = store_visual(db_session, storage, project, "video", noisy_blue_video)
    config = EditConfig.create(
        layout="center_crop", captions_enabled=False,
        audio={"music": {"asset_id": str(music.id), "gain_db": -12, "ducking": "off",
                         "fade_in_seconds": 0, "fade_out_seconds": 0}},
        visuals={"elements": [cutaway(blue, 0.5, 2.5)]},
    )  # fmt: skip
    result, out = render(db_session, edit, settings, storage, config)
    samples = decode(out)
    assert amplitude(samples, 0.7, 2.3, 200) > 0.01  # the music is there
    assert amplitude(samples, 0.7, 2.3, 3000) < 0.005  # the B-roll's own sound is not
    assert close(pixel(out, 540, 960, t=1.5), BLUE)
    assert result.audio_loudness_lufs is not None and result.audio_codec == "aac"


@requires_libass
def test_the_full_v1_edit_with_broll(db_session, settings, storage):
    edit = prepared_edit(db_session, storage)
    project = edit.clip.video.project_id
    analysis = completed_analysis(db_session, edit.clip, points=3)
    track = add_completed_track(db_session, edit.clip)
    music = add_asset(db_session, storage, project, "music", "0.4*sin(2*PI*200*t)", 10)
    hit = add_asset(db_session, storage, project, "sfx", "0.6*sin(2*PI*3000*t)", 0.25)
    red = store_visual(db_session, storage, project, "image", red_image)
    yellow = store_visual(db_session, storage, project, "image", yellow_image)
    config = EditConfig.create(
        layout="smart_reframe", reframe_analysis_id=analysis.id,
        captions_enabled=True, caption_style="punch", caption_position="bottom",
        caption_timing="aligned_word", caption_track_id=track.id,
        hook_enabled=True, hook_text="Watch this", hook_style="headline", hook_position="top",
        hook_duration=1.5,
        audio={"music": {"asset_id": str(music.id)},
               "sfx": [{"asset_id": str(hit.id), "at_seconds": 1.0}]},
        visuals={"elements": [
            cutaway(red, 2.0, 2.8, fit="fit", transition="fade", transition_seconds=0.2),
            {"asset_id": str(yellow.id), "mode": "pip", "position": "top_right", "size": "small",
             "start_seconds": 0.3, "end_seconds": 1.8},
        ]},
    )  # fmt: skip
    result, out = render(db_session, edit, settings, storage, config)
    meta, audio = probe(out), probe_audio(out)
    assert (meta.width, meta.height, meta.video_codec) == (1080, 1920, "h264")
    assert abs(meta.duration_seconds - 3.0) <= 0.1 and round(meta.fps) == 25
    assert (audio.channels, audio.sample_rate) == (2, 48000)
    assert close(pixel(out, 540, 960, t=2.4), RED)  # the cutaway (fit, centre of the image)
    assert close(pixel(out, 1080 - 97 - 92, 192 + 92, t=1.2), YELLOW)  # the small PiP
    assert result.caption_cue_count and result.caption_cue_count > 0
    assert sorted(p.name for p in out.parent.iterdir()) == ["edited.mp4"]  # no temp files left


def test_the_visual_flow_on_object_storage(bucket, client: TestClient, db_session, tmp_path):  # noqa: F811
    media_root = Path(get_settings().media_root)
    before = files_under(media_root)
    account = {"email": "visual-bucket@example.com", "password": "correct horse battery"}
    assert client.post("/auth/register", json=account).status_code == 201
    project_id = client.post("/projects", json={"name": "Bucket visuals"}).json()["id"]
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

    red_image(tmp_path / "red.png")
    noisy_blue_video(tmp_path / "blue.mp4")
    assets = {}
    for name, kind in (("red.png", "image/png"), ("blue.mp4", "video/mp4")):
        upload = {"file": (name, (tmp_path / name).read_bytes(), kind)}
        response = client.post(f"/projects/{project_id}/visual-assets", files=upload)
        assert response.status_code == 201, response.text
        assets[name] = response.json()
        base = f"/projects/{project_id}/visual-assets/{assets[name]['id']}"
        assert_range_served(client, f"{base}/content", assets[name]["file_size"])
        assert client.get(f"{base}/thumbnail").status_code == 200

    edits = f"/projects/{project_id}/videos/{video_id}/clips/{clip['id']}/edits"
    created = client.post(edits, json={
        "layout": "center_crop", "captions_enabled": False,
        "visuals": {"elements": [
            {"asset_id": assets["red.png"]["id"], "mode": "cutaway", "start_seconds": 0.5,
             "end_seconds": 1.5},
            {"asset_id": assets["blue.mp4"]["id"], "mode": "pip", "start_seconds": 1.6,
             "end_seconds": 2.8, "position": "bottom_left"},
        ]},
    })  # fmt: skip
    assert created.status_code == 201, created.text
    edit = client.get(f"{edits}/{created.json()['id']}").json()
    assert edit["status"] == "ready", edit
    assert_range_served(client, f"/edits/{edit['id']}/content", edit["file_size"])

    keys = objects(bucket)
    visuals = [k for k in keys if k.startswith("visuals/")]
    assert len(visuals) == 4  # two assets and their thumbnails
    assert f"edits/{edit['id']}/edited.mp4" in keys
    assert files_under(media_root) == before  # nothing went to local media
    leftovers = [p for p in files_under(work_root(get_settings())) if str(edit["id"]) in str(p)
                 or "uploads" in p.parts]  # fmt: skip
    assert leftovers == []
    # An asset in use cannot be deleted; deleting the edit then the asset empties its objects.
    image_url = f"/projects/{project_id}/visual-assets/{assets['red.png']['id']}"
    assert client.delete(image_url).status_code == 409
    assert client.delete(f"{edits}/{edit['id']}").status_code == 200
    assert client.delete(image_url).json()["media_files_removed"] == 2
    assert len([k for k in objects(bucket) if k.startswith("visuals/")]) == 2
