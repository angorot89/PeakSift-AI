"""Auto Edit with Short templates and brands (V1.7): the template is applied after the
server validated the planner's proposal, so the model never overrides it; what a template
cannot force falls back with a note; plans freeze the template; applied versions record
where they came from."""

import uuid

from sqlalchemy import select

from app.models import ClipEdit, ShortTemplate
from app.services.auto_edit.template import apply_template
from app.services.branding.template_config import TemplateConfig
from tests.test_auto_edit_api import clip_ctx, fake_queues, plan_now  # noqa: F401
from tests.test_auto_edit_validation import MUSIC_HANDLE, ctx, validate
from tests.test_clip_edit_api import sign_up

BRAND = {
    "name": "Amine Clips",
    "logo": {"asset_id": str(uuid.uuid4()), "corner": "top_right", "size": "small"},
    "caption_emphasis": "#FFD43B",
    "hook_accent": "#F43F5E",
}


def template(name="Punchy Gaming", brand=BRAND, **settings):
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "version": 3,
        "recipe": "punchy",
        "config": TemplateConfig.create(settings).snapshot(),
        "brand": brand,
    }


def applied(plan_template, context=None, **proposal_changes):
    context = context or ctx()
    return apply_template(validate(context=context, **proposal_changes), plan_template, context)


def snapshot(plan):
    return plan.configuration.snapshot()


# --- precedence ----------------------------------------------------------------------------------


def test_the_template_wins_over_the_planner_and_the_recipe():
    plan = applied(
        template(
            framing="blur_background", caption_preset="minimal", caption_position="center",
            hook_style="boxed", hook_seconds=1.5, broll="none",
        )
    )  # fmt: skip
    got = snapshot(plan)
    assert got["layout"] == "blur_background" and "reframe" not in got
    assert got["captions"]["style"] == "minimal"  # the planner said Punch
    assert got["captions"]["position"] == "center"
    assert got["hook"]["style"] == "boxed" and got["hook"]["duration"] == 1.5
    assert got["hook"]["text"] == "Our bridge collapsed"  # words still from the clip
    assert "visuals" not in got
    assert got["brand"]["logo"]["corner"] == "top_right"
    assert got["brand"]["hook_accent"] == "#F43F5E"  # a Boxed hook takes the brand accent
    summary = plan.explanations["template"]
    assert (
        summary["summary"]
        == "Started from your Punchy Gaming template. Used your Amine Clips brand."
    )
    assert (summary["name"], summary["version"]) == ("Punchy Gaming", 3)
    assert "Your template uses no B-roll" in plan.explanations["notes"][-1]


def test_sections_the_template_changed_describe_the_render_not_the_planner():
    """V1.8 QA: a Vox Pop plan said "We used the headline style" over a boxed hook. A section
    the template changed is described from the final settings and credited to the template."""
    plain = validate()
    plan = applied(
        template(framing="blur_background", caption_preset="minimal", caption_position="center",
                 hook_style="boxed", hook_seconds=1.5, broll="none")
    )  # fmt: skip
    sections, got = plan.explanations["sections"], snapshot(plan)
    assert sections["captions"]["choice"].startswith("Minimal captions · center")
    assert sections["captions"]["reason"] == "Set by your Punchy Gaming template."
    hook = got["hook"]
    assert sections["hook"]["choice"] == f"“{hook['text']}” · 1.5 s · {hook['position']}"
    assert (
        sections["hook"]["reason"] == "The clip's own words, styled by your Punchy Gaming template."
    )
    assert sections["visuals"] == {
        "choice": "No visuals",
        "reason": "Set by your Punchy Gaming template.",
    }
    assert sections["layout"]["choice"] == "Blur background"
    # A section the template left alone keeps the planner's (validated) explanation.
    assert sections["audio"] == plain.explanations["sections"]["audio"]


def test_empty_settings_keep_the_planners_choices_with_the_brand():
    plain = validate()
    plan = applied(template(brand=None))
    assert {k: v for k, v in snapshot(plan).items()} == plain.configuration.snapshot()
    assert plan.explanations["template"]["summary"] == "Started from your Punchy Gaming template."
    assert plan.explanations["sections"] == plain.explanations["sections"]


