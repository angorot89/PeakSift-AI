"""Private visual asset uploads: content validation (Pillow / ffprobe), normalization (EXIF
orientation, CMYK, 16-bit, transparency, metadata stripping), video geometry (rotation, sample
aspect ratio), thumbnails, limits, duplicates, filename safety, cleanup, search, ownership and
private Range streaming. Fixtures are generated at test time."""

import io
import uuid
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.api.deps import get_storage
from app.core.config import get_settings
from app.main import app
from app.models import VisualAsset
from app.services.media_deletion import visual_asset_ids
from app.services.video_upload import UploadValidationError
from app.services.visual_assets import validate_visual_upload
from tests.media_fixtures import requires_ffmpeg
from tests.storage_backends import provider
from tests.test_video_upload import create_project, sign_up
from tests.visual_fixtures import (
    make_image,
    make_transparent_png,
    make_video,
    rotate_metadata,
)

pytestmark = requires_ffmpeg


def upload(client, project_id, path: Path, name=None, content_type=None):
    file = (name or path.name, path.read_bytes(), content_type or "application/octet-stream")
    return client.post(f"/projects/{project_id}/visual-assets", files={"file": file})


def media_files() -> list[Path]:
    return [p for p in Path(get_settings().media_root).rglob("*") if p.is_file()]


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in media_files():
        path.unlink()


@pytest.fixture
def project(client):
    sign_up(client, f"maker-{uuid.uuid4().hex[:8]}@example.com")
    return create_project(client)["id"]


def content(client, project, asset_id, what="content", **headers):
    return client.get(f"/projects/{project}/visual-assets/{asset_id}/{what}", headers=headers)


def stored_image(client, project, asset_id) -> Image.Image:
    response = content(client, project, asset_id)
    assert response.status_code == 200
    return Image.open(io.BytesIO(response.content))


# --- images ---------------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", [".jpg", ".jpeg", ".png", ".webp"])
def test_images_are_accepted_inspected_and_thumbnailed(client, project, tmp_path, suffix):
    response = upload(client, project, make_image(tmp_path / f"moon{suffix}", (1600, 900)))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "image" and body["display_name"] == f"moon{suffix}"
    assert (body["width"], body["height"]) == (1600, 900)
    assert body["duration_seconds"] is None and body["has_alpha"] is False
    assert body["content_type"] == "image/jpeg" and body["has_thumbnail"] is True
    assert not {"storage_key", "sha256", "thumbnail_storage_key"} & set(body)
    thumb = content(client, project, body["id"], "thumbnail")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    assert thumb.headers["cache-control"] == "private, no-store"
    assert max(Image.open(io.BytesIO(thumb.content)).size) == 480
    assert stored_image(client, project, body["id"]).size == (1600, 900)


def test_transparency_is_kept_only_when_used(client, project, tmp_path):
    clear = upload(client, project, make_transparent_png(tmp_path / "badge.png")).json()
    assert clear["has_alpha"] is True and clear["content_type"] == "image/png"
    assert stored_image(client, project, clear["id"]).getpixel((0, 0))[3] == 0
    thumb = content(client, project, clear["id"], "thumbnail")
    assert thumb.headers["content-type"] == "image/png"
    opaque = make_image(tmp_path / "opaque.png", mode="RGBA", color=(10, 20, 30, 255))
    body = upload(client, project, opaque).json()
    assert body["has_alpha"] is False and body["content_type"] == "image/jpeg"


def test_exif_orientation_is_applied_and_metadata_stripped(client, project, tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to display
    exif[0x010F] = "PhoneMaker"
    exif[0x0131] = "Secret software build"
    path = make_image(tmp_path / "phone.jpg", (400, 300), exif=exif.tobytes())
    body = upload(client, project, path).json()
    assert (body["width"], body["height"]) == (300, 400)  # displayed upright
    stored = stored_image(client, project, body["id"])
    assert stored.size == (300, 400)
    assert not stored.getexif()  # no orientation, maker, software or GPS left
    assert b"PhoneMaker" not in content(client, project, body["id"]).content


def test_cmyk_and_16_bit_images_are_converted_faithfully(client, project, tmp_path):
    cmyk = make_image(tmp_path / "print.jpg", mode="CMYK", color=(0, 255, 255, 0), marker=False)
    body = upload(client, project, cmyk).json()
    red, green, blue = stored_image(client, project, body["id"]).convert("RGB").getpixel((5, 5))
    assert red > 200 and green < 60 and blue < 60  # cyan-free, magenta+yellow = red
    deep = Image.new("I;16", (64, 64), 30000)
    deep.save(tmp_path / "deep.png")
    body = upload(client, project, tmp_path / "deep.png").json()
    value = stored_image(client, project, body["id"]).convert("L").getpixel((5, 5))
    assert 100 < value < 140  # 30000/65535 of full scale, not clipped to white


def test_large_images_are_bounded_for_rendering(client, project, tmp_path):
    body = upload(client, project, make_image(tmp_path / "wide.png", (5000, 1000))).json()
    assert (body["width"], body["height"]) == (3840, 768)


# --- videos ----------------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", [".mp4", ".mov", ".webm"])
def test_videos_are_probed_and_thumbnailed(client, project, tmp_path, suffix):
    path = make_video(tmp_path / f"launch{suffix}", size="320x180", seconds=2.0, audio=True)
    response = upload(client, project, path)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "video" and (body["width"], body["height"]) == (320, 180)
    assert body["duration_seconds"] == pytest.approx(2.0, abs=0.1)
    assert body["fps"] == pytest.approx(30, abs=0.1) and body["has_audio"] is True
    thumb = content(client, project, body["id"], "thumbnail")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(thumb.content)).size == (480, 270)
    full = content(client, project, body["id"])
    assert full.content == path.read_bytes()  # videos are stored unchanged
    part = content(client, project, body["id"], Range="bytes=10-99")
    assert part.status_code == 206 and part.content == path.read_bytes()[10:100]


