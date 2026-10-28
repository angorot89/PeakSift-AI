"""Ask PeakSift about brands and templates (V1.7): the context lists them by handle, exact
questions get PeakSift's own answers, "use my template" starts Auto Edit for this clip, the
model can open but never change a template, and gone templates are re-checked on click."""

import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.models import ClipEdit, ShortTemplate, User
from app.services.copilot import service
from app.services.copilot.actions import resolve_record
from app.services.copilot.context import build_context
from app.services.copilot.provider import FakeCopilotProvider
from tests.test_clip_edit_api import ready_clip, sign_up
from tests.test_clip_edit_model import make_edit


def me(db, email="owner@example.com"):
    return db.scalar(select(User).where(User.email == email))


def setup(client, db):
    sign_up(client)
    data = ready_clip(db, "owner@example.com")
    brand = client.post(
        "/brand/profiles", json={"name": "Amine Clips", "primary_color": "#F43F5E"}
    ).json()
    template = client.post(
        "/brand/templates",
        json={"name": "Punchy Gaming", "recipe": "punchy", "brand_profile_id": brand["id"],
              "config": {"caption_preset": "boxed", "hook_style": "boxed", "end_card": True},
              "is_default": True},
    ).json()  # fmt: skip
    return data, template


def ask(db, text, **scope):
    fake = FakeCopilotProvider([{"message": "The model answered."}])
    exchange = service.ask(db, me(db), get_settings(), text=text, provider=fake, **scope)
    return exchange.answer, fake


def test_the_context_lists_brands_and_templates_by_handle(client, db_session):
    data, template = setup(client, db_session)
    context = build_context(db_session, me(db_session), get_settings(), page="brand")
    branding = context.view["branding"]
    assert branding["brands"] == [{"name": "Amine Clips", "default": True, "has_logo": False}]
    (listed,) = branding["templates"]
    assert listed["handle"] == "template_1" and listed["default"] is True
    assert (
        listed["settings"]
        == "Boxed captions, Boxed hook, B-roll as the style suggests, end card +2s"
    )
    assert context.targets["template_1"].id == uuid.UUID(template["id"])
    assert template["id"] not in context.view_json()  # never an id


def test_exact_questions_get_peaksifts_own_answers(client, db_session):
    data, template = setup(client, db_session)
    answer, fake = ask(db_session, "What template am I using?", page="brand")
    assert answer.content.startswith("Your default template is “Punchy Gaming” (Boxed captions")
    assert [a["label"] for a in answer.actions] == ["Open “Punchy Gaming”"]
    answer, _ = ask(db_session, "Do I have a default brand?", page="home")
    assert answer.content == "Yes — your default brand is “Amine Clips” (no logo yet)."
    assert [a["type"] for a in answer.actions] == ["open_brand_studio"]
    assert not fake.calls  # none of these reached the model


def test_use_my_template_starts_auto_edit_for_this_clip(client, db_session):
    data, template = setup(client, db_session)
    clip = data["clip"]
    project_id = clip.video.project_id
    answer, _ = ask(
        db_session, "Use my Punchy Gaming template", page="create",
        project_id=project_id, clip_id=clip.id,
    )  # fmt: skip
    assert "Auto Edit with your “Punchy Gaming” template" in answer.content
    (action,) = answer.actions
    assert action["type"] == "use_template" and action["label"] == "Use “Punchy Gaming”"
    href = resolve_record(db_session, me(db_session), action).href
    assert (
        href == f"/projects/{project_id}/clips/{clip.id}/auto-edit?new=1&template={template['id']}"
    )
    # Without a clip on the page: open the template instead.
    elsewhere, _ = ask(db_session, "use the punchy gaming template", page="home")
    assert [a["type"] for a in elsewhere.actions] == ["open_template"]
    # A template deleted since is re-checked on click.
    client.delete(f"/brand/templates/{template['id']}")
    response = client.post(f"/copilot/messages/{answer.id}/actions/0")
    assert response.status_code == 409
    assert response.json()["detail"] == "This template is no longer available."


def test_why_a_short_differs_from_its_template(client, db_session):
    data, template = setup(client, db_session)
    clip = data["clip"]
    edit = make_edit(db_session, clip, status="ready", storage_key=f"edits/{uuid.uuid4()}.mp4",
                     file_size=10, duration_seconds=20.0)  # fmt: skip
    edit.config = {
        **edit.config,
        "captions": {"enabled": True, "style": "focus", "position": "bottom"},
    }
    edit.origin = {
        "template": {"id": template["id"], "name": "Punchy Gaming", "version": 1},
        "brand": {"name": "Amine Clips"},
    }
    db_session.commit()
    client.patch(
        f"/brand/templates/{template['id']}", json={"config": {"caption_preset": "minimal"}}
    )
    scope = {"page": "editor", "project_id": clip.video.project_id, "clip_id": clip.id,
             "edit_id": edit.id}  # fmt: skip
    using, _ = ask(db_session, "What template am I using?", **scope)
    assert (
        using.content
        == "This Short started from your “Punchy Gaming” template with your “Amine Clips” brand."
    )
    why, _ = ask(db_session, "Why does this Short look different from my template?", **scope)
    assert "changed after this Short was made (version 1 → 2)" in why.content
    assert "captions are Focus here (template: Minimal)" in why.content
    db_session.execute(ShortTemplate.__table__.delete())
    db_session.commit()
    gone, _ = ask(db_session, "Why does this Short look different from my template?", **scope)
    assert "has since been deleted" in gone.content
    assert db_session.get(ClipEdit, edit.id).config["captions"]["style"] == "focus"  # untouched


def test_the_model_can_open_but_never_use_or_change_templates(client, db_session):
    data, template = setup(client, db_session)
    fake = FakeCopilotProvider(
        [
            {
                "message": "Punchy Gaming fits this short reaction clip — a suggestion.",
                "actions": [
                    {"type": "use_template", "handle": "template_1"},
                    {"type": "delete_template", "handle": "template_1"},
                    {"type": "open_template", "handle": "template_1"},
                ],
            }
        ]
    )
    exchange = service.ask(
        db_session, me(db_session), get_settings(), text="Tell me about my templates.",
        page="create", project_id=data["clip"].video.project_id, clip_id=data["clip"].id,
        provider=fake,
    )  # fmt: skip
    assert [a["type"] for a in exchange.answer.actions] == ["open_template"]
    prompt = fake.calls[0][0]["content"]
    assert (
        "say it is a suggestion" in prompt
        and "Never claim a template will perform better" in prompt
    )


def test_which_template_fits_is_a_labelled_suggestion(client, db_session):
    data, template = setup(client, db_session)
    client.post("/brand/templates", json={"name": "Calm Explainer", "recipe": "clean"})
    clip = data["clip"]
    clip.candidate.category = "humor"
    db_session.commit()
    answer, fake = ask(
        db_session, "Which template fits this clip?", page="create",
        project_id=clip.video.project_id, clip_id=clip.id,
    )  # fmt: skip
    assert answer.content.startswith("“Punchy Gaming” is a reasonable fit because this is a")
    assert "funny moment and it starts from the Punchy style." in answer.content
    assert "This is a suggestion, not a prediction." in answer.content
    assert "isn't large enough to prefer one statistically" in answer.content
    assert [a["type"] for a in answer.actions] == ["use_template"]
    assert not fake.calls
