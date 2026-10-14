"""The opening hook overlay: validation, layout, escaping, configuration, persistence, API and
real burned-in renders (it appears in the safe area and disappears on schedule)."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import ClipEdit
from app.services.clip_edit.caption_styles import build_ass_document
from app.services.clip_edit.composition import CAPTIONS_FILENAME, compose_short
from app.services.clip_edit.config import CaptionPosition, CaptionStyle, EditConfig, Layout
from app.services.clip_edit.hook import (
    DEFAULT_HOOK_SECONDS,
    MAX_HOOK_CHARS,
    HookConfig,
    HookPosition,
    HookStyle,
    hook_ass,
    hook_lines,
)
from app.services.clip_edit.safe_area import GENERAL_SOCIAL
from tests.media_fixtures import requires_ffmpeg, requires_libass
from tests.test_clip_edit_api import ready_clip, sign_up
from tests.test_clip_edit_caption_render import crop, difference, options, plain_source
from tests.test_clip_edit_model import make_clip, make_edit
from tests.test_clip_edit_pipeline import SpyComposer, execute, settings, storage  # noqa: F401 - fixtures
from tests.test_clip_edit_pipeline import make_edit as make_pipeline_edit


def hook(**kwargs) -> HookConfig:
    fields = {
        "text": "This changed how I think",
        "style": "headline",
        "position": "top",
        "duration": 2.0,
    }
    fields.update(kwargs)
    return HookConfig.create(**fields)


# --- validation -----


def test_text_is_normalized_and_kept_exactly():
    config = hook(text="  This changed\nhow I   think  ")
    assert config.text == "This changed how I think"
    assert hook(text="C'était {fou} \\N مرحبا 🔥").text == "C'était {fou} \\N مرحبا 🔥"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"text": "   "}, "needs some text"),
        ({"text": "x" * (MAX_HOOK_CHARS + 1)}, "at most"),
        ({"text": "W" * 40}, "too long to fit"),  # one huge word
        ({"duration": 0.4}, "seconds"),
        ({"duration": 5.1}, "seconds"),
        ({"duration": float("nan")}, "number"),
        ({"duration": True}, "number"),
    ],
)
def test_invalid_hooks_are_refused(kwargs, message):
    with pytest.raises(ValueError, match=message):
        hook(**kwargs)


@pytest.mark.parametrize("field", ["style", "position"])
def test_only_allow_listed_styles_and_positions(field):
    with pytest.raises(ValueError):
        hook(**{field: "evil"})


def test_defaults_and_rounding():
    config = HookConfig.create(text="Watch this", style=None, position=None, duration=None)
    assert (config.style, config.position, config.duration) == (
        HookStyle.HEADLINE,
        HookPosition.TOP,
        DEFAULT_HOOK_SECONDS,
    )
    assert hook(duration=1.96).duration == 2.0


def test_three_line_hooks_are_balanced_without_a_lone_word():
    text = "Nobody tells you what the first night in orbit feels like!"
    lines = hook_lines(hook(text=text, style="headline"))
    assert lines == ["Nobody tells you", "what the first night", "in orbit feels like!"]
    assert " ".join(lines) == text


def test_lines_are_balanced_and_bounded():
    assert hook_lines(hook(text="Wait for it")) == ["Wait for it"]
    two = hook_lines(hook(text="Nobody tells you what the first night feels like"))
    assert len(two) == 2 and all(two)
    long_text = "The hardest lesson came during a spacewalk, halfway out"
    assert 2 <= len(hook_lines(hook(text=long_text, style="boxed"))) <= 3


# --- ASS -----


def test_hook_ass_is_escaped_timed_and_placed_in_the_safe_area():
    style, event = hook_ass(
        hook(text="{\\an1\\c&H0000FF&}hack \\N", duration=2.5), font_family="Noto Sans"
    )
    fields = style.removeprefix("Style: ").split(",")
    assert (
        fields[0] == "Hook" and fields[18] == "8" and fields[21] == str(GENERAL_SOCIAL.px()["top"])
    )
    assert event.startswith("Dialogue: 1,0:00:00.00,0:00:02.50,Hook,")
    body = event.split(",", 9)[9]
    assert body.startswith("{\\fad(150,200)}")
    rest = body.removeprefix("{\\fad(150,200)}")
    # The user's "\\N" and override tags stay inert text: every backslash they typed is followed
    # by a word joiner, and their braces are escaped (no override block can open).
    assert "{" not in rest.replace("\\{", "") and "\\\u2060an1" in rest and "\\\u2060N" in rest
    center_style, _ = hook_ass(hook(position="center"), font_family="Noto Sans")
    assert center_style.split(",")[18] == "5"


def test_v1_documents_are_unchanged_without_extras():
    from app.services.clip_edit.captions import Cue

    cues = [Cue(0.5, 1.5, "hello")]
    base = build_ass_document(
        cues, style=CaptionStyle.BOLD, position=CaptionPosition.BOTTOM, font_family="Noto Sans"
    )
    same = build_ass_document(
        cues,
        style=CaptionStyle.BOLD,
        position=CaptionPosition.BOTTOM,
        font_family="Noto Sans",
        extra_styles=(),
        extra_events=(),
    )
    assert base == same and "Hook" not in base


# --- configuration -----


def test_edits_without_a_hook_keep_their_v06_fingerprints():
    center = EditConfig.create(layout="center_crop", captions_enabled=False)
    blur = EditConfig.create(
        layout="blur_background",
        captions_enabled=True,
        caption_style="bold",
        caption_position="bottom",
    )
    assert center.fingerprint().startswith("4c0faecd") and blur.fingerprint().startswith("a8c24dde")
    assert "hook" not in blur.snapshot()


def test_a_hook_is_part_of_the_snapshot_and_fingerprint():
    plain = EditConfig.create(layout="center_crop", captions_enabled=False)
    with_hook = EditConfig.create(
        layout="center_crop",
        captions_enabled=False,
        hook_enabled=True,
        hook_text="Watch this",
        hook_style="boxed",
    )
    assert with_hook.snapshot()["hook"] == {
        "text": "Watch this",
        "style": "boxed",
        "position": "top",
        "duration": 2.0,
    }
    assert with_hook.fingerprint() != plain.fingerprint()
    assert EditConfig.from_snapshot(with_hook.snapshot()) == with_hook
    longer = EditConfig.create(
        layout="center_crop",
        captions_enabled=False,
        hook_enabled=True,
        hook_text="Watch this",
        hook_style="boxed",
        hook_duration=3,
    )
    assert longer.fingerprint() != with_hook.fingerprint()


def test_hook_options_are_ignored_when_the_hook_is_off():
    a = EditConfig.create(layout="fit", captions_enabled=False)
    b = EditConfig.create(
        layout="fit",
        captions_enabled=False,
        hook_enabled=False,
        hook_text="ignored",
        hook_style="boxed",
    )
    assert a.fingerprint() == b.fingerprint()


@pytest.mark.parametrize("position", ["top", "center"])
def test_hook_and_captions_cannot_share_a_position(position):
    with pytest.raises(ValueError, match="same position"):
        EditConfig.create(
            layout="fit",
            captions_enabled=True,
            caption_position=position,
            hook_enabled=True,
            hook_text="Hi",
            hook_position=position,
        )
    ok = EditConfig.create(
        layout="fit",
        captions_enabled=True,
        caption_position="bottom",
        hook_enabled=True,
        hook_text="Hi",
        hook_position=position,
    )
    assert ok.hook is not None


# --- persistence -----


@pytest.mark.parametrize(
    "overrides",
    [
        {"hook_enabled": True},  # no text/style/position/duration
        {
            "hook_enabled": True,
            "hook_text": "Hi",
            "hook_style": "headline",
            "hook_position": "top",
            "hook_duration_seconds": 6.0,
        },
        {
            "hook_enabled": True,
            "hook_text": "Hi",
            "hook_style": "neon",
            "hook_position": "top",
            "hook_duration_seconds": 2.0,
        },
        {
            "hook_enabled": True,
            "hook_text": "Hi",
            "hook_style": "headline",
            "hook_position": "bottom",
            "hook_duration_seconds": 2.0,
        },
        {"hook_enabled": False, "hook_text": "leftover"},
    ],
)
def test_hook_columns_are_constrained(db_session, overrides):
    with pytest.raises(IntegrityError):
        make_edit(db_session, make_clip(db_session), **overrides)
    db_session.rollback()


def test_existing_style_edits_default_to_no_hook(db_session):
    edit = make_edit(db_session, make_clip(db_session))
    assert edit.hook_enabled is False and edit.hook_text is None


# --- API -----


def test_api_creates_validates_and_deduplicates_hooks(client, db_session):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    body = {
        "layout": "center_crop",
        "captions_enabled": True,
        "caption_position": "bottom",
        "hook_enabled": True,
        "hook_text": "{\\an1}This changed\nhow I think",
        "hook_style": "boxed",
        "hook_position": "top",
        "hook_duration_seconds": 2.5,
    }
    first = client.post(ctx["base"], json=body)
    assert first.status_code == 201
    data = first.json()
    assert data["hook_enabled"] is True and data["hook_text"] == "{\\an1}This changed how I think"
    assert (data["hook_style"], data["hook_position"], data["hook_duration_seconds"]) == (
        "boxed",
        "top",
        2.5,
    )
    assert client.post(ctx["base"], json=body).status_code == 200  # same settings: same edit
    for bad in (
        {"hook_text": "x" * 61},
        {"hook_duration_seconds": 9},
        {"hook_style": "neon"},
        {"hook_position": "bottom"},
        {"hook_text": ""},
        {"caption_position": "top"},  # collides with the hook
    ):
        response = client.post(ctx["base"], json={**body, **bad})
        assert response.status_code == 422, bad
    row = db_session.get(ClipEdit, uuid.UUID(data["id"]))
    assert row.config["hook"]["text"] == "{\\an1}This changed how I think"


# --- pipeline and real renders -----


def test_pipeline_writes_the_hook_even_without_captions(db_session, settings, storage):  # noqa: F811
    edit = make_pipeline_edit(db_session, storage, captions=False)
    config = EditConfig.create(
        layout="blur_background",
        captions_enabled=False,
        hook_enabled=True,
        hook_text="Watch this",
        hook_style="minimal",
    )
    edit.config, edit.config_fingerprint = config.snapshot(), config.fingerprint()
    edit.hook_enabled, edit.hook_text, edit.hook_style = True, "Watch this", "minimal"
    edit.hook_position, edit.hook_duration_seconds = "top", 2.0
    db_session.commit()
    composer = SpyComposer(db_session, edit)
    execute(edit, db_session, settings, storage, composer)
    assert composer.calls[0]["captions"] is True  # the text layer is burned in
    text = composer.captions_text
    assert "Style: Hook,Noto Sans,72," in text and "Dialogue: 1,0:00:00.00,0:00:02.00,Hook," in text
    assert not [
        line for line in text.splitlines() if line.startswith("Dialogue: 0,")
    ]  # no captions


@requires_ffmpeg
@requires_libass
@pytest.mark.parametrize("style", list(HookStyle))
def test_rendered_hook_appears_in_the_top_safe_area_and_leaves_on_schedule(tmp_path: Path, style):
    config = hook(text="This changed how I think", style=style.value, duration=1.5)
    source = plain_source(tmp_path / "src.mp4", seconds=3.0)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    hook_style, hook_event = hook_ass(config, font_family="Noto Sans")
    (workspace / CAPTIONS_FILENAME).write_text(
        build_ass_document(
            [],
            style=CaptionStyle.BOLD,
            position=CaptionPosition.BOTTOM,
            font_family="Noto Sans",
            extra_styles=[hook_style],
            extra_events=[hook_event],
        ),
        encoding="utf-8",
    )
    short = compose_short(
        source,
        workspace / "short.mp4",
        layout=Layout.CENTER_CROP,
        options=options(),
        workspace=workspace,
        captions=True,
    )
    top = GENERAL_SOCIAL.px()["top"]
    band = (top - 20, 360)  # just above the safe top edge to well below it
    during = crop(short.path, 0.8, 0, band[0], 1080, band[1])
    after = crop(short.path, 2.4, 0, band[0], 1080, band[1])
    assert difference(during, after) > 2, style  # visible during the hook, gone afterwards
    above = crop(short.path, 0.8, 0, 0, 1080, top - 30)
    assert (
        difference(above, crop(short.path, 2.4, 0, 0, 1080, top - 30)) < 0.2
    )  # nothing above the safe area
