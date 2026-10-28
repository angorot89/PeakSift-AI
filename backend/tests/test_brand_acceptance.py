"""V1.7 acceptance journeys through the API (deterministic planner): a fresh creator from a
brand and a template to a branded version, historical safety after the template and brand
change, and two templates on the same clip. The same journeys run with the real local model
and real renders on the review stack (see docs/brand-studio.md, *Acceptance*)."""

from tests.test_auto_edit_api import clip_ctx, fake_queues, plan_now  # noqa: F401
from tests.test_clip_edit_api import sign_up
from tests.test_copilot_context import visual


def make_brand_and_template(client, db_session, ctx, **config):
    logo = visual(db_session, ctx["clip"].video.project_id, "logo.png")
    logo.has_alpha = True
    db_session.commit()
    brand = client.post(
        "/brand/profiles",
        json={
            "name": "Amine Clips",
            "primary_color": "#F43F5E",
            "caption_emphasis_color": "#FFD43B",
            "logo_asset_id": str(logo.id),
            "logo_position": "top_right",
            "end_card_text": "Follow for more",
        },
    ).json()
    settings = {"caption_preset": "punch", "hook_style": "boxed", "end_card": True, **config}
    template = client.post(
        "/brand/templates",
        json={
            "name": "Punchy Gaming",
            "recipe": "punchy",
            "brand_profile_id": brand["id"],
            "config": settings,
            "is_default": True,
        },
    ).json()
    return logo, brand, template


def plan_and_apply(client, db_session, ctx, template_id):
    plan_id = client.post(ctx["base"], json={"template_id": template_id}).json()["id"]
    plan_now(db_session, plan_id)
    plan = client.get(f"{ctx['base']}/{plan_id}").json()
    edit = client.post(f"{ctx['base']}/{plan_id}/apply").json()["edit"]
    return plan, edit


def test_a_fresh_creator_gets_a_branded_short_from_their_template(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    assert client.get("/brand/templates").json() == []  # nothing forced at sign-up
    logo, brand, template = make_brand_and_template(client, db_session, ctx)
    plan, edit = plan_and_apply(client, db_session, ctx, template["id"])
    assert plan["explanations"]["template"]["summary"] == (
        "Started from your Punchy Gaming template. Used your Amine Clips brand."
    )
    config = edit["configuration"]
    assert config["captions"]["style"] == "punch"
    assert config["brand"]["logo"] == {
        "asset_id": str(logo.id),
        "corner": "top_right",
        "size": "small",
    }
    assert config["brand"]["caption_emphasis"] == "#FFD43B"
    assert config["brand"]["end_card"] == {
        "seconds": 2.0, "background": "#F43F5E", "text": "Follow for more", "show_logo": True,
    }  # fmt: skip
    assert edit["origin"]["template"] == {
        "id": template["id"],
        "name": "Punchy Gaming",
        "version": 1,
    }


def test_old_shorts_never_change_when_the_template_or_brand_does(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    _, brand, template = make_brand_and_template(client, db_session, ctx)
    _, first = plan_and_apply(client, db_session, ctx, template["id"])
    before = first["configuration"]
    client.patch(
        f"/brand/templates/{template['id']}",
        json={"config": {**template["config"], "caption_preset": "minimal", "end_card": False}},
    )
    client.patch(f"/brand/profiles/{brand['id']}", json={"primary_color": "#0EA5E9"})
    reopened = client.get(f"{ctx['edits']}/{first['id']}").json()
    assert reopened["configuration"] == before  # the old version is exactly as it was made
    assert reopened["origin"]["template"]["version"] == 1
    _, second = plan_and_apply(client, db_session, ctx, template["id"])
    assert second["configuration"]["captions"]["style"] == "minimal"  # new values apply
    assert "end_card" not in second["configuration"]["brand"]
    assert second["origin"]["template"]["version"] == 2


def test_two_templates_make_two_different_shorts_of_one_clip(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    _, brand, punchy = make_brand_and_template(client, db_session, ctx)
    clean = client.post(
        "/brand/templates",
        json={"name": "Clean Professional", "recipe": "clean", "brand_profile_id": brand["id"],
              "config": {"framing": "fit", "caption_preset": "minimal", "hook_style": "minimal",
                         "broll": "none", "logo": False, "end_card": False}},
    ).json()  # fmt: skip
    _, a = plan_and_apply(client, db_session, ctx, punchy["id"])
    _, b = plan_and_apply(client, db_session, ctx, clean["id"])
    assert a["id"] != b["id"]
    assert (a["configuration"]["captions"]["style"], b["configuration"]["captions"]["style"]) == (
        "punch",
        "minimal",
    )
    assert b["configuration"]["layout"] == "fit"
    assert "logo" in a["configuration"]["brand"] and "logo" not in b["configuration"].get(
        "brand", {}
    )
