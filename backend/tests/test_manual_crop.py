"""Manual focal-point crop: normalization, geometry at corners/edges, real renders, API."""

import math
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.services.clip_edit.composition import compose_short, manual_crop_point
from app.services.clip_edit.config import EditConfig, Layout
from app.services.clip_render.renderer import RenderError, RenderOptions
from tests.media_fixtures import FFMPEG, requires_ffmpeg

S = get_settings()
OPTIONS = RenderOptions(
    ffmpeg_path=S.ffmpeg_path, ffprobe_path=S.ffprobe_path, preset="ultrafast", timeout_seconds=180
)
CROP_W = 405 / 1280  # 720 · 9/16 = 405 px of 1280


# --- configuration -----


@pytest.mark.parametrize(
    "focus",
    [
        (None, 0.5),
        (0.5, None),
        (-0.01, 0.5),
        (0.5, 1.01),
        (math.nan, 0.5),
        (math.inf, 0.5),
        (True, 0.5),
        ("0.5", 0.5),
    ],
)
def test_manual_crop_needs_a_valid_focal_point(focus):
    with pytest.raises(ValueError):
        EditConfig.create(
            layout="manual_crop", captions_enabled=False, focus_x=focus[0], focus_y=focus[1]
        )


def test_focal_point_is_normalized_so_slider_noise_does_not_create_new_renders():
    a = EditConfig.create(
        layout="manual_crop", captions_enabled=False, focus_x=0.30001, focus_y=0.5
    )
    b = EditConfig.create(
        layout="manual_crop", captions_enabled=False, focus_x=0.30049, focus_y=0.5
    )
    c = EditConfig.create(layout="manual_crop", captions_enabled=False, focus_x=0.302, focus_y=0.5)
    assert a.fingerprint() == b.fingerprint() != c.fingerprint()
    assert a.snapshot()["focus"] == {"x": 0.3, "y": 0.5}
    assert EditConfig.from_snapshot(a.snapshot()) == a
    assert "focus" not in EditConfig.create(layout="center_crop", captions_enabled=False).snapshot()
    # other layouts ignore a stray focal point instead of fingerprinting it
    assert EditConfig.create(
        layout="center_crop", captions_enabled=False, focus_x=0.2, focus_y=0.2
    ).fingerprint() == ("4c0faecdfd2869195836178272c438bc9ecc95421037ebca0a4a946629eb3e69")


# --- geometry -----


@pytest.mark.parametrize(
    ("focus", "expected_x"),
    [
        ((0.5, 0.5), 0.5),
        ((0.0, 0.0), CROP_W / 2),  # top-left corner
        ((1.0, 1.0), 1 - CROP_W / 2),  # bottom-right corner
        ((0.0, 1.0), CROP_W / 2),
        ((1.0, 0.0), 1 - CROP_W / 2),
        ((0.1, 0.5), CROP_W / 2),  # near the left edge: clamped
        ((0.8, 0.5), 0.8),  # inside: centred on the point
    ],
)
def test_crop_is_centred_on_the_point_and_never_leaves_the_frame(focus, expected_x):
    p = manual_crop_point(1280, 720, focus)
    assert p.center_x == pytest.approx(expected_x) and p.center_y == 0.5  # full height: no y pan
    assert p.crop_width == pytest.approx(CROP_W) and p.crop_height == 1
    assert p.center_x - p.crop_width / 2 >= -1e-9 and p.center_x + p.crop_width / 2 <= 1 + 1e-9


def test_portrait_and_square_sources():
    portrait = manual_crop_point(1080, 1920, (0.1, 0.9))
    assert (portrait.center_x, portrait.center_y, portrait.crop_width) == (0.5, 0.5, 1.0)
    square = manual_crop_point(1000, 1000, (0.9, 0.1))
    assert square.crop_width == pytest.approx(0.5625) and square.center_x == pytest.approx(
        1 - 0.5625 / 2
    )


def test_invalid_focus_is_a_safe_render_error():
    with pytest.raises(RenderError) as info:
        manual_crop_point(1280, 720, (1.5, 0.5))
    assert info.value.code == "invalid_focus"


# --- real renders -----


