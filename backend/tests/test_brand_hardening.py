"""Brand and template hardening (V1.7): unreadable templates, gone logos, CMYK uploads, tall
logos, Smart Reframe with a logo, an end card longer than its clip, Arabic and emoji captions
with a brand emphasis colour, and deleted defaults."""

import subprocess
import uuid

from PIL import Image
from sqlalchemy import select

from app.models import ShortTemplate
from app.services.clip_edit.brand import EndCard
from app.services.clip_edit.brand_render import BrandLayers
from app.services.clip_edit.caption_v2 import build_dynamic_ass
from app.services.clip_edit.composition import compose_short
from app.services.clip_edit.config import DynamicPreset, Layout
from app.services.clip_edit.dynamic_cues import CueWord, WordCue
from app.services.clip_edit.smart_crop import CropPoint
from app.services.ffprobe import probe
from tests.media_fixtures import FFMPEG, requires_ffmpeg
from tests.test_auto_edit_api import clip_ctx, fake_queues, plan_now  # noqa: F401
from tests.test_brand_render import GREEN, plan, render_brand
from tests.test_clip_edit_api import sign_up
from tests.test_clip_edit_composition import close, pixel
from tests.test_video_upload import create_project
from tests.test_visual_assets_api import upload
from tests.test_visual_render import GREY, OPTIONS, RED, main_clip, solid_image
from tests.visual_fixtures import make_transparent_png

# --- the API -------------------------------------------------------------------------------------


def test_a_template_this_server_cannot_read_is_refused_clearly(client, db_session):
    sign_up(client)
    brand = client.post("/brand/profiles", json={"name": "B", "primary_color": "#000"}).json()
    made = client.post(
        "/brand/templates",
        json={"name": "Old one", "brand_profile_id": brand["id"], "is_default": True},
    ).json()
    row = db_session.get(ShortTemplate, uuid.UUID(made["id"]))
    row.config = {"version": "template_v0", "captions": "maybe"}
    db_session.commit()
    ctx = clip_ctx(db_session)
    refused = client.post(ctx["base"], json={"template_id": made["id"]})
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "“Old one” can't be used as it is; open it in Brand Studio and save it again"
    )
    assert client.get("/brand/edit-section").status_code == 409
    assert client.get(f"/brand/templates/{made['id']}").status_code == 200  # still listed


def test_a_cmyk_or_palette_logo_upload_is_normalized_and_usable(client, db_session, tmp_path):
    sign_up(client)
    project = create_project(client)
    cmyk = tmp_path / "logo-cmyk.jpg"
    Image.new("CMYK", (300, 120), (0, 255, 255, 0)).save(cmyk, "JPEG")
    palette = tmp_path / "logo-palette.png"
    Image.new("P", (200, 200), 3).save(palette)
    for path in (cmyk, palette):
        asset = upload(client, project["id"], path).json()
        made = client.post(
            "/brand/profiles",
            json={"name": path.stem, "primary_color": "#000", "logo_asset_id": asset["id"]},
        )
        assert made.status_code == 201, made.text
        assert made.json()["logo"]["name"] == path.name


def test_applying_a_plan_whose_logo_is_gone_says_why(client, db_session, tmp_path):
    sign_up(client)
    ctx = clip_ctx(db_session)
    logos = create_project(client, "Logos")
    image = solid_image(tmp_path / "logo.png")
    asset = upload(client, logos["id"], image).json()
    brand = client.post(
        "/brand/profiles",
        json={"name": "B", "primary_color": "#000", "logo_asset_id": asset["id"]},
    ).json()
    template = client.post(
        "/brand/templates", json={"name": "T", "brand_profile_id": brand["id"]}
    ).json()
    plan_id = client.post(ctx["base"], json={"template_id": template["id"]}).json()["id"]
    plan_now(db_session, plan_id)
    client.request("DELETE", f"/projects/{logos['id']}", json={"confirm_name": "Logos"})
    applied = client.post(f"{ctx['base']}/{plan_id}/apply")
    assert applied.status_code == 409
    assert applied.json()["detail"].startswith("The brand logo is no longer one of your images")


def test_a_deleted_default_template_falls_back_to_the_brand(client, db_session):
    sign_up(client)
    client.post("/brand/profiles", json={"name": "B", "primary_color": "#000"})
    template = client.post("/brand/templates", json={"name": "T", "is_default": True}).json()
    client.delete(f"/brand/templates/{template['id']}")
    section = client.get("/brand/edit-section").json()
    assert section["template"] is None and section["brand"]["name"] == "B"
    assert db_session.scalar(select(ShortTemplate)) is None


# --- captions ------------------------------------------------------------------------------------


def test_arabic_and_emoji_captions_take_the_brand_emphasis(tmp_path):
    words = [CueWord("مرحبا", 0.0, 0.5), CueWord("بكم", 0.5, 1.0), CueWord("🔥", 1.0, 1.5)]
    cue = WordCue(0.0, 1.5, tuple(words), (0,), timed=True)
    ass = build_dynamic_ass(
        [cue], preset=DynamicPreset.PUNCH, alignment=2, margin_v=422, margin_h=97,
        font_family="Noto Sans", active_colour="#F43F5E", emoji_family=None,
    )  # fmt: skip
    assert "&H005E3FF4" in ass  # #F43F5E as ASS BGR, on the spoken word
    assert "مرحبا" in ass and "بكم" in ass


# --- real renders --------------------------------------------------------------------------------


@requires_ffmpeg
def test_a_tall_logo_fits_its_box_by_height(tmp_path):
    tall = solid_image(tmp_path / "tall.png", size=(100, 400), colour=RED)
    out = render_brand(tmp_path, BrandLayers(3.0, tall, plan("top_left")), name="tall.png.mp4")
    # 100×400 into the 172 box → 43×172 at x = 97, y = 192.
    assert close(pixel(out, 118, 278, t=1.0, box=4), RED)
    assert close(pixel(out, 200, 278, t=1.0, box=4), GREY)


@requires_ffmpeg
def test_an_end_card_longer_than_its_clip_is_still_exact(tmp_path):
    source = main_clip(tmp_path / "main.mp4", seconds=1.0)
    card = EndCard(3.0, "#0EA5E9", None, show_logo=False)
    out = tmp_path / "short.mp4"
    compose_short(source, out, layout=Layout.FIT, options=OPTIONS, workspace=tmp_path,
                  brand=BrandLayers(1.0, None, None, card))  # fmt: skip
    assert abs(probe(out).duration_seconds - 4.0) <= 0.15
    assert close(pixel(out, 540, 1700, t=3.0), (14, 165, 233))


@requires_ffmpeg
def test_smart_reframe_keeps_the_logo_fixed_while_the_crop_moves(tmp_path):
    wide = tmp_path / "wide.mp4"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=1280x720:r=25:d=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", str(wide)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    points = [CropPoint(0.0, 0.3, 0.5, 0.316, 1.0), CropPoint(3.0, 0.7, 0.5, 0.316, 1.0)]
    disc = make_transparent_png(tmp_path / "disc.png")
    out = tmp_path / "reframed.mp4"
    compose_short(wide, out, layout=Layout.SMART_REFRAME, options=OPTIONS, workspace=tmp_path,
                  crop_points=points, brand=BrandLayers(3.0, disc, plan("top_left")))  # fmt: skip
    for t in (0.3, 2.7):
        assert close(pixel(out, 183, 278, t=t, box=4), GREEN)  # the logo never moves
