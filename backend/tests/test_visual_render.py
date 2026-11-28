"""Visual elements rendered with real FFmpeg into the 1080 × 1920 short and checked on the
encoded frames: cutaway fill and fit, transparent images, video B-roll, picture-in-picture,
overlays and opacity, fades, several elements in sequence, captions staying on top, and the
short's duration, frame rate and audio left untouched."""

import subprocess
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.core.config import Settings, get_settings
from app.models import ClipEditStatus, VisualAsset
from app.services.clip_edit.caption_styles import build_ass_document
from app.services.clip_edit.captions import Cue
from app.services.clip_edit.composition import (
    CAPTIONS_FILENAME,
    build_edit_command,
    compose_short,
    supports_visuals,
)
from app.services.clip_edit.config import CaptionPosition, CaptionStyle, EditConfig, Layout
from app.services.clip_edit.pipeline import run_clip_edit
from app.services.clip_render.renderer import RenderOptions
from app.services.ffprobe import probe
from app.services.storage import LocalStorageProvider
from app.services.visuals.compositor import VisualLayer, layer_inputs, layers_graph
from app.services.visuals.config import VisualElement, VisualPosition, VisualSize
from app.services.visuals.layout import inset_box, inset_position, layout_summary
from tests.media_fixtures import FFMPEG, requires_ffmpeg, requires_libass
from tests.test_clip_edit_composition import close, pixel
from tests.test_clip_edit_pipeline import make_edit as make_pipeline_edit
from tests.test_dynamic_caption_edits import frame, use_config
from tests.visual_fixtures import make_transparent_png

GREY, RED, BLUE, YELLOW, GREEN, WHITE = (
    (128, 128, 128), (255, 0, 0), (0, 0, 255), (255, 255, 0), (30, 200, 60), (255, 255, 255)
)  # fmt: skip
BACKGROUND = (17, 17, 19)
# The configured FFmpeg (the libass build), as the render job uses it.
OPTIONS = RenderOptions(
    preset="ultrafast", timeout_seconds=120, ffmpeg_path=get_settings().ffmpeg_path,
    ffprobe_path=get_settings().ffprobe_path,
)  # fmt: skip