def static_marker(target: Path) -> Path:
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x202020:s=1280x720:r=25:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=60x120:r=25:d=2",
            "-filter_complex",
            "[0][1]overlay=x=1000:y=300",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return target


def marker_columns(path: Path) -> tuple[int, int] | None:
    raw = subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-ss",
            "1",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout
    cols = [i for i, v in enumerate(raw[1080 * 960 : 1080 * 961]) if v > 200]
    return (min(cols), max(cols)) if cols else None


@requires_ffmpeg
def test_render_follows_the_chosen_point(tmp_path: Path):
    source = static_marker(tmp_path / "src.mp4")
    centred = compose_short(
        source,
        tmp_path / "a.mp4",
        layout=Layout.MANUAL_CROP,
        options=OPTIONS,
        focus=(1030 / 1280, 0.5),
    )
    assert (centred.width, centred.height) == (1080, 1920)
    cols = marker_columns(centred.path)
    assert cols is not None and abs((cols[0] + cols[1]) / 2 - 540) <= 8
    left = compose_short(
        source, tmp_path / "b.mp4", layout=Layout.MANUAL_CROP, options=OPTIONS, focus=(0.0, 0.5)
    )
    assert marker_columns(left.path) is None  # the crop sits at the left edge, away from the marker
    right = compose_short(
        source, tmp_path / "c.mp4", layout=Layout.MANUAL_CROP, options=OPTIONS, focus=(1.0, 0.5)
    )
    cols = marker_columns(right.path)
    assert cols is not None and cols[1] < 1080  # clamped at the right edge: still visible, inside


@requires_ffmpeg
def test_manual_crop_without_a_point_is_refused(tmp_path: Path):
    with pytest.raises(RenderError) as info:
        compose_short(
            static_marker(tmp_path / "src.mp4"),
            tmp_path / "x.mp4",
            layout=Layout.MANUAL_CROP,
            options=OPTIONS,
        )
    assert info.value.code == "invalid_focus"


# --- API and database -----


@pytest.fixture
def api_queue(monkeypatch):
    from app.api import clip_edits

    monkeypatch.setattr(clip_edits, "enqueue_clip_edit", lambda edit_id, *, task_id: task_id)
    monkeypatch.setattr(clip_edits, "supports_captions", lambda path: True)


def test_api_validates_and_deduplicates_manual_crops(client, db_session, api_queue):
    from tests.test_clip_edit_api import ready_clip, sign_up

    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    body = {"layout": "manual_crop", "captions_enabled": False}
    assert client.post(ctx["base"], json=body).status_code == 422
    for bad in (
        {"focus_x": 1.5, "focus_y": 0.5},
        {"focus_x": -1, "focus_y": 0.5},
        {"focus_x": "left", "focus_y": 0.5},
        {"focus_x": 0.5},
    ):
        response = client.post(ctx["base"], json={**body, **bad})
        assert response.status_code == 422, bad
        assert "left" not in response.text  # submitted values are not echoed
    first = client.post(ctx["base"], json={**body, "focus_x": 0.30001, "focus_y": 0.5})
    assert first.status_code == 201
    data = first.json()
    assert (data["layout"], data["focus_x"], data["focus_y"]) == ("manual_crop", 0.3, 0.5)
    again = client.post(ctx["base"], json={**body, "focus_x": 0.30004, "focus_y": 0.5})
    assert again.status_code == 200 and again.json()["id"] == data["id"]


def test_database_requires_a_point_exactly_for_manual_crops(db_session):
    from tests.test_clip_edit_model import make_clip, make_edit

    clip = make_clip(db_session)
    with pytest.raises(IntegrityError):
        make_edit(db_session, clip, focus_x=0.5, focus_y=0.5)  # a static layout with a point
    db_session.rollback()
    manual = EditConfig.create(
        layout="manual_crop", captions_enabled=False, focus_x=0.5, focus_y=0.5
    )
    with pytest.raises(IntegrityError):
        make_edit(db_session, clip, config=manual)  # manual crop without the point columns
    db_session.rollback()
    with pytest.raises(IntegrityError):
        make_edit(db_session, clip, config=manual, focus_x=1.5, focus_y=0.5)
    db_session.rollback()
    make_edit(db_session, clip, config=manual, focus_x=0.5, focus_y=0.5)
