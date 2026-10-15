"""Smart-reframe rendering: crop-path compilation, real FFmpeg renders of a moving marker
(controlled crop path, no detector), captions on top, the edit pipeline and the edit API."""

import math
import re
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ClipEdit, KeyframeMode, ReframeAnalysis, ReframeKeyframe, ReframeStatus
from app.services.clip_edit.caption_styles import build_ass_document
from app.services.clip_edit.captions import Cue
from app.services.clip_edit.composition import CAPTIONS_FILENAME, compose_short
from app.services.clip_edit.config import CaptionPosition, CaptionStyle, EditConfig, Layout
from app.services.clip_edit.smart_crop import (
    MAX_SEGMENTS,
    CropPoint,
    crop_points_from,
    position_expression,
    smart_crop_filter,
)
from app.services.clip_render.renderer import RenderError, RenderOptions
from tests.media_fixtures import FFMPEG, requires_ffmpeg, requires_libass

S = get_settings()
OPTIONS = RenderOptions(
    ffmpeg_path=S.ffmpeg_path, ffprobe_path=S.ffprobe_path, preset="ultrafast", timeout_seconds=180
)
W, H, SECONDS = 1280, 720, 6.0
CROP_W = round(H * 9 / 16) / W  # normalized crop width


def marker_x(t: float) -> float:
    """Centre of the moving white marker in source pixels (40 + 140·t + half its width)."""
    return 70 + 140 * t


def marker_source(target: Path, *, reverse=False, audio=True) -> Path:
    x = "1180-t*140" if reverse else "40+t*140"
    command = [
        FFMPEG,
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x202020:s={W}x{H}:r=25:d={SECONDS}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=white:s=60x120:r=25:d={SECONDS}",
    ]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={SECONDS}"]
    command += [
        "-filter_complex",
        f"[0][1]overlay=x='{x}':y=300",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
    ]
    if audio:
        command += ["-c:a", "aac", "-shortest"]
    command.append(str(target))
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    return target


def following_path(xfun, n=24) -> list[CropPoint]:
    points = []
    for i in range(n + 1):
        t = SECONDS * i / n
        cx = min(1 - CROP_W / 2, max(CROP_W / 2, xfun(t) / W))
        points.append(CropPoint(t, cx, 0.5, CROP_W, 1.0))
    return points


def marker_columns(path: Path, t: float, row: int = 960) -> tuple[int, int] | None:
    raw = subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-ss",
            f"{t:.3f}",
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
    line = raw[1080 * row : 1080 * (row + 1)]
    cols = [i for i, v in enumerate(line) if v > 200]
    return (min(cols), max(cols)) if cols else None


# --- path compilation (no FFmpeg) -----


class K:
    def __init__(self, timestamp, center_x, center_y=0.5, crop_width=CROP_W, crop_height=1.0):
        self.timestamp, self.center_x, self.center_y, self.crop_width, self.crop_height = (
            timestamp,
            center_x,
            center_y,
            crop_width,
            crop_height,
        )


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [K(0, float("nan"))],
        [K(0, 0.5), K(0, 0.6)],  # not strictly increasing
        [K(1, 0.5), K(0.5, 0.6)],
        [K(-1, 0.5)],
        [K(0, 0.05)],  # crop leaves the frame on the left
        [K(0, 0.5), K(1, 0.5, crop_width=0.4)],  # size changes (no zoom in V0.7)
        [K(0, 0.5, crop_width=0)],
        [K(0, True)],
    ],
)
def test_invalid_paths_are_refused(bad):
    with pytest.raises(ValueError):
        crop_points_from(bad)


def test_long_paths_are_thinned_keeping_both_ends():
    keys = [K(i * 0.01, 0.5 + 0.0001 * (i % 7)) for i in range(3000)]
    points = crop_points_from(keys)
    assert (
        len(points) <= MAX_SEGMENTS + 1
        and points[0].timestamp == 0
        and points[-1].timestamp == keys[-1].timestamp
    )


