"""Brand rendering (V1.7) inside the one renderer: the snapshot's brand section, readability
rules, the deterministic logo placement policy, the filtergraph, and real FFmpeg renders of a
corner logo (transparent, never stretched) and an appended, silent end card."""

import subprocess
import uuid
from pathlib import Path

import numpy as np
import pytest

from app.core.config import Settings, get_settings
from app.models import ClipEditStatus, VisualAsset
from app.services.clip_edit.brand import (
    BrandConfig,
    BrandLogo,
    EndCard,
    LogoCorner,
    LogoSize,
    enable_expression,
    logo_box,
    logo_plan,
)
from app.services.clip_edit.brand_render import BrandLayers, brand_graph, end_card_ass
from app.services.clip_edit.caption_styles import build_ass_document
from app.services.clip_edit.composition import CAPTIONS_FILENAME, build_edit_command, compose_short
from app.services.clip_edit.config import CaptionPosition, CaptionStyle, EditConfig, Layout
from app.services.clip_edit.pipeline import run_clip_edit
from app.services.ffprobe import probe
from app.services.storage import LocalStorageProvider
from tests.media_fixtures import FFMPEG, requires_ffmpeg, requires_libass
from tests.test_clip_edit_composition import close, pixel
from tests.test_clip_edit_pipeline import make_edit as make_pipeline_edit
from tests.test_dynamic_caption_edits import use_config
from tests.test_visual_render import GREY, OPTIONS, RED, main_clip, solid_image
from tests.visual_fixtures import make_transparent_png

LOGO = str(uuid.uuid4())
PINK = (244, 63, 94)
GREEN = (30, 200, 60)
BRAND = {
    "name": "Amine Clips",
    "logo": {"asset_id": LOGO, "corner": "bottom_right", "size": "small"},
    "caption_emphasis": "#FFD43B",
    "hook_accent": "#F43F5E",
    "end_card": {
        "seconds": 1.5, "background": "#F43F5E", "text": "Follow for more", "show_logo": True,
    },
}  # fmt: skip


def edit_config(**extra):
    base = {
        "layout": "blur_background", "captions_enabled": True, "caption_style": "punch",
        "caption_position": "bottom", "caption_timing": "phrase_fallback",
    }  # fmt: skip
    return EditConfig.create(**{**base, **extra})


# --- the snapshot -------------------------------------------------------------------------------


def test_the_brand_section_exists_only_when_it_changes_something():
    plain = edit_config()
    assert "brand" not in plain.snapshot()
    assert edit_config(brand=None).fingerprint() == plain.fingerprint()  # old edits unchanged
    # Nothing readable or applicable left: no section at all.
    assert edit_config(brand={"name": "A", "caption_emphasis": "#1E3A8A"}).brand is None
    branded = edit_config(brand=BRAND, hook_enabled=True, hook_text="Watch", hook_style="boxed")
    section = branded.snapshot()["brand"]
    assert section["logo"] == {"asset_id": LOGO, "corner": "bottom_right", "size": "small"}
    assert section["caption_emphasis"] == "#FFD43B" and section["hook_accent"] == "#F43F5E"
    assert section["end_card"]["seconds"] == 1.5
    assert EditConfig.from_snapshot(branded.snapshot()) == branded
    assert branded.fingerprint() != plain.fingerprint()


def test_brand_colours_apply_only_where_they_mean_something():
    # Phrase captions have no spoken word; only the Boxed hook has a label colour.
    phrase = EditConfig.create(
        layout="fit", captions_enabled=True, caption_style="bold", brand=BRAND
    ).brand
    assert phrase.caption_emphasis is None and phrase.hook_accent is None
    headline = edit_config(brand=BRAND, hook_enabled=True, hook_text="Hi", hook_style="headline")
    assert headline.brand.hook_accent is None
    off = EditConfig.create(layout="fit", captions_enabled=False, brand=BRAND).brand
    assert off.caption_emphasis is None and off.logo is not None


@pytest.mark.parametrize(
    "data",
    [
        {"name": "A", "logo": {"asset_id": "x", "corner": "top_left", "size": "small"}},
        {"name": "A", "logo": {"asset_id": LOGO, "corner": "middle", "size": "small"}},
        {"name": "A", "end_card": {"seconds": 9, "background": "#000000"}},
        {"name": "A", "end_card": {"seconds": 2, "background": "red"}},
        {"name": "", "caption_emphasis": "#FFFFFF"},
        {"name": "A", "caption_emphasis": "url(x)"},
    ],
)
def test_invalid_brand_values_are_refused(data):
    with pytest.raises(ValueError):
        BrandConfig.create(data)


# --- the placement policy -----------------------------------------------------------------------


def plan(corner, **kw):
    args = {"captions_position": None, "hook_position": None, "hook_seconds": 0.0, "insets": []}
    return logo_plan(BrandLogo(LOGO, LogoCorner(corner), LogoSize.SMALL), **{**args, **kw})


