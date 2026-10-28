"""Short templates (V1.7): validated, normalized editing preferences built from the editor's
own types, recipe starting points, versions that track real changes, one default, duplicates
and owner scoping."""

import pytest

from app.services.auto_edit.recipes import current_recipe
from app.services.branding.template_config import (
    TEMPLATE_CONFIG_VERSION,
    BrollAmount,
    Framing,
    TemplateConfig,
)
from tests.test_clip_edit_api import sign_up

# --- the settings -------------------------------------------------------------------------------


def test_settings_are_normalized_and_versioned():
    config = TemplateConfig.create(
        {
            "framing": "smart_reframe",
            "caption_preset": "punch",
            "caption_position": "bottom",
            "hook_style": "boxed",
            "hook_position": "top",
            "hook_seconds": 2.04,
            "broll": "light",
            "music_level": "low",
            "ducking": "strong",
            "end_card": True,
        }
    )
    snapshot = config.snapshot()
    assert snapshot["version"] == TEMPLATE_CONFIG_VERSION
    assert snapshot["framing"] == "smart_reframe" and snapshot["hook_seconds"] == 2.0
    assert snapshot["end_card_seconds"] == 2.0  # the default length when enabled
    assert TemplateConfig.from_snapshot(snapshot) == config
    # Settings that do not apply are dropped, so equal intent gives one snapshot.
    off = TemplateConfig.create({"captions": False, "caption_preset": "punch", "hook": False})
    assert off.caption_preset is None and off.hook_style is None
    assert TemplateConfig.create({}) == TemplateConfig()  # everything "recipe decides"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"caption_preset": "comic sans"}, "Unsupported caption style"),
        ({"framing": "zoom"}, "Unsupported framing"),
        ({"hook_seconds": 9}, "The hook must be between"),
        ({"end_card": True, "end_card_seconds": 10}, "The end card must be between"),
        ({"captions": "yes"}, "Captions must be true or false"),
        ({"caption_position": "top", "hook_position": "top"}, "cannot share the same position"),
        ({"filter": "drawtext=..."}, "Unknown template setting"),
    ],
)
def test_anything_outside_the_editors_choices_is_refused(data, message):
    with pytest.raises(ValueError, match=message):
        TemplateConfig.create(data)


def test_starting_points_follow_each_recipe():
    for name in ("clean", "punchy", "story", "minimal"):
        recipe = current_recipe(name)
        config = TemplateConfig.from_recipe(recipe)
        assert config.caption_preset == recipe.caption_presets[0]
        assert config.hook_style == recipe.hook_styles[0]
        assert config.sound_effects is (recipe.max_sfx > 0)
        assert config.framing == Framing.AUTO
    assert TemplateConfig.from_recipe(current_recipe("minimal")).broll == BrollAmount.LIGHT


# --- the API ------------------------------------------------------------------------------------


def test_templates_start_from_a_recipe_and_version_real_changes(client, db_session):
    sign_up(client, "tpl@example.com")
    starters = client.get("/brand/template-starters").json()
    assert [s["label"] for s in starters] == ["Clean", "Punchy", "Story", "Minimal"]
    brand = client.post(
        "/brand/profiles", json={"name": "Amine", "primary_color": "#F43F5E"}
    ).json()
    made = client.post(
        "/brand/templates",
        json={"name": "Punchy Gaming", "recipe": "punchy", "brand_profile_id": brand["id"]},
    )
    assert made.status_code == 201
    template = made.json()
    assert template["config"]["caption_preset"] == "punch" and template["version"] == 1
    assert template["brand"] == {
        "id": brand["id"], "name": "Amine", "primary_color": "#F43F5E", "has_logo": False,
    }  # fmt: skip
    url = f"/brand/templates/{template['id']}"
    renamed = client.patch(url, json={"name": "Punchy Gaming 2", "description": " Fast "}).json()
    assert renamed["version"] == 1 and renamed["description"] == "Fast"  # how it edits: same
    changed = client.patch(url, json={"config": {**template["config"], "broll": "none"}}).json()
    assert changed["version"] == 2 and changed["config"]["broll"] == "none"
    same = client.patch(url, json={"config": changed["config"]}).json()
    assert same["version"] == 2  # sending the same settings is not a new version
    assert client.patch(url, json={"brand_profile_id": None}).json()["version"] == 3
    bad = client.patch(url, json={"config": {"caption_preset": "rainbow"}})
    assert bad.status_code == 422 and bad.json()["detail"] == "Unsupported caption style"


def test_one_default_template_duplicates_and_deletion(client, db_session):
    sign_up(client, "lib@example.com")
    first = client.post(
        "/brand/templates", json={"name": "Clean Pro", "recipe": "clean", "is_default": True}
    ).json()
    second = client.post(
        "/brand/templates", json={"name": "Punchy", "recipe": "punchy", "is_default": True}
    ).json()
    listed = client.get("/brand/templates").json()
    assert [(t["name"], t["is_default"]) for t in listed][0] == ("Punchy", True)
    assert client.get(f"/brand/templates/{first['id']}").json()["is_default"] is False
    copy = client.post(f"/brand/templates/{second['id']}/duplicate").json()
    again = client.post(f"/brand/templates/{second['id']}/duplicate").json()
    assert (copy["name"], again["name"]) == ("Punchy copy", "Punchy copy 2")
    assert copy["config"] == second["config"] and not copy["is_default"] and copy["version"] == 1
    assert client.post("/brand/templates", json={"name": "Punchy"}).status_code == 409
    assert client.delete(f"/brand/templates/{second['id']}").status_code == 204
    assert [t["is_default"] for t in client.get("/brand/templates").json()] == [False, False, False]


def test_templates_and_their_brands_are_private(client, db_session):
    sign_up(client, "a@example.com")
    brand = client.post("/brand/profiles", json={"name": "A", "primary_color": "#000"}).json()
    template = client.post("/brand/templates", json={"name": "Mine"}).json()
    sign_up(client, "b@example.com")
    assert client.get(f"/brand/templates/{template['id']}").status_code == 404
    assert client.post(f"/brand/templates/{template['id']}/duplicate").status_code == 404
    stolen = client.post(
        "/brand/templates", json={"name": "Theirs", "brand_profile_id": brand["id"]}
    )
    assert stolen.status_code == 404  # another creator's brand is not found
    assert client.get("/brand/templates").json() == []


def test_deleting_a_brand_leaves_its_templates_without_one(client, db_session):
    sign_up(client, "brandless@example.com")
    brand = client.post("/brand/profiles", json={"name": "B", "primary_color": "#000"}).json()
    template = client.post(
        "/brand/templates", json={"name": "T", "brand_profile_id": brand["id"]}
    ).json()
    client.delete(f"/brand/profiles/{brand['id']}")
    assert client.get(f"/brand/templates/{template['id']}").json()["brand"] is None