def test_rotation_and_sample_aspect_give_display_dimensions(client, project, tmp_path):
    base = make_video(tmp_path / "base.mp4", size="320x180")
    portrait = upload(client, project, rotate_metadata(base, tmp_path / "phone.mp4", 90)).json()
    assert (portrait["width"], portrait["height"]) == (180, 320)
    anamorphic = make_video(tmp_path / "wide.mp4", size="160x180", extra_filters="setsar=2")
    body = upload(client, project, anamorphic).json()
    assert (body["width"], body["height"]) == (320, 180)


# --- refusals: nothing is kept ------------------------------------------------------------------


def refused(client, project, response, status: int) -> None:
    assert response.status_code == status, response.text
    assert media_files() == []
    detail = response.json()["detail"]
    assert "/" not in detail or "MB" in detail  # never a path


@pytest.mark.parametrize(
    ("name", "data", "status"),
    [
        ("anim.gif", b"GIF89a....", 415),
        ("notes.txt", b"hello", 415),
        ("fake.jpg", b"\x89PNG\r\n\x1a\n" + b"0" * 64, 415),  # PNG bytes named .jpg
        ("broken.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, 415),
        ("random.mp4", b"\x00\x01garbage" * 50, 422),
        ("empty.png", b"", 400),
    ],
)
def test_wrong_or_corrupt_files_are_refused(client, project, tmp_path, name, data, status):
    (tmp_path / name).write_bytes(data)
    refused(client, project, upload(client, project, tmp_path / name), status)


def test_truncated_images_are_refused(client, project, tmp_path):
    whole = make_image(tmp_path / "whole.jpg", (800, 600)).read_bytes()
    (tmp_path / "cut.jpg").write_bytes(whole[: len(whole) // 2])
    refused(client, project, upload(client, project, tmp_path / "cut.jpg"), 415)


def test_declared_type_must_match_the_extension(client, project, tmp_path):
    path = make_image(tmp_path / "x.png")
    refused(client, project, upload(client, project, path, content_type="video/mp4"), 415)


def test_animated_images_are_refused(client, project, tmp_path):
    frames = [Image.new("RGB", (64, 64), c) for c in ((255, 0, 0), (0, 0, 255))]
    for name in ("anim.png", "anim.webp"):
        frames[0].save(tmp_path / name, save_all=True, append_images=frames[1:], duration=100)
        refused(client, project, upload(client, project, tmp_path / name), 415)


def test_audio_only_files_named_as_video_are_refused(client, project, tmp_path):
    path = make_video(tmp_path / "x.mp4", source="sine=frequency=330:duration=1", audio=False)
    refused(client, project, upload(client, project, path), 415)


@pytest.mark.parametrize(
    ("size", "status"),
    [((12, 64), 422), ((2100, 100), 422)],  # too small; 21:1
)
def test_unusable_geometry_is_refused(client, project, tmp_path, size, status):
    refused(client, project, upload(client, project, make_image(tmp_path / "x.png", size)), status)


def test_limits_are_server_configuration(client, project, tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "visual_asset_max_pixel_count", 100_000)
    refused(
        client, project, upload(client, project, make_image(tmp_path / "a.png", (400, 300))), 413
    )
    monkeypatch.setattr(settings, "visual_asset_max_video_duration_seconds", 1.0)
    video = make_video(tmp_path / "long.mp4", seconds=2.0)
    refused(client, project, upload(client, project, video), 413)
    monkeypatch.setattr(settings, "visual_asset_max_video_duration_seconds", 600.0)
    monkeypatch.setattr(settings, "visual_asset_max_video_pixel_count", 320 * 180 - 1)
    refused(client, project, upload(client, project, video), 413)
    monkeypatch.setattr(settings, "visual_asset_max_bytes", 1024)
    refused(client, project, upload(client, project, video), 413)
    limits = client.get("/visual-upload-limits").json()
    assert limits["max_bytes"] == 1024 and ".webm" in limits["accepted_extensions"]


def test_validation_is_by_extension_and_declared_type():
    assert validate_visual_upload("a/b/../Moon Shot.PNG", "image/png") == (
        "Moon Shot.PNG",
        ".png",
        "image",
    )
    with pytest.raises(UploadValidationError):
        validate_visual_upload("clip.mkv", "video/x-matroska")


# --- duplicates, names, listing, ownership ------------------------------------------------------


def test_the_same_file_twice_is_one_asset(client, db_session, project, tmp_path):
    path = make_image(tmp_path / "moon.png")
    first = upload(client, project, path)
    second = upload(client, project, path, name="moon copy.png")
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    other = create_project(client)["id"]
    assert upload(client, other, path).json()["id"] != first.json()["id"]
    assert db_session.scalar(select(func.count()).select_from(VisualAsset)) == 2
    assert len(media_files()) == 4  # two images + two thumbnails, no leftovers


def test_names_are_sanitized_metadata(client, project, tmp_path):
    path = make_image(tmp_path / "x.png")
    body = upload(client, project, path, name="../../etc/Lune — éclipse 🌙.png").json()
    assert body["display_name"] == "Lune — éclipse 🌙.png"
    disposition = content(client, project, body["id"]).headers["content-disposition"]
    assert disposition.startswith("inline") and "etc" not in disposition


def test_listing_filters_by_kind_and_searches_names(client, project, tmp_path):
    upload(client, project, make_image(tmp_path / "Moon Surface.png", color=(1, 2, 3)))
    upload(client, project, make_image(tmp_path / "rocket_100%.jpg", color=(4, 5, 6)))
    upload(client, project, make_video(tmp_path / "moon launch.mp4"))
    url = f"/projects/{project}/visual-assets"
    # (Newest-first order is not asserted: now() is constant inside the test transaction.)
    names = lambda **q: {a["display_name"] for a in client.get(url, params=q).json()}  # noqa: E731
    assert names() == {"moon launch.mp4", "rocket_100%.jpg", "Moon Surface.png"}
    assert names(kind="image") == {"rocket_100%.jpg", "Moon Surface.png"}
    assert names(q="MOON") == {"moon launch.mp4", "Moon Surface.png"}
    assert names(q="moon launch") == {"moon launch.mp4"}
    assert names(q="100%") == {"rocket_100%.jpg"} and names(q="_") == {"rocket_100%.jpg"}
    assert client.get(url, params={"kind": "gif"}).status_code == 422


def test_assets_are_private_to_their_owner(client, project, tmp_path):
    asset = upload(client, project, make_image(tmp_path / "x.png")).json()["id"]
    base = f"/projects/{project}/visual-assets"
    paths = [base, f"{base}/{asset}", f"{base}/{asset}/content", f"{base}/{asset}/thumbnail"]
    sign_up(client, f"other-{uuid.uuid4().hex[:8]}@example.com")
    for path in paths:
        assert client.get(path).status_code == 404
    assert client.delete(f"{base}/{asset}").status_code == 404
    assert upload(client, project, tmp_path / "x.png").status_code == 404
    client.cookies.clear()
    for path in paths:
        assert client.get(path).status_code == 401


def test_deleting_an_unused_asset_removes_it_and_its_files(client, project, tmp_path):
    asset = upload(client, project, make_video(tmp_path / "x.mp4")).json()["id"]
    response = client.delete(f"/projects/{project}/visual-assets/{asset}")
    assert response.json() == {"media_files_removed": 2, "media_files_pending_cleanup": 0}
    assert media_files() == []
    assert client.get(f"/projects/{project}/visual-assets/{asset}").status_code == 404


def test_edit_references_are_read_from_the_visuals_section():
    config = {"visuals": {"elements": [{"asset_id": "a"}, {"asset_id": "b"}, {}]}}
    assert visual_asset_ids(config) == {"a", "b"}
    assert visual_asset_ids({"audio": {}}) == set() and visual_asset_ids(None) == set()


def test_uploads_work_on_s3_storage(client, project, tmp_path, monkeypatch):
    with provider("s3-moto", tmp_path, monkeypatch) as bucket:
        app.dependency_overrides[get_storage] = lambda: bucket
        try:
            path = make_video(tmp_path / "s3.mp4")
            body = upload(client, project, path).json()
            assert body["kind"] == "video"
            part = content(client, project, body["id"], Range="bytes=0-31")
            assert part.status_code == 206 and part.content == path.read_bytes()[:32]
            assert content(client, project, body["id"], "thumbnail").status_code == 200
            keys = [item.key for item in bucket.list_objects("visuals")]
            assert len(keys) == 2 and media_files() == []
        finally:
            app.dependency_overrides.pop(get_storage, None)