def test_the_logo_stays_clear_of_captions_the_hook_and_insets():
    assert plan("bottom_right", captions_position="bottom").corner == LogoCorner.TOP_RIGHT
    assert plan("bottom_right", captions_position="bottom").moved
    assert plan("top_left", captions_position="top").corner == LogoCorner.BOTTOM_LEFT
    assert plan("bottom_left", captions_position="center").corner == LogoCorner.BOTTOM_LEFT
    assert plan("bottom_left").corner == LogoCorner.BOTTOM_LEFT  # no captions: no move
    hooked = plan("top_right", hook_position="top", hook_seconds=2.0)
    assert hooked.visible_from == 2.0
    assert plan("top_right", hook_position="center", hook_seconds=2.0).visible_from == 0.0
    shared = plan("top_right", insets=[("top_right", 1.0, 2.5), ("top_left", 0.0, 1.0)])
    assert shared.hidden == ((1.0, 2.5),)
    assert enable_expression(hooked) == "gte(t,2.000)"
    assert enable_expression(shared) == "not(between(t,1.000,2.500))"
    assert enable_expression(plan("top_left")) == "1"
    assert logo_box(LogoSize.SMALL) == 172 and logo_box(LogoSize.LARGE) == 302


def test_the_graph_appends_a_silent_card_and_carries_no_paths(tmp_path):
    logo = tmp_path / "secret-logo.png"
    layers = BrandLayers(
        3.0, logo, plan("top_right"), EndCard(1.5, "#F43F5E", "Follow", show_logo=True)
    )
    graph, label = brand_graph(layers, 1, 25.0, "[framed]")
    assert label == "[branded]" and "secret-logo" not in graph
    assert "split=2[lga][lgb]" in graph and "concat=n=2:v=1:a=0" in graph
    assert "color=c=0xF43F5E:s=1080x1920:r=25:d=1.500" in graph
    assert "force_original_aspect_ratio=decrease" in graph  # never stretched
    command = build_edit_command(
        FFMPEG, tmp_path / "in.mp4", tmp_path / "out.mp4", layout=Layout.FIT, has_audio=True,
        captions=False, preset="ultrafast", crf=23, audio_bitrate="128k",
        brand_inputs=["-loop", "1", "-i", str(logo)], brand_graph=graph, brand_label=label,
        extra_seconds=1.5,
    )  # fmt: skip
    filtergraph = command[command.index("-filter_complex") + 1]
    assert "[0:a:0]apad=pad_dur=1.500[aud]" in filtergraph
    assert command[command.index("-map", command.index("-map") + 1) + 1] == "[aud]"


def test_end_card_text_is_escaped_and_fits():
    card = EndCard(2.0, "#FFD43B", "{\\b1}Follow\\N", show_logo=False)
    styles, events = end_card_ass(card, name="A" * 60, start=3.0, font_family="Noto Sans")
    assert "&H00141111" in styles[0]  # dark text on the light card
    assert "\\fs84" not in events[0]  # a long name gets smaller to fit
    assert "{\\b1}" not in events[1] and "0:00:03.00,0:00:05.00" in events[1]


# --- real renders --------------------------------------------------------------------------------


def wide_logo(path: Path) -> Path:
    return solid_image(path, size=(400, 100), colour=RED)


def render_brand(tmp_path, layers: BrandLayers, *, captions=False, name="out.mp4") -> Path:
    source = tmp_path / "main.mp4"
    if not source.exists():
        main_clip(source, seconds=3.0)
    target = tmp_path / name
    compose_short(
        source, target, layout=Layout.CENTER_CROP, options=OPTIONS, workspace=tmp_path,
        captions=captions, brand=layers,
    )  # fmt: skip
    return target


def audio_peak(path: Path, start: float, seconds: float) -> float:
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", str(start), "-t", str(seconds), "-i", str(path),
         "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        check=True, capture_output=True, timeout=60,
    ).stdout  # fmt: skip
    samples = np.frombuffer(raw, dtype=np.int16)
    return float(np.abs(samples).max()) if samples.size else 0.0


@requires_ffmpeg
def test_a_logo_keeps_its_shape_and_transparency_in_its_safe_corner(tmp_path):
    wide = BrandLayers(3.0, wide_logo(tmp_path / "wide.png"), plan("top_right"))
    out = render_brand(tmp_path, wide, name="wide.mp4")
    # 400×100 into the 172 box → 172×43 at x = 1080−172−97, y = 192: never stretched.
    assert close(pixel(out, 897, 213, t=1.0, box=4), RED)
    assert close(pixel(out, 897, 300, t=1.0, box=4), GREY)
    disc = make_transparent_png(tmp_path / "disc.png")
    round_logo = BrandLayers(3.0, disc, plan("top_left"))
    out = render_brand(tmp_path, round_logo, name="disc.mp4")
    assert close(pixel(out, 183, 278, t=1.0, box=4), GREEN)
    assert close(pixel(out, 100, 195, t=1.0, box=2), GREY)  # its transparent corner
    hooked = BrandLayers(3.0, disc, plan("top_left", hook_position="top", hook_seconds=1.5))
    out = render_brand(tmp_path, hooked, name="hooked.mp4")
    assert close(pixel(out, 183, 278, t=0.5, box=4), GREY)  # clear while the hook shows
    assert close(pixel(out, 183, 278, t=2.0, box=4), GREEN)


