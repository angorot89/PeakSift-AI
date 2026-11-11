"""Morocco template pack (V1.8): curated formats made only of existing settings, offered first in
Morocco Mode next to the Global starters (never instead of them), never in Global mode, and
turned into the creator's own versioned templates."""

from app.services.branding.market_starters import MARKET_STARTERS
from app.services.branding.template_config import TemplateConfig
from tests.test_clip_edit_api import sign_up

GLOBAL_KEYS = ["clean", "punchy", "story", "minimal"]


def test_global_mode_sees_exactly_the_global_starters(client):
    sign_up(client, "global-templates@example.com")
    starters = client.get("/brand/template-starters").json()
    assert [s["key"] for s in starters] == GLOBAL_KEYS
    assert {s["market"] for s in starters} == {"global"}


def test_morocco_mode_puts_its_formats_first_and_keeps_every_global_one(client):
    sign_up(client, "ma-templates@example.com")
    starters = client.get("/brand/template-starters", params={"market": "ma"}).json()
    keys = [s["key"] for s in starters]
    assert keys[: len(MARKET_STARTERS)] == [s.key for s in MARKET_STARTERS]
    assert keys[len(MARKET_STARTERS) :] == GLOBAL_KEYS  # Global never hidden
    labels = [s["label"] for s in starters[:4]]
    assert labels == ["Morocco Vox Pop", "Darija Reaction", "Local Storytime", "Lesson / Explainer"]
    for starter in starters:
        # Only settings the editor already supports; nothing claims to be "trending".
        assert TemplateConfig.from_snapshot(starter["config"]).snapshot() == starter["config"]
        assert "trend" not in (starter["label"] + starter["description"]).lower()
    assert client.get("/brand/template-starters", params={"market": "xx"}).status_code == 422


def test_the_formats_really_differ_in_what_they_configure():
    by_key = {s.key: s.config() for s in MARKET_STARTERS}
    assert by_key["ma_vox_pop"]["broll"] == "none" and by_key["ma_vox_pop"]["framing"] == (
        "smart_reframe"
    )  # fmt: skip
    assert by_key["ma_product_showcase"]["end_card"] is True
    assert by_key["ma_talking_head"]["hook"] is False
    assert len({str(sorted(c.items())) for c in by_key.values()}) == len(by_key)


def test_a_format_becomes_the_creators_own_versioned_template(client):
    sign_up(client, "vox@example.com")
    starter = client.get("/brand/template-starters", params={"market": "ma"}).json()[0]
    created = client.post("/brand/templates", json={
        "name": starter["label"], "description": starter["description"],
        "recipe": starter["recipe"], "config": starter["config"], "market": "ma",
    })  # fmt: skip
    assert created.status_code == 201
    template = created.json()
    assert (template["market"], template["version"]) == ("ma", 1)
    boxed = {**starter["config"], "caption_preset": "boxed"}
    changed = client.patch(f"/brand/templates/{template['id']}", json={"config": boxed})
    assert changed.json()["version"] == 2 and changed.json()["market"] == "ma"
    assert client.post("/brand/templates", json={"name": "Bad", "market": "zz"}).status_code == 422
    plain = client.post("/brand/templates", json={"name": "Mine", "recipe": "clean"}).json()
    assert plain["market"] == "global"
    client.cookies.clear()
    sign_up(client, "not-vox@example.com")
    assert client.get(f"/brand/templates/{template['id']}").status_code == 404
