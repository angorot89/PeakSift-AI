"""Video semantic indexing: bounded deterministic sampling (targets, candidates, margins),
lightweight black / empty / duplicate filtering, real FFmpeg extraction (rotation, pixel aspect,
VFR, black intro, corrupt input) and per-frame vectors with their times."""

import uuid
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AssetEmbedding, VisualAsset
from app.services.semantic.fake import FakeEmbeddingProvider
from app.services.semantic.indexing import request_index, run_semantic_index
from app.services.semantic.sampling import (
    SamplingError,
    candidate_times,
    evenly,
    extract_frame,
    is_duplicate,
    is_empty,
    sample_video,
    target_count,
)
from app.services.semantic.vectors import cosine
from tests.media_fixtures import requires_ffmpeg
from tests.test_video_upload import create_project, sign_up
from tests.visual_fixtures import ffmpeg, make_video, rotate_metadata

BLUE, RED = "0x2d5fbe", "0xd7462d"  # the fake provider's bridge and rocket


@pytest.fixture(autouse=True)
def manual_indexing(monkeypatch):
    """These tests drive ``request_index`` themselves: uploads here do not start indexing."""
    monkeypatch.setattr("app.api.visual_assets.start_indexing_quietly", lambda *a: None)


# --- planning (pure) ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("duration", "expected"), [(0.5, 1), (2.0, 1), (5.0, 3), (16.0, 8), (600.0, 8), (1800.0, 8)]
)
def test_target_count_is_bounded(duration, expected):
    assert target_count(duration, 8) == expected
    assert target_count(duration, 3) == min(expected, 3)


def test_candidates_are_deterministic_inside_the_video_and_bounded():
    times = candidate_times(600.0, 8)
    assert times == candidate_times(600.0, 8) and len(times) == 16  # 10 minutes: 16 FFmpeg calls
    assert all(0.25 <= t <= 599.75 for t in times) and times == sorted(times)
    short = candidate_times(1.0, 8)
    assert len(short) == 2 and all(0.05 <= t <= 0.95 for t in short)
    assert candidate_times(float("nan"), 8) == [0.0] and candidate_times(0, 8) == [0.0]


def test_evenly_keeps_the_whole_video_represented():
    assert evenly(list(range(10)), 3) == [0, 4, 9]  # (round(4.5) = 4: banker's rounding)
    assert evenly(list(range(10)), 1) == [5]
    assert evenly([1, 2], 5) == [1, 2]


def noisy(colour, size=(320, 180), seed=0) -> Image.Image:
    rng = np.random.default_rng(seed)
    base = np.array(Image.new("RGB", size, colour), float)
    return Image.fromarray(np.clip(base + rng.normal(0, 25, base.shape), 0, 255).astype("uint8"))


def test_black_and_flat_frames_are_empty_but_dark_scenes_with_detail_are_not():
    assert is_empty(Image.new("RGB", (64, 36), (3, 3, 3)))
    assert is_empty(noisy((5, 5, 5)).point(lambda v: min(v, 20)))  # black with sensor noise
    assert is_empty(Image.new("RGB", (64, 36), (240, 240, 240)))  # a flat white card
    night = Image.new("RGB", (64, 36), (8, 8, 12))
    ImageDraw.Draw(night).rectangle((20, 10, 40, 25), fill=(230, 220, 120))  # lit window
    assert not is_empty(night)
    shot = noisy((45, 95, 190))
    ImageDraw.Draw(shot).rectangle((40, 40, 120, 100), fill=(240, 240, 240))  # some structure
    assert not is_empty(shot)


def test_duplicates_are_detected_on_small_thumbnails():
    from app.services.semantic.sampling import _grey

    kept = [_grey(noisy((45, 95, 190), seed=1), 16)]
    assert is_duplicate(noisy((45, 95, 190), seed=2), kept)  # same shot, new noise
    assert not is_duplicate(noisy((215, 70, 45)), kept)


