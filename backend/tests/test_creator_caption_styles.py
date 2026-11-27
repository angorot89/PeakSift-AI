"""Creator caption styles (V2.0): the styles API, fonts on this server, and edits using them."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models import ClipEditStatus
from app.services.clip_edit.caption_fonts import CAPTION_FONTS, font_file, line_metrics
from app.services.clip_edit.composition import compose_short
from app.services.clip_edit.config import EditConfig
from app.services.clip_edit.pipeline import run_clip_edit
from tests.media_fixtures import requires_ffmpeg, requires_libass
from tests.test_clip_edit_api import ready_clip, sign_up
from tests.test_clip_edit_pipeline import (  # noqa: F401 (fixtures)
    clean_media_root,
    make_edit,
    settings,
    storage,
)

FONTS_DIR = get_settings().caption_fonts_dir
HAVE_FONTS = all(font_file(key, FONTS_DIR) for key in CAPTION_FONTS)


def test_every_font_is_pinned_to_one_file_with_its_licence():
    for font in CAPTION_FONTS.values():
        assert font.repo_path.startswith(("ofl/", "apache/")) and font.repo_path.endswith(".ttf")
        assert font.licence in ("OFL-1.1", "Apache-2.0")
        assert len(font.sha256) == 64 and len(font.licence_sha256) == 64
        assert font.licence_path.rsplit("/", 1)[0] == font.repo_path.rsplit("/", 1)[0]
    assert {"arabic", "latin"} <= set(CAPTION_FONTS["lalezar"].scripts)


def test_a_file_that_differs_from_the_pin_is_never_used(tmp_path):
    (tmp_path / "Anton-Regular.ttf").write_bytes(b"not the pinned font")
    assert font_file("anton", tmp_path) is None
    assert font_file("not-a-font", tmp_path) is None


@pytest.mark.skipif(not HAVE_FONTS, reason="caption style fonts not installed")
def test_line_metrics_are_read_from_the_font():
    path = font_file("anton", FONTS_DIR)
    assert line_metrics(path.read_bytes()) == (2048, 2876, 674)


def test_one_word_and_reveal_need_word_timing():
    for style in ("one_word", "reveal"):
        with pytest.raises(ValueError, match="word timing"):
            EditConfig.create(
                layout="center_crop",
                captions_enabled=True,
                caption_style=style,
                caption_timing="phrase_fallback",
            )
    # Other creator styles may use phrase timing (they simply have no spoken word then).
    EditConfig.create(
        layout="center_crop",
        captions_enabled=True,
        caption_style="pop",
        caption_timing="phrase_fallback",
    )


def test_styles_api_describes_every_style(client: TestClient):
    sign_up(client)
    presets = {p["name"]: p for p in client.get("/caption-styles").json()["presets"]}
    assert len(presets) == 14
    assert presets["focus"]["font"] is None and presets["focus"]["available"] is True
    assert presets["pop"]["font"] == "Anton" and presets["pop"]["pop"] == 116
    assert presets["marker"]["highlight"] == "marker" and presets["marker"]["marker"]
    assert presets["one_word"]["one_word"] and presets["one_word"]["needs_word_timing"]
    assert presets["reveal"]["reveal"] and presets["bold_arabic"]["scripts"] == ["arabic", "latin"]
    assert presets["pop"]["available"] is HAVE_FONTS
    if HAVE_FONTS:
        assert presets["pop"]["em_per_size"] == pytest.approx(2048 / (2876 + 674), abs=1e-4)
    for leak in ("fonts/", ".ttf", "sha256", "githubusercontent"):
        assert leak not in str(presets)


def test_a_style_whose_font_is_missing_is_refused(client, db_session, monkeypatch, tmp_path):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    monkeypatch.setenv("CAPTION_FONTS_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        body = {
            "layout": "blur_background",
            "captions_enabled": True,
            "caption_style": "comic",
            "caption_position": "bottom",
            "caption_timing": "phrase_fallback",
        }
        response = client.post(ctx["base"], json=body)
        assert response.status_code == 409 and "font" in response.json()["detail"]
        assert "/" not in response.json()["detail"]  # no path in the message
        styles = {p["name"]: p for p in client.get("/caption-styles").json()["presets"]}
        assert styles["comic"]["available"] is False and styles["focus"]["available"] is True
    finally:
        get_settings.cache_clear()


@pytest.mark.skipif(not HAVE_FONTS, reason="caption style fonts not installed")
@requires_ffmpeg
@requires_libass
def test_a_display_font_style_renders_through_the_pipeline(db_session, settings, storage):  # noqa: F811
    edit = make_edit(db_session, storage)
    config = EditConfig.create(
        layout="blur_background",
        captions_enabled=True,
        caption_style="comic",
        caption_position="bottom",
        caption_timing="phrase_fallback",
    )
    edit.config, edit.config_fingerprint = config.snapshot(), config.fingerprint()
    edit.caption_style, edit.caption_renderer = "comic", "caption_v2"
    edit.caption_timing = "phrase_fallback"
    db_session.commit()
    seen = {}

    def spy(source, target, **kwargs):
        workspace = kwargs["workspace"]
        seen["fonts"] = sorted(p.name for p in (workspace / "fonts").iterdir())
        seen["style"] = next(
            line for line in (workspace / "captions.ass").read_text().splitlines()
            if line.startswith("Style: Dynamic,")
        )  # fmt: skip
        return compose_short(source, target, **kwargs)

    result = run_clip_edit(
        edit.id, db_session, settings=settings, storage=storage, composer=spy, task_id="task-1"
    )
    assert result.status == ClipEditStatus.READY, result.error_message
    assert seen["fonts"] == ["Bangers-Regular.ttf"]
    assert seen["style"].startswith("Style: Dynamic,Bangers,138,")


def test_a_template_style_that_needs_word_sync_falls_back_without_it():
    from types import SimpleNamespace

    from app.services.auto_edit.template import _captions
    from app.services.branding.template_config import TemplateConfig

    template = TemplateConfig.create({"captions": True, "caption_preset": "one_word"})
    fields = {
        "captions_enabled": True,
        "caption_style": "focus",
        "caption_position": "bottom",
        "caption_timing": "phrase_fallback",
        "caption_track_id": None,
    }
    notes: list[str] = []
    _captions(fields, template, SimpleNamespace(capabilities=None), notes)
    assert fields["caption_style"] == "focus" and "word sync" in notes[0]
    fields.update(caption_timing="aligned_word", caption_track_id="t")
    _captions(fields, template, SimpleNamespace(capabilities=None), [])
    assert fields["caption_style"] == "one_word"
