"""Edits with a visuals section: request validation, the checks of referenced assets (same
project, mode fits the asset, timing inside the clip and the video), idempotency, references
that block deleting an asset, and a clear refusal while visuals cannot be rendered."""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.api import clip_edits as edits_api
from app.models import Project, VisualAsset
from tests.test_clip_edit_api import ready_clip, sign_up

OWNER = "visual-owner@example.com"


def visual(db: Session, project_id: uuid.UUID, kind: str = "image", duration: float | None = None):
    row = VisualAsset(
        project_id=project_id, kind=kind, display_name=f"{kind}.bin",
        storage_key=f"visuals/{uuid.uuid4().hex}.bin", content_type="image/png",
        file_size=10, sha256=uuid.uuid4().hex * 2, width=1920, height=1080,
        duration_seconds=duration, fps=30.0 if kind == "video" else None,
        codec="h264" if kind == "video" else "png", container="mp4" if kind == "video" else "png",
    )  # fmt: skip
    db.add(row)
    db.commit()
    return str(row.id)


@pytest.fixture
def ctx(client, db_session, monkeypatch):
    sign_up(client, OWNER)
    ctx = ready_clip(db_session, OWNER)  # a 20 s clip
    ctx["project_id"] = ctx["video"].project_id
    ctx["image"] = visual(db_session, ctx["project_id"])
    ctx["video_asset"] = visual(db_session, ctx["project_id"], "video", 8.0)
    ctx["queued"] = []
    monkeypatch.setattr(
        edits_api, "enqueue_clip_edit", lambda edit_id, *, task_id: ctx["queued"].append(edit_id)
    )
    monkeypatch.setattr(edits_api, "supports_visuals", lambda path: True)
    return ctx


def body(*elements):
    return {
        "layout": "center_crop",
        "captions_enabled": False,
        "visuals": {"elements": list(elements)},
    }


def cut(asset_id, **extra):
    return {"asset_id": asset_id, "mode": "cutaway", "start_seconds": 2, "end_seconds": 5, **extra}


def test_valid_visuals_are_stored_once_in_the_snapshot(client, ctx):
    request = body(
        cut(ctx["image"], fit="fit"),
        {"asset_id": ctx["video_asset"], "mode": "pip", "start_seconds": 6, "end_seconds": 9,
         "position": "bottom_left", "size": "small", "asset_offset_seconds": 1.5},
    )  # fmt: skip
    first = client.post(ctx["base"], json=request)
    assert first.status_code == 201, first.text
    elements = first.json()["configuration"]["visuals"]["elements"]
    assert [(e["mode"], e["asset_id"]) for e in elements] == [
        ("cutaway", ctx["image"]), ("pip", ctx["video_asset"])
    ]  # fmt: skip
    again = client.post(ctx["base"], json=request)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    plain = client.post(ctx["base"], json={"layout": "center_crop", "captions_enabled": False})
    assert "visuals" not in plain.json()["configuration"]
    assert len(ctx["queued"]) == 2


def test_assets_must_belong_to_the_clips_project(client, db_session, ctx):
    other = Project(name="Other", user_id=ctx["video"].project.user_id)
    db_session.add(other)
    db_session.commit()
    for asset_id in (visual(db_session, other.id), str(uuid.uuid4())):
        response = client.post(ctx["base"], json=body(cut(asset_id)))
        assert (
            response.status_code == 409
            and "this project's visual assets" in response.json()["detail"]
        )


CASES = [
    ({"mode": "cutaway", "start_seconds": 18, "end_seconds": 21}, "after the end of the clip"),
    ({"mode": "overlay", "start_seconds": 2, "end_seconds": 4, "video": True}, "Overlays use"),
    ({"mode": "cutaway", "start_seconds": 2, "end_seconds": 4, "loop": True}, "Images have no"),
    (
        {"mode": "pip", "start_seconds": 1, "end_seconds": 9, "video": True,
         "asset_offset_seconds": 2},
        "shorter than the visual",
    ),
]  # fmt: skip


@pytest.mark.parametrize(("element", "detail"), CASES)
def test_visuals_must_fit_their_asset_and_the_clip(client, ctx, element, detail):
    asset = ctx["video_asset"] if element.pop("video", False) else ctx["image"]
    response = client.post(ctx["base"], json=body({"asset_id": asset, **element}))
    assert response.status_code == 422 and detail in response.json()["detail"]


@pytest.mark.parametrize(
    "visuals",
    [
        {"elements": [{"asset_id": "x", "mode": "cutaway", "start_seconds": 0, "end_seconds": 1}]},
        {"elements": [{"mode": "cutaway", "start_seconds": 0, "end_seconds": 1}]},
        {"elements": [{"asset_id": str(uuid.uuid4()), "mode": "cutaway", "start_seconds": 0,
                       "end_seconds": 1, "filter": "drawtext"}]},
        {"elements": "all of them"},
        {"elements": [], "extra": 1},
    ],
)  # fmt: skip
def test_malformed_visual_requests_are_422(client, ctx, visuals):
    response = client.post(
        ctx["base"], json={"layout": "fit", "captions_enabled": False, "visuals": visuals}
    )
    assert response.status_code == 422


def test_overlapping_cutaways_are_refused(client, ctx):
    response = client.post(
        ctx["base"], json=body(cut(ctx["image"]), cut(ctx["image"], start_seconds=4, end_seconds=7))
    )
    assert response.status_code == 422 and "cannot overlap" in response.json()["detail"]


def test_an_asset_used_by_an_edit_cannot_be_deleted(client, ctx):
    assert client.post(ctx["base"], json=body(cut(ctx["image"]))).status_code == 201
    response = client.delete(f"/projects/{ctx['project_id']}/visual-assets/{ctx['image']}")
    assert response.status_code == 409 and "used by 1 edit" in response.json()["detail"]


def test_visuals_are_refused_clearly_while_they_cannot_be_rendered(client, ctx, monkeypatch):
    monkeypatch.setattr(edits_api, "supports_visuals", lambda path: False)
    response = client.post(ctx["base"], json=body(cut(ctx["image"])))
    assert response.status_code == 409 and "not available" in response.json()["detail"]
    assert ctx["queued"] == []