def main_clip(path: Path, seconds: float = 3.0) -> Path:
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=0x808080:s=640x360:r=25:d={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    return path


def solid_image(path: Path, size=(400, 300), colour=RED, border: int = 0) -> Path:
    image = Image.new("RGB", size, colour)
    if border:
        ImageDraw.Draw(image).rectangle(
            (0, 0, size[0] - 1, size[1] - 1), outline=WHITE, width=border
        )
    image.save(path)
    return path


def solid_video(path: Path, colour: str = "0x0000FF", seconds: float = 2.0, size="320x180") -> Path:
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c={colour}:s={size}:r=30:d={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=3000:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac",
         "-shortest", str(path)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    return path


def layer(path: Path, kind="image", alpha=False, size=(400, 300), **element) -> VisualLayer:
    data = {"asset_id": str(uuid.uuid4()), "mode": "cutaway", "start_seconds": 1.0,
            "end_seconds": 2.0, **element}  # fmt: skip
    return VisualLayer(VisualElement.create(data), path, kind, alpha, *size)


def render(tmp_path: Path, layers: list[VisualLayer], *, captions=False, name="out.mp4") -> Path:
    source = (
        main_clip(tmp_path / "main.mp4")
        if not (tmp_path / "main.mp4").exists()
        else tmp_path / "main.mp4"
    )
    target = tmp_path / name
    compose_short(
        source, target, layout=Layout.CENTER_CROP, options=OPTIONS, workspace=tmp_path,
        captions=captions, visuals=layers,
    )  # fmt: skip
    return target


# --- geometry and graph (no FFmpeg needed) -------------------------------------------------------


def test_inset_boxes_and_positions_use_the_safe_area():
    assert inset_box(VisualSize.SMALL) == (368, 460)
    assert inset_box(VisualSize.MEDIUM) == (476, 596)
    assert inset_box(VisualSize.LARGE) == (604, 756)
    assert inset_position(VisualPosition.BOTTOM_LEFT) == ("97", "H-h-422")
    assert inset_position(VisualPosition.TOP_RIGHT) == ("W-w-97", "192")
    assert inset_position(VisualPosition.CENTER) == ("(W-w)/2", "(H-h)/2")
    summary = layout_summary()
    assert summary["margins"] == {"top": 192, "bottom": 422, "left": 97, "right": 97}
    assert summary["inset_width_fraction"]["medium"] == 0.44


def test_inputs_trim_mute_and_loop_each_asset(tmp_path):
    image = layer(tmp_path / "a.png")
    video = layer(tmp_path / "b.mp4", "video", asset_offset_seconds=1.25)
    looped = layer(
        tmp_path / "c.mp4", "video", mode="pip", start_seconds=3, end_seconds=8, loop=True
    )
    assert layer_inputs([image, video, looped], 25.0) == [
        "-loop", "1", "-framerate", "25", "-t", "1.000", "-i", str(tmp_path / "a.png"),
        "-ss", "1.250", "-t", "1.000", "-an", "-i", str(tmp_path / "b.mp4"),
        "-stream_loop", "-1", "-ss", "0.000", "-t", "5.000", "-an", "-i", str(tmp_path / "c.mp4"),
    ]  # fmt: skip


def test_the_graph_has_no_paths_and_releases_each_layer(tmp_path):
    secret = tmp_path / "private" / "moon.png"
    overlay = layer(secret, mode="overlay", start_seconds=2.5, end_seconds=3.0, opacity=0.5)
    graph, label = layers_graph([layer(secret), overlay], 2, 25.0)
    assert str(tmp_path) not in graph and "moon" not in graph
    assert "[2:v]" in graph and "[3:v]" in graph and label == "[v1]"
    assert graph.count("eof_action=pass") == 2
    assert "enable='between(t,1.000,2.000)'" in graph and "colorchannelmixer=aa=0.50" in graph


def test_the_text_layer_is_drawn_after_the_visuals(tmp_path):
    command = build_edit_command(
        "ffmpeg", tmp_path / "s.mp4", tmp_path / "o.mp4", layout=Layout.CENTER_CROP,
        has_audio=True, captions=True, preset="ultrafast", crf=23, audio_bitrate="128k",
        visual_inputs=["-i", "v.png"], visual_graph="[1:v]null[l0];[framed][l0]overlay[v0]",
        visual_label="[v0]",
    )  # fmt: skip
    graph = command[command.index("-filter_complex") + 1]
    assert graph.index("overlay[v0]") < graph.index("[v0]subtitles=")
    assert command[command.index("-map") + 1] == "[out]" and command.count("-i") == 2


# --- rendered pixels ----------------------------------------------------------------------------


@requires_ffmpeg
def test_this_ffmpeg_can_draw_visuals():
    assert supports_visuals(FFMPEG)


@requires_ffmpeg
def test_an_image_cutaway_replaces_the_picture_only_during_its_interval(tmp_path):
    out = render(tmp_path, [layer(solid_image(tmp_path / "red.png"))])
    assert close(pixel(out, 540, 960, t=0.5), GREY)
    assert close(pixel(out, 540, 960, t=1.5), RED) and close(pixel(out, 8, 8, t=1.5), RED)
    assert close(pixel(out, 540, 960, t=2.5), GREY)
    meta = probe(out)
    assert abs(meta.duration_seconds - 3.0) <= 0.1 and meta.audio_codec == "aac"
    assert (meta.width, meta.height) == (1080, 1920) and round(meta.fps) == 25


@requires_ffmpeg
def test_fill_crops_while_fit_shows_the_whole_image_over_its_blur(tmp_path):
    framed = solid_image(tmp_path / "framed.png", colour=BLUE, border=20)
    fill = render(tmp_path, [layer(framed, fit="fill")], name="fill.mp4")
    fit = render(tmp_path, [layer(framed, fit="fit")], name="fit.mp4")
    # Fit: 400×300 → 1080×810, centred (y 555..1365): its top border sits at y ≈ 555-609.
    assert close(pixel(fit, 540, 575, t=1.5, box=4), WHITE)
    assert close(pixel(fit, 540, 300, t=1.5), BLUE, tolerance=80)  # the blurred copy behind
    # Fill: 2560×1920 cropped to the centre: the border is only at the very top.
    assert close(pixel(fill, 540, 575, t=1.5), BLUE)
    assert close(pixel(fill, 540, 40, t=1.5, box=4), WHITE)


@requires_ffmpeg
def test_a_transparent_image_cutaway_is_flattened_onto_the_background(tmp_path):
    disc = make_transparent_png(tmp_path / "disc.png")
    out = render(tmp_path, [layer(disc, alpha=True, size=(200, 200))])
    assert close(pixel(out, 540, 960, t=1.5), GREEN)
    assert close(pixel(out, 8, 8, t=1.5), BACKGROUND, tolerance=20)  # not the main video


@requires_ffmpeg
def test_a_video_cutaway_plays_muted_from_its_offset(tmp_path):
    video = solid_video(tmp_path / "blue.mp4")
    out = render(tmp_path, [layer(video, "video", size=(320, 180), asset_offset_seconds=0.5)])
    assert close(pixel(out, 540, 960, t=1.5), BLUE)
    assert close(pixel(out, 540, 960, t=2.5), GREY)


@requires_ffmpeg
def test_picture_in_picture_sits_in_its_safe_corner_with_a_frame(tmp_path):
    yellow = solid_image(tmp_path / "yellow.png", size=(300, 300), colour=YELLOW)
    out = render(tmp_path, [layer(yellow, mode="pip", position="bottom_left", size=(300, 300),
                                  start_seconds=0.5, end_seconds=2.5)])  # fmt: skip
    # medium box 476 wide → 476×476 + 6 px frame = 488×488 at x=97, y=1920-422-488=1010.
    assert close(pixel(out, 341, 1254, t=1.0), YELLOW)
    assert close(pixel(out, 98, 1254, t=1.0, box=4), WHITE)
    assert close(pixel(out, 900, 400, t=1.0), GREY)
    assert close(pixel(out, 341, 1254, t=2.8), GREY)


@requires_ffmpeg
def test_overlays_keep_transparency_and_apply_opacity(tmp_path):
    disc = make_transparent_png(tmp_path / "disc.png")
    white = solid_image(tmp_path / "white.png", size=(200, 200), colour=WHITE)
    out = render(tmp_path, [
        layer(disc, alpha=True, size=(200, 200), mode="overlay", position="center",
              start_seconds=0.5, end_seconds=1.5),
        layer(white, size=(200, 200), mode="overlay", position="center", opacity=0.5,
              start_seconds=2.0, end_seconds=2.8),
    ])  # fmt: skip
    # small box 368: the disc (368×368) is centred at (356, 776).
    assert close(pixel(out, 540, 960, t=1.0), GREEN)
    assert close(pixel(out, 362, 782, t=1.0, box=4), GREY)  # its transparent corner
    assert close(pixel(out, 540, 960, t=2.4), (191, 191, 191), tolerance=25)  # half-opaque white


@requires_ffmpeg
def test_a_faded_cutaway_cross_fades_in_the_short(tmp_path):
    red = solid_image(tmp_path / "red.png")
    out = render(tmp_path, [layer(red, transition="fade", transition_seconds=0.3)])
    red_level, green_level, _ = pixel(out, 540, 960, t=1.16)  # about half-way in
    assert 150 < red_level < 240 and 25 < green_level < 110
    assert close(pixel(out, 540, 960, t=1.5), RED)


@requires_ffmpeg
def test_several_elements_in_sequence_keep_duration_and_audio(tmp_path):
    out = render(tmp_path, [
        layer(solid_image(tmp_path / "red.png"), start_seconds=0.4, end_seconds=1.0),
        layer(solid_image(tmp_path / "y.png", size=(300, 300), colour=YELLOW), mode="pip",
              size=(300, 300), position="top_right", start_seconds=1.0, end_seconds=2.0),
        layer(solid_video(tmp_path / "b.mp4"), "video", size=(320, 180), start_seconds=2.0,
              end_seconds=2.6),
    ])  # fmt: skip
    assert close(pixel(out, 540, 960, t=0.7), RED)
    assert close(pixel(out, 540, 960, t=1.5), GREY) and close(
        pixel(out, 1080 - 97 - 244, 192 + 244, t=1.5), YELLOW
    )
    assert close(pixel(out, 540, 960, t=2.3), BLUE)
    meta = probe(out)
    assert abs(meta.duration_seconds - 3.0) <= 0.1 and meta.audio_codec == "aac"


@requires_ffmpeg
@requires_libass
def test_captions_stay_on_top_of_a_cutaway(tmp_path):
    (tmp_path / CAPTIONS_FILENAME).write_text(
        build_ass_document([Cue(0.0, 3.0, "BIG WORDS ON TOP")], style=CaptionStyle.BOLD,
                           position=CaptionPosition.CENTER, font_family="Noto Sans"),
        encoding="utf-8",
    )  # fmt: skip
    red = solid_image(tmp_path / "red.png")
    with_text = render(tmp_path, [layer(red, start_seconds=0.5, end_seconds=2.5)], captions=True,
                       name="text.mp4")  # fmt: skip
    without = render(tmp_path, [layer(red, start_seconds=0.5, end_seconds=2.5)], name="plain.mp4")
    a, b = frame(with_text, 1.5), frame(without, 1.5)
    changed = np.abs(a - b).sum(axis=2) > 150
    assert changed[800:1120].sum() > 2000  # the caption is visible over the B-roll


# --- the render job, end to end -------------------------------------------------------------------


@requires_ffmpeg
def test_the_render_job_draws_visuals_and_reports_missing_assets(db_session, tmp_path):
    settings = Settings(**get_settings().model_dump())
    storage = LocalStorageProvider(Path(settings.media_root))
    edit = make_pipeline_edit(db_session, storage, captions=False, layout="center_crop")
    main_clip(storage.path_for(edit.clip.storage_key), seconds=3.0)
    edit.clip.end_time = edit.clip.start_time + 3.0
    edit.clip.duration_seconds = 3.0
    key = storage.generate_key("png", category="visuals")
    storage.path_for(key).parent.mkdir(parents=True, exist_ok=True)
    solid_image(storage.path_for(key))
    asset = VisualAsset(
        project_id=edit.clip.video.project_id, kind="image", display_name="red.png",
        storage_key=key, content_type="image/png", file_size=storage.size(key),
        sha256=uuid.uuid4().hex * 2, width=400, height=300, codec="png", container="png",
    )  # fmt: skip
    db_session.add(asset)
    db_session.commit()
    config = EditConfig.create(
        layout="center_crop", captions_enabled=False,
        visuals={"elements": [{"asset_id": str(asset.id), "mode": "cutaway",
                               "start_seconds": 1.0, "end_seconds": 2.0}]},
    )  # fmt: skip
    edit = use_config(db_session, edit, config)
    try:
        result = run_clip_edit(
            edit.id, db_session, settings=settings, storage=storage, task_id="task-1"
        )
        assert result.status == ClipEditStatus.READY, result.error_message
        out = storage.path_for(result.storage_key)
        assert close(pixel(out, 540, 960, t=1.5), RED) and close(pixel(out, 540, 960, t=0.5), GREY)
        assert abs(result.duration_seconds - 3.0) <= 0.1
        # The asset disappears before a retry: the job fails clearly, nothing is rendered.
        storage.delete(key)
        result.status, result.celery_task_id = ClipEditStatus.QUEUED, "task-2"
        db_session.commit()
        again = run_clip_edit(
            edit.id, db_session, settings=settings, storage=storage, task_id="task-2"
        )
        assert (
            again.status == ClipEditStatus.FAILED and again.error_code == "visual_asset_unavailable"
        )
    finally:
        for path in sorted(storage.root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()


def transparent_video(path: Path, seconds: float = 2.0) -> Path:
    """A VP9 WebM with an alpha channel: a red square in the middle, transparent elsewhere."""
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=red:s=360x640:r=30:d={seconds},format=rgba,"
               "geq=r=255:g=0:b=0:a='255*between(X,120,239)*between(Y,260,379)'",
         "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "30",
         "-auto-alt-ref", "0", str(path)],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    return path


@requires_ffmpeg
def test_a_transparent_video_is_probed_as_such(tmp_path):
    from app.services.visual_assets import inspect_video

    found = inspect_video(
        transparent_video(tmp_path / "fx.webm"), ".webm", tmp_path, get_settings()
    )
    assert found.kind.value == "video" and found.has_alpha is True and found.codec == "vp9"
    opaque = inspect_video(solid_video(tmp_path / "plain.mp4"), ".mp4", tmp_path, get_settings())
    assert opaque.has_alpha is False


@requires_ffmpeg
def test_a_transparent_video_overlay_fills_the_frame_and_keeps_its_transparency(tmp_path):
    fx = transparent_video(tmp_path / "fx.webm")
    effect = VisualLayer(
        VisualElement.create({
            "asset_id": str(uuid.uuid4()), "mode": "overlay", "size": "full",
            "start_seconds": 0.5, "end_seconds": 2.5,
        }),
        fx, "video", True, 360, 640, codec="vp9",
    )  # fmt: skip
    assert effect.element.position == VisualPosition.CENTER  # a full-frame overlay is centred
    inputs = layer_inputs([effect], 25.0)
    assert inputs[inputs.index("-i") - 2 : inputs.index("-i")] == ["-c:v", "libvpx-vp9"]
    out = render(tmp_path, [effect])
    # 360×640 scaled to the 1080×1920 frame: the red square lands in the middle.
    assert close(pixel(out, 540, 960, t=1.0), RED, tolerance=60)
    assert close(pixel(out, 100, 300, t=1.0), GREY)  # transparent: the clip shows through
    assert close(pixel(out, 540, 960, t=0.2), GREY)  # before the overlay starts
    assert abs(probe(out).duration_seconds - 3.0) < 0.3


def test_only_overlays_may_fill_the_frame():
    import pytest

    with pytest.raises(ValueError, match="Only overlays"):
        VisualElement.create({"asset_id": str(uuid.uuid4()), "mode": "pip", "size": "full",
                              "start_seconds": 0, "end_seconds": 1})  # fmt: skip
    assert inset_box(VisualSize.FULL) == (1080, 1920)