def test_what_a_template_cannot_force_falls_back_with_a_note():
    no_analysis = ctx(reframe_analysis_id=None)
    plan = applied(template(framing="smart_reframe", brand=None), context=no_analysis)
    assert snapshot(plan)["layout"] != "smart_reframe"
    assert "prefers Smart Reframe" in plan.explanations["notes"][-1]
    no_hook = applied(template(brand=None, hook=True), hook__enabled=False)
    assert "hook" not in snapshot(no_hook)
    assert "no line from this clip worked" in no_hook.explanations["notes"][-1]


def test_captions_off_light_broll_and_collisions():
    off = snapshot(applied(template(brand=None, captions=False)))
    assert off["captions"] == {"enabled": False, "style": None, "position": None}
    # Captions at the top and the planner's hook at the top: the hook moves to the centre.
    top = snapshot(applied(template(brand=None, caption_position="top")))
    assert top["captions"]["position"] == "top" and top["hook"]["position"] == "center"


def test_music_is_never_added_only_levelled():
    without = snapshot(applied(template(brand=None, music_level="medium", sound_effects=False)))
    assert (without.get("audio") or {}).get("music") is None
    audio = {"use_music": True, "music_level": "low", "ducking": "medium",
             "transition_sounds": True}  # fmt: skip
    plan = applied(
        template(brand=None, music_level="medium", ducking="strong", sound_effects=False),
        context=ctx(),
        audio=audio,
    )
    mix = snapshot(plan)["audio"]
    assert mix["music"]["gain_db"] == -16.0 and mix["music"]["ducking"] == "strong"
    assert not mix.get("sfx")
    assert MUSIC_HANDLE  # the creator's own choice of track stays the only source of music


# --- the API -------------------------------------------------------------------------------------


def make_template(client, **body):
    payload = {"name": "Punchy Gaming", "recipe": "story", **body}
    return client.post("/brand/templates", json=payload).json()


def test_plans_freeze_the_template_and_versions_record_their_origin(client, db_session):
    sign_up(client)
    brand = client.post(
        "/brand/profiles", json={"name": "Amine Clips", "primary_color": "#F43F5E"}
    ).json()
    made = make_template(
        client,
        brand_profile_id=brand["id"],
        config={"caption_preset": "boxed", "end_card": True, "end_card_seconds": 1.5},
    )
    ctx = clip_ctx(db_session)
    created = client.post(ctx["base"], json={"template_id": made["id"]})
    assert created.status_code == 201
    plan_id = created.json()["id"]
    assert created.json()["recipe"] == "story"  # the template's starting style
    # Editing the template after asking does not change the plan.
    client.patch(f"/brand/templates/{made['id']}", json={"config": {"caption_preset": "minimal"}})
    plan_now(db_session, plan_id)
    plan = client.get(f"{ctx['base']}/{plan_id}").json()
    assert plan["configuration"]["captions"]["style"] == "boxed"
    assert plan["configuration"]["brand"]["end_card"]["seconds"] == 1.5
    assert plan["explanations"]["template"]["version"] == 1
    edit = client.post(f"{ctx['base']}/{plan_id}/apply").json()["edit"]
    assert edit["origin"]["template"] == {"id": made["id"], "name": "Punchy Gaming", "version": 1}
    assert edit["origin"]["brand"] == {"name": "Amine Clips"}
    # Deleting the template and brand never changes the version.
    client.delete(f"/brand/templates/{made['id']}")
    client.delete(f"/brand/profiles/{brand['id']}")
    row = db_session.get(ClipEdit, uuid.UUID(edit["id"]))
    db_session.refresh(row)
    assert row.config["brand"]["end_card"]["background"] == "#F43F5E"
    assert db_session.scalar(select(ShortTemplate)) is None


def test_templates_are_owner_scoped_and_regenerate_keeps_them(client, db_session):
    sign_up(client, "other@example.com")
    theirs = make_template(client, name="Theirs")
    sign_up(client)
    ctx = clip_ctx(db_session)
    assert client.post(ctx["base"], json={"template_id": theirs["id"]}).status_code == 404
    assert client.post(ctx["base"], json={}).status_code == 422  # a recipe or a template
    mine = make_template(client, name="Mine", recipe="minimal")
    plan_id = client.post(ctx["base"], json={"template_id": mine["id"]}).json()["id"]
    plan_now(db_session, plan_id)
    again = client.post(f"{ctx['base']}/{plan_id}/regenerate").json()
    plan_now(db_session, again["id"])
    regenerated = client.get(f"{ctx['base']}/{again['id']}").json()
    assert regenerated["explanations"]["template"]["name"] == "Mine"