def test_extract_frame_refuses_impossible_times(tmp_path):
    calls = []
    runner = lambda command, timeout: calls.append(command) or 0  # noqa: E731
    for time in (float("nan"), float("inf"), -1.0):
        assert extract_frame(tmp_path / "v.mp4", time, tmp_path / "f.png", ffmpeg_path="ffmpeg",
                             timeout=5, runner=runner) is None  # fmt: skip
    assert calls == []


def test_the_command_is_an_argument_list_with_module_formatted_numbers(tmp_path):
    seen = []

    def runner(command, timeout):
        seen.append((command, timeout))
        return 1

    extract_frame(tmp_path / "v.mp4", 1.23456, tmp_path / "f.png", ffmpeg_path="ffmpeg",
                  timeout=7, runner=runner)  # fmt: skip
    command, timeout = seen[0]
    assert command[command.index("-ss") + 1] == "1.235" and timeout == 7
    assert command[command.index("-frames:v") + 1] == "1"


# --- real FFmpeg ---------------------------------------------------------------------------


# A coloured shot with some structure and sensor noise (a real picture, not a flat card).
SHOT = "drawbox=x=40:y=40:w=80:h=60:color=white:t=fill,noise=alls=20:allf=t"


def colour_video(path: Path, colour: str, seconds: float = 4.0, size: str = "320x180", **kw):
    return make_video(path, source=f"color=c={colour}:size={size}:rate=30:duration={seconds}",
                      seconds=seconds, extra_filters=SHOT, **kw)  # fmt: skip


def sample(path: Path, duration: float, tmp_path: Path, max_frames: int = 8):
    work = tmp_path / f"work-{uuid.uuid4().hex[:6]}"
    work.mkdir()
    return sample_video(path, duration, work, ffmpeg_path=ffmpeg(), max_frames=max_frames,
                        timeout=30)  # fmt: skip


@requires_ffmpeg
def test_a_moving_video_gives_distinct_frames_in_time_order(tmp_path):
    video = make_video(tmp_path / "pattern.mp4", seconds=8.0)  # testsrc2 changes every frame
    frames = sample(video, 8.0, tmp_path)
    assert len(frames) == 4 and [f.time for f in frames] == sorted(f.time for f in frames)
    assert all(f.image.mode == "RGB" and f.image.size == (320, 180) for f in frames)


@requires_ffmpeg
def test_a_static_shot_is_represented_once(tmp_path):
    video = colour_video(tmp_path / "static.mp4", BLUE, seconds=8.0)
    assert len(sample(video, 8.0, tmp_path)) == 1  # the other candidates are duplicates


@requires_ffmpeg
def test_a_black_intro_is_skipped(tmp_path):
    video = make_video(
        tmp_path / "intro.mp4", seconds=6.0,
        source="color=c=black:size=320x180:rate=30:duration=3[a];"
               "testsrc2=size=320x180:rate=30:duration=3[b];[a][b]concat=n=2:v=1:a=0",
    )  # fmt: skip
    frames = sample(video, 6.0, tmp_path)
    assert frames and all(f.time >= 3.0 for f in frames)


@requires_ffmpeg
def test_an_all_black_video_has_no_usable_frames(tmp_path):
    video = make_video(tmp_path / "black.mp4", source="color=c=black:size=160x90:duration=3",
                       seconds=3.0)  # fmt: skip
    with pytest.raises(SamplingError) as error:
        sample(video, 3.0, tmp_path)
    assert error.value.code == "no_frames"


@requires_ffmpeg
def test_rotation_and_pixel_aspect_give_display_frames(tmp_path):
    video = make_video(tmp_path / "wide.mp4", size="320x180", seconds=3.0)
    rotated = rotate_metadata(video, tmp_path / "rotated.mp4", 90)
    assert sample(rotated, 3.0, tmp_path)[0].image.size == (180, 320)
    anamorphic = make_video(tmp_path / "sar.mp4", size="160x180", seconds=3.0,
                            extra_filters="setsar=2")  # fmt: skip
    assert sample(anamorphic, 3.0, tmp_path)[0].image.size == (320, 180)


