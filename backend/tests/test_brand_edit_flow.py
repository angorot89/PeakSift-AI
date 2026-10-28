"""Brands and templates in the editor (V1.7): the brand section a Short would use now, edits
that carry a brand (own logo only), and the display-only origin of a version."""

from sqlalchemy import select

from app.models import Project, User
from tests.test_clip_edit_api import PASSWORD, ready_clip, sign_up
from tests.test_copilot_context import visual

PLAIN = {"layout": "blur_background", "captions_enabled": False}


def me(db, email="owner@example.com"):
    return db.scalar(select(User).where(User.email == email))


def test_the_brand_section_comes_from_a_template_the_default_or_the_brand(client, db_session):
    sign_up(client)
    assert client.get("/brand/edit-section").json() == {"brand": None, "template": None}
    project = Project(name="Logos", owner=me(db_session))
    db_session.add(project)
    db_session.flush()
    logo = visual(db_session, project.id, "logo.png")
    db_session.commit()
    brand = client.post(
        "/brand/profiles",
        json={"name": "Amine Clips", "primary_color": "#F43F5E", "logo_asset_id": str(logo.id),
              "end_card_text": "Follow for more"},
    ).json()  # fmt: skip
    plain = client.get("/brand/edit-section").json()
    assert plain["template"] is None  # the default brand: logo on, no end card
    assert plain["brand"]["logo"]["asset_id"] == str(logo.id) and "end_card" not in plain["brand"]
    template = client.post(
        "/brand/templates",
        json={"name": "Punchy Gaming", "recipe": "punchy", "brand_profile_id": brand["id"],
              "config": {"end_card": True, "logo": False}, "is_default": True},
    ).json()  # fmt: skip
    section = client.get("/brand/edit-section").json()
    assert section["template"] == {"id": template["id"], "name": "Punchy Gaming", "version": 1}
    assert "logo" not in section["brand"]  # this template hides the logo
    assert section["brand"]["end_card"] == {
        "seconds": 2.0, "background": "#F43F5E", "text": "Follow for more", "show_logo": False,
    }  # fmt: skip
    sign_up(client, "other@example.com")
    stolen = client.get("/brand/edit-section", params={"template_id": template["id"]})
    assert stolen.status_code == 404


def test_a_branded_edit_records_its_origin_and_uses_only_own_logos(client, db_session):
    sign_up(client)
    data = ready_clip(db_session, "owner@example.com")
    project_id = data["clip"].video.project_id
    mine = visual(db_session, project_id, "logo.png")
    sign_up(client, "other@example.com")
    theirs = visual(
        db_session, ready_clip(db_session, "other@example.com")["clip"].video.project_id, "x.png"
    )
    db_session.commit()
    client.post("/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    template = client.post("/brand/templates", json={"name": "Clean Pro", "recipe": "clean"}).json()
    brand = {
        "name": "Amine Clips",
        "logo": {"asset_id": str(mine.id), "corner": "top_left", "size": "small"},
    }
    made = client.post(
        data["base"], json={**PLAIN, "brand": brand, "origin_template_id": template["id"]}
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["configuration"]["brand"]["logo"]["asset_id"] == str(mine.id)
    assert body["origin"] == {
        "template": {"id": template["id"], "name": "Clean Pro", "version": 1},
        "brand": {"name": "Amine Clips"},
    }
    # Another creator's image as a logo is refused; their template is simply not recorded.
    foreign = {**brand, "logo": {**brand["logo"], "asset_id": str(theirs.id)}}
    assert client.post(data["base"], json={**PLAIN, "brand": foreign}).status_code == 409
    sign_up(client, "third@example.com")
    theirs_template = client.post("/brand/templates", json={"name": "Theirs"}).json()
    client.post("/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    plain = client.post(
        data["base"], json={**PLAIN, "layout": "fit", "origin_template_id": theirs_template["id"]}
    ).json()
    assert plain["origin"] is None