def test_expression_contains_only_numbers_and_fixed_functions():
    graph = smart_crop_filter(following_path(marker_x), W, H, 1080, 1920)
    expressions = re.findall(r"x='([^']*)'|y='([^']*)'", graph)
    text = "".join(a + b for a, b in expressions)
    assert re.fullmatch(r"[0-9t.,+\-*()a-z]*", text)
    assert set(re.findall(r"[a-z]+", text)) <= {"if", "lt", "gte", "clip", "t"}
    assert graph.endswith("scale=1080:1920:flags=lanczos,setsar=1[framed]")


def test_tree_depth_is_logarithmic_and_ends_are_held():
    times = [i * 0.1 for i in range(513)]
    values = [100 + 10 * math.sin(i) for i in range(513)]
    expr = position_expression(times, values, 1000)
    depth = max_depth = 0
    for ch in expr:
        depth += ch == "("
        depth -= ch == ")"
        max_depth = max(max_depth, depth)
    assert max_depth <= 3 * math.ceil(math.log2(512)) + 6
    assert expr.startswith("clip(if(lt(t,0.000000),100.000,if(gte(t,51.200000),")


def test_a_static_path_is_a_constant():
    assert position_expression([0, 1, 2], [300, 300, 300], 1000) == "300.000"
    assert position_expression([0, 1], [-5, -5], 1000) == "0.000"


# --- real FFmpeg renders -----


@requires_ffmpeg
@pytest.mark.parametrize("reverse", [False, True])
def test_moving_marker_stays_in_the_vertical_frame(tmp_path: Path, reverse: bool):
    source = marker_source(tmp_path / "src.mp4", reverse=reverse)
    xfun = (lambda t: 1210 - 140 * t) if reverse else marker_x
    short = compose_short(
        source,
        tmp_path / "out.mp4",
        layout=Layout.SMART_REFRAME,
        options=OPTIONS,
        crop_points=following_path(xfun),
    )
    assert (short.width, short.height) == (1080, 1920)
    assert abs(short.duration_seconds - SECONDS) <= 0.5 and short.audio_codec == "aac"
    for t in (0.2, 1.5, 3.0, 4.5, 5.8):
        cols = marker_columns(short.path, t)
        assert cols is not None, t  # the subject is visible at every checked moment
        center = (cols[0] + cols[1]) / 2
        source_center = xfun(t)
        crop_left = min(W - CROP_W * W, max(0, source_center - CROP_W * W / 2))
        expected = (source_center - crop_left) * 1080 / (CROP_W * W)
        assert abs(center - expected) <= 12, (t, center, expected)
        if 1.0 <= t <= 5.0:  # away from the clamped ends the marker is kept central
            assert 400 <= center <= 680, (t, center)


@requires_ffmpeg
def test_video_only_source_stays_video_only(tmp_path: Path):
    source = marker_source(tmp_path / "src.mp4", audio=False)
    short = compose_short(
        source,
        tmp_path / "out.mp4",
        layout=Layout.SMART_REFRAME,
        options=OPTIONS,
        crop_points=following_path(marker_x),
    )
    assert short.audio_codec is None


@requires_ffmpeg
def test_smart_reframe_without_a_path_is_refused(tmp_path: Path):
    source = marker_source(tmp_path / "src.mp4", audio=False)
    with pytest.raises(RenderError) as info:
        compose_short(source, tmp_path / "out.mp4", layout=Layout.SMART_REFRAME, options=OPTIONS)
    assert info.value.code == "reframe_unavailable" and not (tmp_path / "out.mp4").exists()


@requires_ffmpeg
@requires_libass
def test_captions_stay_fixed_while_the_framing_moves(tmp_path: Path):
    source = marker_source(tmp_path / "src.mp4")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / CAPTIONS_FILENAME).write_text(
        build_ass_document(
            [Cue(0.5, 5.5, "Stable caption")],
            style=CaptionStyle.BOLD,
            position=CaptionPosition.BOTTOM,
            font_family="Noto Sans",
        ),
        encoding="utf-8",
    )
    short = compose_short(
        source,
        workspace / "short.mp4",
        layout=Layout.SMART_REFRAME,
        options=OPTIONS,
        workspace=workspace,
        captions=True,
        crop_points=following_path(marker_x),
    )

    def band(t):
        return subprocess.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-ss",
                f"{t}",
                "-i",
                str(short.path),
                "-frames:v",
                "1",
                "-vf",
                "crop=1080:250:0:1370,format=gray",
                "-f",
                "rawvideo",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=60,
        ).stdout

    a, b, after = band(1.0), band(4.0), band(5.8)
    changed = sum(1 for x, y in zip(a, b, strict=True) if abs(x - y) > 40) / len(a)
    text = sum(1 for x, y in zip(a, after, strict=True) if abs(x - y) > 40) / len(a)
    assert changed < 0.005  # same caption, same place, although the crop moved 420 px
    assert text > 0.01  # and the caption really is there (gone after its cue)
    assert marker_columns(short.path, 1.0) and marker_columns(short.path, 4.0)


