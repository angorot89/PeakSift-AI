"""V1.3 semantic assets on the CI matrix: upload → index → search → B-roll match on object
storage (moto, and the live MinIO CI requires) with nothing written to local media and no
frames stored; and the CI workflow keeps every semantic suite, the benchmark gate and its
no-weights rule."""

import uuid
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.models import VisualAsset
from app.services.semantic.indexing import request_index, run_semantic_index
from app.services.semantic.matching import match_queries
from app.services.semantic.registry import reset_providers
from app.services.semantic.search import QUERY_CACHE
from tests.media_fixtures import requires_ffmpeg
from tests.test_s3_media_regression import (  # noqa: F401  (the bucket fixture)
    _Reusable,
    bucket,
    files_under,
    objects,
)
from tests.test_video_upload import create_project, sign_up
from tests.visual_fixtures import make_image, make_video

ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
SHOT = "drawbox=x=40:y=40:w=80:h=60:color=white:t=fill,noise=alls=20:allf=t"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    QUERY_CACHE.clear()
    reset_providers()
    monkeypatch.setattr("app.api.visual_assets.start_indexing_quietly", lambda *a: None)
    yield
    reset_providers()


@requires_ffmpeg
def test_index_search_and_match_on_object_storage(client, db_session, bucket, tmp_path):  # noqa: F811
    sign_up(client, f"s3-{uuid.uuid4().hex[:8]}@example.com")
    project = create_project(client)["id"]
    photo = make_image(tmp_path / "IMG_7834.jpg", color=(45, 95, 190))
    video = make_video(
        tmp_path / "VID_1429.mp4", seconds=8.0, extra_filters=SHOT,
        source="color=c=0x2d5fbe:size=320x180:rate=30:duration=4[a];"
               "color=c=0xd7462d:size=320x180:rate=30:duration=4[b];[a][b]concat=n=2:v=1:a=0",
    )  # fmt: skip
    local_before = set(files_under(Path(get_settings().media_root)))
    ids = []
    for path in (photo, video):
        with path.open("rb") as handle:
            response = client.post(f"/projects/{project}/visual-assets",
                                   files={"file": (path.name, handle.read())})  # fmt: skip
        assert response.status_code == 201
        ids.append(response.json()["id"])
    stored_before = objects(bucket)
    for asset_id in ids:
        asset = db_session.get(VisualAsset, uuid.UUID(asset_id))
        index = request_index(db_session, asset, get_settings())
        run_semantic_index(index.id, db_session, settings=get_settings(),
                           task_id=index.celery_task_id)  # fmt: skip
        assert index.status == "ready", index.error_message
    assert objects(bucket) == stored_before  # frames and vectors never become media objects
    assert set(files_under(Path(get_settings().media_root))) == local_before  # nothing local
    body = client.get(f"/projects/{project}/visual-assets/search",
                      params={"q": "bridge structure"}).json()  # fmt: skip
    assert body["visual_search_used"] and body["results"][0]["asset"]["id"] in ids
    (hit,) = client.get(f"/projects/{project}/visual-assets/search",
                        params={"q": "rocket launch"}).json()["results"]  # fmt: skip
    assert hit["asset"]["id"] == ids[1] and hit["match"]["best_frame_time"] >= 4.0
    assets = [db_session.get(VisualAsset, uuid.UUID(i)) for i in ids]
    found = match_queries(db_session, uuid.UUID(project), ["bridge joint"], assets, get_settings())
    matches = found.get("bridge joint")  # the photo, and the video's bridge scene
    assert assets[0].id in [m.asset.id for m in matches]
    assert all(m.strength == "strong" and m.method == "visual" for m in matches)


def test_the_ci_workflow_runs_every_semantic_suite_and_gate():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "image: pgvector/pgvector:pg16" in ci  # the vector type exists in CI's database
    assert "python scripts/semantic_benchmark.py" in ci  # the benchmark's safety gates
    assert 'SEMANTIC_PROVIDER: "fake"' in ci  # deterministic embeddings, no weights
    assert "python scripts/fetch_semantic_model" not in ci  # CI never downloads a model
    suites = sorted(
        p.name for p in TESTS.glob("test_*.py")
        if p.name.startswith("test_semantic_") or p.name == "test_auto_edit_semantic.py"
    )  # fmt: skip
    missing = [name for name in suites if f"tests/{name}" not in ci]
    assert not missing, f"semantic suites not listed in CI: {missing}"
    smoke = (ROOT / "backend/scripts/celery_smoke.py").read_text()
    assert '"peaksift.index_visual_asset"' in smoke
    compose = (ROOT / "deploy/docker-compose.prod.yml").read_text()
    assert "dockerfile: postgres.Dockerfile" in compose and "models:/models:ro" in compose
