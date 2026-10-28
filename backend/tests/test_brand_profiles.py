"""Brand profiles (V1.7): owner-scoped brands with normalized colours, a logo from the
creator's own images, one default, and deletion that never breaks anything."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import BrandProfile, Project, User, VisualAsset
from app.services.branding import profiles
from app.services.branding.colors import (
    contrast,
    emphasis_readable,
    normalize_color,
    text_on,
)
from tests.test_clip_edit_api import PASSWORD, sign_up
from tests.test_copilot_context import visual


def me(db, email):
    return db.scalar(select(User).where(User.email == email))


def project_for(db, email, name="Channel"):
    project = Project(name=name, owner=me(db, email))
    db.add(project)
    db.flush()
    return project


def video_asset(db, project_id):
    asset = VisualAsset(
        project_id=project_id, kind="video", display_name="b.mp4",
        storage_key=f"visuals/{uuid.uuid4().hex}.mp4", content_type="video/mp4", file_size=10,
        sha256=uuid.uuid4().hex * 2, width=640, height=360, duration_seconds=3.0, fps=30.0,
        codec="h264", container="mp4",
    )  # fmt: skip
    db.add(asset)
    db.flush()
    return asset


# --- colours ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [("#ff3a72", "#FF3A72"), ("#F3A", "#FF33AA"), ("  #00aa00 ", "#00AA00")],
)
def test_colours_are_normalized(raw, normalized):
    assert normalize_color(raw) == normalized


@pytest.mark.parametrize(
    "raw",
    ["red", "#12345", "#1234567", "rgb(1,2,3)", "#ff3a72; background:url(x)", "#ff3a7280", 3, None],
)
def test_anything_but_hex_is_refused(raw):
    with pytest.raises(ValueError):
        normalize_color(raw)


def test_readability_follows_wcag():
    assert round(contrast("#FFFFFF", "#000000"), 1) == 21.0
    assert emphasis_readable("#FFD43B")  # the presets' own yellow
    assert not emphasis_readable("#1E3A8A")  # a dark navy is not readable on a dark outline
    assert text_on("#FFD43B") == "#111114" and text_on("#1E3A8A") == "#FFFFFF"


# --- the API ------------------------------------------------------------------------------------


def test_a_creators_first_brand_is_the_default_and_defaults_switch(client, db_session):
    sign_up(client, "brand@example.com")
    first = client.post("/brand/profiles", json={"name": "Amine Clips", "primary_color": "#ff3a72"})
    assert first.status_code == 201
    body = first.json()
    assert body["is_default"] and body["primary_color"] == "#FF3A72" and body["logo"] is None
    second = client.post(
        "/brand/profiles",
        json={"name": "Study", "primary_color": "#0EA5E9", "is_default": True},
    ).json()
    listed = client.get("/brand/profiles").json()
    assert [b["name"] for b in listed] == ["Study", "Amine Clips"]  # the default first
    assert [b["is_default"] for b in listed] == [True, False]
    client.patch(f"/brand/profiles/{body['id']}", json={"is_default": True})
    assert [b["name"] for b in client.get("/brand/profiles").json() if b["is_default"]] == [
        "Amine Clips"
    ]
    assert client.get(f"/brand/profiles/{second['id']}").json()["is_default"] is False


def test_brand_values_are_validated(client, db_session):
    sign_up(client, "valid@example.com")
    bad = client.post("/brand/profiles", json={"name": "A", "primary_color": "pink"})
    assert bad.status_code == 422 and bad.json()["detail"].startswith("Colours are hex values")
    assert (
        client.post("/brand/profiles", json={"name": " ", "primary_color": "#000"}).status_code
        == 422
    )
    long = client.post(
        "/brand/profiles", json={"name": "A", "primary_color": "#000", "end_card_text": "x" * 41}
    )
    assert long.status_code == 422
    created = client.post(
        "/brand/profiles",
        json={
            "name": "  Amine   Clips ",
            "primary_color": "#000",
            "caption_emphasis_color": "#1e3a8a",
            "end_card_text": "  Follow   for more ",
            "logo_position": "bottom_left",
            "logo_size": "large",
        },
    ).json()
    assert created["name"] == "Amine Clips" and created["end_card_text"] == "Follow for more"
    assert created["caption_emphasis_readable"] is False  # kept as an accent, never as text
    dup = client.post("/brand/profiles", json={"name": "Amine Clips", "primary_color": "#111"})
    assert dup.status_code == 409
    cleared = client.patch(
        f"/brand/profiles/{created['id']}", json={"caption_emphasis_color": None}
    ).json()
    assert cleared["caption_emphasis_color"] is None and cleared["logo_size"] == "large"
    assert (
        client.patch(f"/brand/profiles/{created['id']}", json={"primary_color": None}).status_code
        == 422
    )


def test_a_logo_is_one_of_the_creators_own_images(client, db_session):
    sign_up(client, "logo@example.com")
    project = project_for(db_session, "logo@example.com")
    image = visual(db_session, project.id, "logo.png")
    image.has_alpha = True
    clip = video_asset(db_session, project.id)
    sign_up(client, "other@example.com")
    theirs = visual(db_session, project_for(db_session, "other@example.com").id, "theirs.png")
    db_session.commit()
    client.post("/auth/login", json={"email": "logo@example.com", "password": PASSWORD})

    made = client.post(
        "/brand/profiles",
        json={"name": "B", "primary_color": "#000", "logo_asset_id": str(image.id)},
    ).json()
    assert made["logo"]["name"] == "logo.png" and made["logo"]["transparent"] is True
    assert made["logo"]["project_name"] == "Channel"
    video = client.post(
        "/brand/profiles",
        json={"name": "C", "primary_color": "#000", "logo_asset_id": str(clip.id)},
    )
    assert video.status_code == 422
    other = client.post(
        "/brand/profiles",
        json={"name": "D", "primary_color": "#000", "logo_asset_id": str(theirs.id)},
    )
    assert other.status_code == 404
    candidates = client.get("/brand/logo-candidates").json()
    assert [c["name"] for c in candidates] == ["logo.png"]  # images only, own only


def test_brands_are_private(client, db_session):
    sign_up(client, "owner@example.com")
    brand = client.post("/brand/profiles", json={"name": "Mine", "primary_color": "#000"}).json()
    sign_up(client, "intruder@example.com")
    for response in (
        client.get(f"/brand/profiles/{brand['id']}"),
        client.patch(f"/brand/profiles/{brand['id']}", json={"name": "x"}),
        client.delete(f"/brand/profiles/{brand['id']}"),
    ):
        assert response.status_code == 404
    assert client.get("/brand/profiles").json() == []


def test_deleting_never_breaks_anything(client, db_session):
    sign_up(client, "del@example.com")
    project = project_for(db_session, "del@example.com")
    image = visual(db_session, project.id, "logo.png")
    db_session.commit()
    brand = client.post(
        "/brand/profiles",
        json={"name": "B", "primary_color": "#000", "logo_asset_id": str(image.id)},
    ).json()
    # The image cannot be deleted while it is a brand's logo.
    refused = client.delete(f"/projects/{project.id}/visual-assets/{image.id}")
    assert refused.status_code == 409 and "logo of your brand “B”" in refused.json()["detail"]
    # Deleting the image's project only clears the logo.
    client.request("DELETE", f"/projects/{project.id}", json={"confirm_name": "Channel"})
    assert client.get(f"/brand/profiles/{brand['id']}").json()["logo"] is None
    assert client.delete(f"/brand/profiles/{brand['id']}").status_code == 204
    assert client.get("/brand/profiles").json() == []


def test_one_default_per_creator_even_in_a_race(client, db_session):
    sign_up(client, "race@example.com")
    user = me(db_session, "race@example.com")
    db_session.add_all(
        [
            BrandProfile(user_id=user.id, name="A", primary_color="#000000", is_default=True),
            BrandProfile(user_id=user.id, name="B", primary_color="#000000", is_default=True),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_creator_has_at_most_ten_brands(client, db_session):
    sign_up(client, "many@example.com")
    for i in range(profiles.MAX_BRANDS):
        assert (
            client.post(
                "/brand/profiles", json={"name": f"B{i}", "primary_color": "#000"}
            ).status_code
            == 201
        )
    over = client.post("/brand/profiles", json={"name": "Too many", "primary_color": "#000"})
    assert over.status_code == 409