@requires_ffmpeg
@requires_libass
def test_an_end_card_is_appended_silent_with_the_logo_and_name(tmp_path):
    card = EndCard(1.5, "#F43F5E", "Follow for more", show_logo=True)
    styles, events = end_card_ass(card, name="Amine Clips", start=3.0, font_family="Noto Sans")
    (tmp_path / CAPTIONS_FILENAME).write_text(
        build_ass_document([], style=CaptionStyle.BOLD, position=CaptionPosition.BOTTOM,
                           font_family="Noto Sans", extra_styles=styles, extra_events=events),
        encoding="utf-8",
    )  # fmt: skip
    disc = make_transparent_png(tmp_path / "disc.png")
    layers = BrandLayers(3.0, disc, plan("bottom_right"), card)
    out = render_brand(tmp_path, layers, captions=True)
    meta = probe(out)
    assert abs(meta.duration_seconds - 4.5) <= 0.15  # exactly the card longer
    assert meta.audio_codec == "aac"
    assert close(pixel(out, 540, 960, t=1.5), GREY)  # the clip itself is untouched
    assert close(pixel(out, 120, 1750, t=4.0), PINK)  # the card's background
    assert close(pixel(out, 540, 691, t=4.0), GREEN)  # the logo, centred on the card
    name_band = np.abs(np.array(pixel(out, 540, 1075, t=4.0, box=60)) - np.array(PINK)).sum()
    assert name_band > 20  # the brand name is drawn on the card
    assert audio_peak(out, 0.5, 1.0) > 2000 and audio_peak(out, 3.3, 1.0) < 50  # card silent


# --- the render job ----------------------------------------------------------------------------


@requires_ffmpeg
@requires_libass
def test_the_render_job_uses_the_snapshot_and_rechecks_the_logo(db_session, tmp_path):
    settings = Settings(**get_settings().model_dump())
    storage = LocalStorageProvider(Path(settings.media_root))
    edit = make_pipeline_edit(db_session, storage, captions=False, layout="center_crop")
    main_clip(storage.path_for(edit.clip.storage_key), seconds=3.0)
    edit.clip.end_time = edit.clip.start_time + 3.0
    edit.clip.duration_seconds = 3.0
    key = storage.generate_key("png", category="visuals")
    storage.path_for(key).parent.mkdir(parents=True, exist_ok=True)
    make_transparent_png(storage.path_for(key))
    asset = VisualAsset(
        project_id=edit.clip.video.project_id, kind="image", display_name="logo.png",
        storage_key=key, content_type="image/png", file_size=storage.size(key),
        sha256=uuid.uuid4().hex * 2, width=200, height=200, codec="png", container="png",
        has_alpha=True,
    )  # fmt: skip
    db_session.add(asset)
    db_session.commit()
    brand = {
        "name": "Amine Clips",
        "logo": {"asset_id": str(asset.id), "corner": "top_left", "size": "small"},
        "end_card": {"seconds": 1.0, "background": "#0EA5E9", "text": None, "show_logo": False},
    }
    edit = use_config(
        db_session,
        edit,
        EditConfig.create(layout="center_crop", captions_enabled=False, brand=brand),
    )
    try:
        result = run_clip_edit(
            edit.id, db_session, settings=settings, storage=storage, task_id="task-1"
        )
        assert result.status == ClipEditStatus.READY, result.error_message
        out = storage.path_for(result.storage_key)
        assert abs(result.duration_seconds - 4.0) <= 0.15
        assert close(pixel(out, 183, 278, t=1.0, box=4), GREEN)
        assert close(pixel(out, 120, 1750, t=3.5), (14, 165, 233))
        # The logo disappears before a retry: the job fails clearly.
        storage.delete(key)
        result.status, result.celery_task_id = ClipEditStatus.QUEUED, "task-2"
        db_session.commit()
        again = run_clip_edit(
            edit.id, db_session, settings=settings, storage=storage, task_id="task-2"
        )
        assert again.status == ClipEditStatus.FAILED
        assert again.error_code == "brand_logo_unavailable"
    finally:
        for path in sorted(storage.root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()


def test_a_logo_used_by_any_short_cannot_be_deleted():
    from app.services.media_deletion import visual_asset_ids

    snapshot = edit_config(brand=BRAND).snapshot()
    assert LOGO in visual_asset_ids(snapshot)


def test_previews_get_the_renderers_numbers(client, db_session):
    from tests.test_clip_edit_api import sign_up

    sign_up(client, "layout@example.com")
    layout = client.get("/brand/layout").json()
    assert layout["logo_width_fraction"] == {"small": 0.16, "medium": 0.22, "large": 0.28}
    assert layout["margins"] == {"top": 192, "bottom": 422, "left": 97, "right": 97}
    assert layout["end_card_seconds"] == [1.0, 3.0]
