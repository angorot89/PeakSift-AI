"""Visual asset hardening: multi-picture JPEGs, colour profiles, decompression-bomb headers,
very short and variable-frame-rate videos, crafted storage keys contained, and B-roll sound
never reaching the short."""

import io
import struct
import subprocess
import uuid
import zlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageCms

from app.core.config import get_settings
from app.models import ClipEditStatus, VisualAsset
from app.services.clip_edit.composition import compose_short
from app.services.clip_edit.config import EditConfig, Layout
from app.services.clip_edit.pipeline import run_clip_edit
from app.services.storage import LocalStorageProvider
from tests.audio_fixtures import amplitude, decode
from tests.media_fixtures import requires_ffmpeg
from tests.test_clip_edit_pipeline import make_edit as make_pipeline_edit
from tests.test_dynamic_caption_edits import use_config
from tests.test_visual_assets_api import content, media_files, project, upload  # noqa: F401
from tests.test_visual_render import OPTIONS, layer, main_clip
from tests.visual_fixtures import make_video

pytestmark = requires_ffmpeg


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in sorted(Path(get_settings().media_root).rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()


def stored(client, project_id, asset_id) -> Image.Image:
    return Image.open(io.BytesIO(content(client, project_id, asset_id).content))


# --- images ------------------------------------------------------------------------------------


def test_a_multi_picture_jpeg_keeps_its_primary_picture(client, project, tmp_path):  # noqa: F811
    first = Image.new("RGB", (320, 240), (220, 30, 30))
    second = Image.new("RGB", (320, 240), (30, 30, 220))
    path = tmp_path / "camera.jpg"
    first.save(path, "MPO", save_all=True, append_images=[second])
    response = upload(client, project, path)
    assert response.status_code == 201, response.text
    assert (response.json()["width"], response.json()["height"]) == (320, 240)
    red, green, blue = stored(client, project, response.json()["id"]).getpixel((10, 10))
    assert red > 180 and blue < 80


def test_an_embedded_srgb_profile_is_applied_and_not_kept(client, project, tmp_path):  # noqa: F811
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    path = tmp_path / "profiled.png"
    Image.new("RGB", (64, 64), (120, 180, 60)).save(path, icc_profile=srgb)
    body = upload(client, project, path).json()
    image = stored(client, project, body["id"])
    assert "icc_profile" not in image.info
    assert all(abs(a - b) <= 2 for a, b in zip(image.getpixel((5, 5)), (120, 180, 60), strict=True))


def test_a_broken_profile_never_breaks_an_upload(client, project, tmp_path):  # noqa: F811
    path = tmp_path / "broken-profile.jpg"
    Image.new("RGB", (64, 64), (10, 200, 10)).save(path, icc_profile=b"not a profile at all")
    response = upload(client, project, path)
    assert response.status_code == 201
    assert stored(client, project, response.json()["id"]).getpixel((5, 5))[1] > 150


WIDE_GAMUT = Path("/System/Library/ColorSync/Profiles/Display P3.icc")


@pytest.mark.skipif(not WIDE_GAMUT.exists(), reason="no Display P3 profile on this system")
def test_a_display_p3_photo_is_converted_to_srgb(client, project, tmp_path):  # noqa: F811
    path = tmp_path / "p3.png"
    Image.new("RGB", (64, 64), (0, 255, 0)).save(path, icc_profile=WIDE_GAMUT.read_bytes())
    red, green, blue = stored(client, project, upload(client, project, path).json()["id"]).getpixel(
        (5, 5)
    )
    assert green == 255 and red < 30  # P3 pure green is beyond sRGB: clipped, never shifted to red


def png_with_header(width: int, height: int) -> bytes:
    """A tiny PNG whose header claims ``width`` × ``height`` (the data is far too short)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\0" * 16))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("size", [(30_000, 30_000), (12_000, 9_000)])
def test_decompression_bomb_headers_are_refused_before_decoding(client, project, tmp_path, size):  # noqa: F811
    (tmp_path / "bomb.png").write_bytes(png_with_header(*size))
    response = upload(client, project, tmp_path / "bomb.png")
    assert response.status_code == 413 and media_files() == []


# --- videos -------------------------------------------------------------------------------------


def test_very_short_and_variable_frame_rate_videos_are_accepted(client, project, tmp_path):  # noqa: F811
    short = upload(client, project, make_video(tmp_path / "blink.mp4", seconds=0.2))
    assert short.status_code == 201 and 0 < short.json()["duration_seconds"] <= 0.3
    vfr = tmp_path / "vfr.mp4"
    subprocess.run(
        [get_settings().ffmpeg_path, "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=320x180:rate=30:duration=3",
         "-vf", "setpts='if(lt(N,30),PTS,PTS+0.5*N/TB/30)'", "-fps_mode", "vfr",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", str(vfr)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    body = upload(client, project, vfr).json()
    assert body["kind"] == "video" and body["duration_seconds"] > 3


def test_a_variable_frame_rate_broll_keeps_the_shorts_frame_rate(tmp_path):
    vfr = tmp_path / "vfr.mp4"
    subprocess.run(
        [get_settings().ffmpeg_path, "-v", "error", "-y", "-f", "lavfi", "-i",
         "color=c=blue:s=320x180:r=30:d=2", "-vf", "setpts='PTS+0.3*N/TB/30'", "-fps_mode", "vfr",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", str(vfr)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    from app.services.ffprobe import probe

    out = tmp_path / "out.mp4"
    main_clip(tmp_path / "main.mp4")
    compose_short(
        tmp_path / "main.mp4", out, layout=Layout.CENTER_CROP, options=OPTIONS, workspace=tmp_path,
        visuals=[layer(vfr, "video", size=(320, 180), start_seconds=0.5, end_seconds=2.0)],
    )  # fmt: skip
    meta = probe(out)
    assert round(meta.fps) == 25 and abs(meta.duration_seconds - 3.0) <= 0.1


# --- storage containment ----------------------------------------------------------------------


def test_crafted_storage_keys_are_contained(client, db_session, project, tmp_path):  # noqa: F811
    escape = VisualAsset(
        project_id=uuid.UUID(project), kind="image", display_name="x.png",
        storage_key="../../../etc/hosts", thumbnail_storage_key="visuals/../../secret.png",
        content_type="image/png", file_size=10, sha256=uuid.uuid4().hex * 2, width=20,
        height=20, codec="png", container="png",
    )  # fmt: skip
    db_session.add(escape)
    db_session.commit()
    assert content(client, project, escape.id).status_code == 404
    assert content(client, project, escape.id, "thumbnail").status_code == 404

    settings = get_settings()
    storage = LocalStorageProvider(Path(settings.media_root))
    edit = make_pipeline_edit(db_session, storage, captions=False, layout="center_crop")
    main_clip(storage.path_for(edit.clip.storage_key), seconds=3.0)
    edit.clip.end_time, edit.clip.duration_seconds = edit.clip.start_time + 3.0, 3.0
    escape.project_id = edit.clip.video.project_id
    db_session.commit()
    config = EditConfig.create(
        layout="center_crop", captions_enabled=False,
        visuals={"elements": [{"asset_id": str(escape.id), "mode": "cutaway",
                               "start_seconds": 0.5, "end_seconds": 1.5}]},
    )  # fmt: skip
    result = run_clip_edit(
        use_config(db_session, edit, config).id, db_session, settings=settings, storage=storage,
        task_id="task-1",
    )  # fmt: skip
    assert result.status == ClipEditStatus.FAILED
    assert result.error_code == "visual_asset_unavailable" and "/" not in result.error_message


# --- B-roll sound -----------------------------------------------------------------------------


def test_broll_sound_never_reaches_the_short(tmp_path):
    loud = tmp_path / "loud.mp4"
    subprocess.run(
        [get_settings().ffmpeg_path, "-v", "error", "-y", "-f", "lavfi", "-i",
         "color=c=blue:s=320x180:r=30:d=3", "-f", "lavfi", "-i",
         "sine=frequency=3000:duration=3:sample_rate=48000", "-af", "volume=8",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac",
         "-shortest", str(loud)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    main_clip(tmp_path / "main.mp4")
    with_broll, plain = tmp_path / "with.mp4", tmp_path / "plain.mp4"
    compose_short(
        tmp_path / "main.mp4", with_broll, layout=Layout.CENTER_CROP, options=OPTIONS,
        workspace=tmp_path,
        visuals=[layer(loud, "video", size=(320, 180), start_seconds=0.5, end_seconds=2.5)],
    )  # fmt: skip
    compose_short(
        tmp_path / "main.mp4", plain, layout=Layout.CENTER_CROP, options=OPTIONS, workspace=tmp_path
    )
    a, b = decode(with_broll), decode(plain)
    assert amplitude(a, 0.6, 2.4, 3000) < 0.005  # none of the B-roll's tone
    assert amplitude(a, 0.6, 2.4, 440) == pytest.approx(amplitude(b, 0.6, 2.4, 440), rel=0.02)
    assert np.max(np.abs(a[: len(b)] - b[: len(a)])) < 0.02  # the same audio, modulo encoding