# --- configuration -----


def test_smart_reframe_config_requires_an_analysis_and_static_fingerprints_are_unchanged():
    with pytest.raises(ValueError):
        EditConfig.create(layout="smart_reframe", captions_enabled=False)
    analysis = uuid.uuid4()
    config = EditConfig.create(
        layout="smart_reframe", captions_enabled=True, reframe_analysis_id=analysis
    )
    assert config.snapshot()["reframe"] == {"analysis_id": str(analysis)}
    assert EditConfig.from_snapshot(config.snapshot()) == config
    other = EditConfig.create(
        layout="smart_reframe", captions_enabled=True, reframe_analysis_id=uuid.uuid4()
    )
    assert other.fingerprint() != config.fingerprint()
    # V0.6 configurations keep their exact snapshot and fingerprint (dedupe keeps working).
    assert (
        "reframe" not in EditConfig.create(layout="center_crop", captions_enabled=False).snapshot()
    )
    assert EditConfig.create(layout="center_crop", captions_enabled=False).fingerprint() == (
        "4c0faecdfd2869195836178272c438bc9ecc95421037ebca0a4a946629eb3e69"
    )
    assert EditConfig.create(
        layout="blur_background",
        captions_enabled=True,
        caption_style="bold",
        caption_position="bottom",
    ).fingerprint() == ("a8c24dde2530b46a431b322bc7b11ec79c5d368df50ebd1708452a87e49c7abc")


# --- edit pipeline -----


def completed_analysis(
    db: Session, clip, *, points=3, status=ReframeStatus.COMPLETED
) -> ReframeAnalysis:
    from tests.test_reframe_model import make_analysis

    analysis = make_analysis(db, clip, status=status, source_width=1920, source_height=1080)
    for i in range(points):
        db.add(
            ReframeKeyframe(
                analysis=analysis,
                sequence_index=i,
                timestamp=i * 1.0,
                center_x=0.4 + 0.05 * i,
                center_y=0.5,
                crop_width=0.31640625,
                crop_height=1.0,
                confidence=0.9,
                mode=KeyframeMode.TRACKED,
            )
        )
    db.commit()
    return analysis


def smart_edit(db: Session, storage, analysis_id) -> ClipEdit:
    from tests.test_clip_edit_pipeline import make_edit

    edit = make_edit(db, storage, captions=False, layout="center_crop")
    config = EditConfig.create(
        layout="smart_reframe", captions_enabled=False, reframe_analysis_id=analysis_id
    )
    edit.config, edit.config_fingerprint, edit.layout, edit.reframe_analysis_id = (
        config.snapshot(),
        config.fingerprint(),
        "smart_reframe",
        analysis_id,
    )
    db.commit()
    return edit


