"""The creator's words about a visual asset (name, description, tags): normalization, limits,
ownership, search across them, and suggestions offering likely matching assets."""

import uuid

import pytest

from app.api import broll as broll_api
from app.models import BrollAnalysis, BrollSuggestion, VisualAsset
from tests.test_clip_edit_api import ready_clip, sign_up

OWNER = "details-owner@example.com"


def visual(db, project_id, name="clip.png", **fields) -> str:
    row = VisualAsset(
        project_id=project_id, kind="image", display_name=name,
        storage_key=f"visuals/{uuid.uuid4().hex}.png", content_type="image/png", file_size=10,
        sha256=uuid.uuid4().hex * 2, width=100, height=100, codec="png", container="png", **fields,
    )  # fmt: skip
    db.add(row)
    db.commit()
    return str(row.id)


@pytest.fixture
def ctx(client, db_session, monkeypatch):
    sign_up(client, OWNER)
    ctx = ready_clip(db_session, OWNER)
    ctx["project_id"] = ctx["video"].project_id
    ctx["assets"] = f"/projects/{ctx['project_id']}/visual-assets"
    monkeypatch.setattr(
        broll_api, "enqueue_broll_analysis", lambda analysis_id, *, task_id: task_id
    )
    return ctx


def test_details_are_normalized_and_kept(client, db_session, ctx):
    asset = visual(db_session, ctx["project_id"])
    response = client.patch(
        f"{ctx['assets']}/{asset}",
        json={
            "display_name": "../Moon  launch.mp4",
            "description": "  NASA-style\n rocket   launch ",
            "tags": [" Rocket ", "space_station!", "rocket", "", "Lift-off"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] == "Moon  launch.mp4"
    assert body["description"] == "NASA-style rocket launch"
    assert body["tags"] == ["rocket", "space station", "lift-off"]
    partial = client.patch(f"{ctx['assets']}/{asset}", json={"tags": []}).json()
    assert partial["tags"] == [] and partial["description"] == "NASA-style rocket launch"


@pytest.mark.parametrize(
    ("details", "status"),
    [
        ({"display_name": "   "}, 422),
        ({"description": "x" * 501}, 422),
        ({"tags": ["t" * 33]}, 422),
        ({"tags": [f"tag{i}" for i in range(21)]}, 422),
        ({"storage_key": "visuals/x.png"}, 422),
        ({"tags": "rocket"}, 422),
    ],
)
def test_invalid_details_are_refused(client, db_session, ctx, details, status):
    asset = visual(db_session, ctx["project_id"])
    assert client.patch(f"{ctx['assets']}/{asset}", json=details).status_code == status


def test_only_the_owner_can_change_details(client, db_session, ctx):
    asset = visual(db_session, ctx["project_id"])
    sign_up(client, "intruder@example.com")
    assert client.patch(f"{ctx['assets']}/{asset}", json={"tags": ["x"]}).status_code == 404
    client.cookies.clear()
    assert client.patch(f"{ctx['assets']}/{asset}", json={"tags": ["x"]}).status_code == 401


def test_search_covers_descriptions_and_tags(client, db_session, ctx):
    visual(
        db_session,
        ctx["project_id"],
        "clip-7.mp4",
        description="NASA-style launch",
        tags=["rocket"],
    )
    visual(db_session, ctx["project_id"], "rocket.png")
    visual(db_session, ctx["project_id"], "other.png")
    names = lambda q: {a["display_name"] for a in client.get(ctx["assets"], params={"q": q}).json()}  # noqa: E731
    assert names("rocket") == {"clip-7.mp4", "rocket.png"}
    assert names("rocket launch") == {"clip-7.mp4"}
    assert names("nasa") == {"clip-7.mp4"}


def test_suggestions_offer_the_projects_likely_assets(client, db_session, ctx):
    bridge = visual(db_session, ctx["project_id"], "toothpick-bridge.jpg")
    tagged = visual(db_session, ctx["project_id"], "IMG_0042.jpg", tags=["bridge", "model"])
    visual(db_session, ctx["project_id"], "moon.jpg")
    other_project = ready_clip(db_session, OWNER)["video"].project_id
    visual(db_session, other_project, "bridge-elsewhere.jpg")  # never offered here
    base = ctx["base"].removesuffix("/edits") + "/broll"
    analysis_id = client.post(f"{base}/analyses").json()["id"]
    analysis = db_session.get(BrollAnalysis, uuid.UUID(analysis_id))
    analysis.status, analysis.suggestion_count = "completed", 2
    for index, query in enumerate(["bridge model", "solar fan"]):
        db_session.add(
            BrollSuggestion(analysis=analysis, clip_id=analysis.clip_id, sequence_index=index,
                            start_time=index * 5.0, end_time=index * 5.0 + 2, query=query,
                            reason="r", provider="ollama", provider_version="m")
        )  # fmt: skip
    db_session.commit()
    suggestions = client.get(base).json()["suggestions"]
    assert suggestions[0]["matches"] == [tagged]  # the bridge by name alone covers half: too weak
    assert suggestions[1]["matches"] == []
    db_session.get(VisualAsset, uuid.UUID(bridge)).tags = ["model"]
    db_session.commit()
    assert set(client.get(base).json()["suggestions"][0]["matches"]) == {tagged, bridge}