@requires_ffmpeg
def test_large_frames_are_downscaled_for_analysis(tmp_path):
    video = make_video(tmp_path / "big.mp4", size="1920x1080", seconds=2.0)
    assert sample(video, 2.0, tmp_path)[0].image.size == (640, 360)


@requires_ffmpeg
def test_variable_frame_rate_and_a_duration_past_the_real_end(tmp_path):
    video = make_video(tmp_path / "vfr.mp4", seconds=4.0,
                       extra_filters="setpts='if(lt(T,2),PTS,PTS*3)'")  # fmt: skip
    frames = sample(video, 12.0, tmp_path)  # the probe said longer than the stream really is
    assert frames and all(0 <= f.time < 12.0 for f in frames)


@requires_ffmpeg
def test_a_corrupt_video_is_unreadable(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    with pytest.raises(SamplingError) as error:
        sample(bad, 4.0, tmp_path)
    assert error.value.code == "unreadable_video"


# --- indexing a video ----------------------------------------------------------------------


@pytest.fixture
def settings():
    return get_settings().model_copy(update={"semantic_provider": "fake"})


@requires_ffmpeg
def test_a_video_is_indexed_per_frame_with_times(client, db_session, settings, tmp_path):
    sign_up(client, f"video-{uuid.uuid4().hex[:8]}@example.com")
    project = create_project(client)["id"]
    video = make_video(
        tmp_path / "VID_1429.mp4", seconds=8.0,
        source=f"color=c={BLUE}:size=320x180:rate=30:duration=4[a];"
               f"color=c={RED}:size=320x180:rate=30:duration=4[b];[a][b]concat=n=2:v=1:a=0",
        extra_filters=SHOT,
    )  # fmt: skip
    with video.open("rb") as handle:
        response = client.post(f"/projects/{project}/visual-assets",
                               files={"file": (video.name, handle.read())})  # fmt: skip
    asset = db_session.get(VisualAsset, uuid.UUID(response.json()["id"]))
    fake = FakeEmbeddingProvider()
    index = request_index(db_session, asset, settings)
    assert index.config["video_max_frames"] == settings.semantic_video_max_frames
    run_semantic_index(index.id, db_session, settings=settings, provider=fake,
                       task_id=index.celery_task_id)  # fmt: skip
    assert index.status == "ready", index.error_message
    rows = db_session.scalars(
        select(AssetEmbedding).where(AssetEmbedding.index_id == index.id)
        .order_by(AssetEmbedding.frame_index)
    ).all()  # fmt: skip
    assert len(rows) == index.embedding_count == index.frames_total == index.frames_done == 2
    assert fake.image_calls == 2  # one model run per kept frame, never per decoded frame
    bridge, rocket = fake.embed_text("bridge"), fake.embed_text("rocket launch")
    early, late = (np.asarray(r.embedding) for r in rows)
    assert rows[0].frame_time < 4.0 <= rows[1].frame_time
    assert cosine(bridge, early) > 0.8 > cosine(bridge, late)
    assert cosine(rocket, late) > 0.8 > cosine(rocket, early)


@requires_ffmpeg
def test_the_frame_budget_bounds_model_runs(client, db_session, settings, tmp_path):
    sign_up(client, f"budget-{uuid.uuid4().hex[:8]}@example.com")
    project = create_project(client)["id"]
    video = make_video(tmp_path / "long.mp4", size="160x90", seconds=40.0, fps=10)
    with video.open("rb") as handle:
        response = client.post(f"/projects/{project}/visual-assets",
                               files={"file": (video.name, handle.read())})  # fmt: skip
    asset = db_session.get(VisualAsset, uuid.UUID(response.json()["id"]))
    tight = settings.model_copy(update={"semantic_video_max_frames": 3})
    fake = FakeEmbeddingProvider()
    index = request_index(db_session, asset, tight)
    run_semantic_index(index.id, db_session, settings=tight, provider=fake,
                       task_id=index.celery_task_id)  # fmt: skip
    assert index.status == "ready" and index.embedding_count == 3 and fake.image_calls == 3