@pytest.fixture
def storage():
    from app.services.storage import LocalStorageProvider

    yield LocalStorageProvider(Path(S.media_root))
    root = Path(S.media_root)
    for path in sorted(root.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()


def test_pipeline_hands_the_validated_path_to_the_renderer(db_session, storage):
    from tests.test_clip_edit_pipeline import SpyComposer, execute, make_edit

    probe_edit = make_edit(db_session, storage, captions=False)
    analysis = completed_analysis(db_session, probe_edit.clip)
    edit = smart_edit(db_session, storage, analysis.id)
    edit.clip_id = analysis.clip_id
    db_session.commit()
    composer = SpyComposer(db_session, edit)
    result = execute(edit, db_session, get_settings(), storage, composer)
    assert result.status == "ready"
    points = composer.calls[0]["crop_points"]
    assert [p.timestamp for p in points] == [0.0, 1.0, 2.0] and composer.calls[0][
        "layout"
    ] == Layout.SMART_REFRAME


@pytest.mark.parametrize("problem", ["not_completed", "nan"])
def test_pipeline_refuses_an_unusable_analysis(db_session, storage, problem):
    from tests.test_clip_edit_pipeline import SpyComposer, execute, make_edit

    probe_edit = make_edit(db_session, storage, captions=False)
    analysis = completed_analysis(
        db_session,
        probe_edit.clip,
        status=ReframeStatus.COMPLETED if problem == "nan" else ReframeStatus.PLANNING,
    )
    if problem == "nan":  # PostgreSQL accepts NaN timestamps through ">= 0"; the renderer must not
        analysis.keyframes[1].timestamp = float("nan")
        db_session.commit()
    edit = smart_edit(db_session, storage, analysis.id)
    edit.clip_id = analysis.clip_id
    db_session.commit()
    composer = SpyComposer(db_session, edit)
    result = execute(edit, db_session, get_settings(), storage, composer)
    assert result.status == "failed" and composer.calls == []
    assert result.error_code == ("invalid_path" if problem == "nan" else "reframe_unavailable")


# --- edit API -----


@pytest.fixture
def api_queue(monkeypatch):
    from app.api import clip_edits

    monkeypatch.setattr(clip_edits, "enqueue_clip_edit", lambda edit_id, *, task_id: task_id)
    monkeypatch.setattr(clip_edits, "supports_captions", lambda path: True)


def test_smart_edits_require_a_completed_analysis_of_the_same_clip(client, db_session, api_queue):
    from tests.test_clip_edit_api import ready_clip, sign_up

    sign_up(client)
    ctx, other = (
        ready_clip(db_session, "owner@example.com"),
        ready_clip(db_session, "owner@example.com"),
    )
    body = {"layout": "smart_reframe", "captions_enabled": False}
    assert client.post(ctx["base"], json=body).status_code == 422  # no analysis named
    pending = completed_analysis(db_session, ctx["clip"], status=ReframeStatus.PLANNING)
    assert (
        client.post(ctx["base"], json={**body, "reframe_analysis_id": str(pending.id)}).status_code
        == 409
    )
    foreign = completed_analysis(db_session, other["clip"])
    response = client.post(ctx["base"], json={**body, "reframe_analysis_id": str(foreign.id)})
    assert response.status_code == 409 and str(foreign.id) not in response.text
    missing = client.post(ctx["base"], json={**body, "reframe_analysis_id": str(uuid.uuid4())})
    assert missing.status_code == 409


def test_smart_edit_is_created_and_caption_changes_reuse_the_analysis(
    client, db_session, api_queue
):
    from tests.test_clip_edit_api import ready_clip, sign_up

    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")
    analysis = completed_analysis(db_session, ctx["clip"])
    body = {
        "layout": "smart_reframe",
        "captions_enabled": False,
        "reframe_analysis_id": str(analysis.id),
    }
    first = client.post(ctx["base"], json=body)
    assert first.status_code == 201
    data = first.json()
    assert data["layout"] == "smart_reframe" and data["reframe_analysis_id"] == str(analysis.id)
    assert client.post(ctx["base"], json=body).json()["id"] == data["id"]  # deduplicated
    captioned = client.post(
        ctx["base"],
        json={
            **body,
            "captions_enabled": True,
            "caption_style": "bold",
            "caption_position": "bottom",
        },
    )
    assert captioned.status_code == 201 and captioned.json()["id"] != data["id"]
    assert captioned.json()["reframe_analysis_id"] == str(analysis.id)  # no re-analysis needed


def test_static_layouts_cannot_carry_an_analysis(db_session):
    from sqlalchemy.exc import IntegrityError

    from tests.test_clip_edit_model import make_clip, make_edit

    clip = make_clip(db_session)
    analysis = completed_analysis(db_session, clip)
    with pytest.raises(IntegrityError):
        make_edit(db_session, clip, reframe_analysis_id=analysis.id)  # center/blur + analysis
    db_session.rollback()
