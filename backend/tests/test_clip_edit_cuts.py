"""Tighten: removed ranges in an edit, the tightened render and the moved timings."""

import pytest

from app.models import ClipEditStatus
from app.services.clip_edit.config import EditConfig
from app.services.clip_edit.cuts import CUTS_VERSION, CutsConfig, remap_crop_points
from app.services.clip_edit.pipeline import run_clip_edit
from app.services.clip_edit.smart_crop import CropPoint, crop_points_from
from app.services.clip_edit.tighten import tighten_clip, tighten_graph
from app.services.clip_render.renderer import RenderOptions
from app.services.ffprobe import probe
from tests.media_fixtures import generate_video, requires_ffmpeg, requires_libass
from tests.test_clip_edit_api import BLUR_BOLD, ready_clip, sign_up
from tests.test_clip_edit_pipeline import (  # noqa: F401 (fixtures)
    SpyComposer,
    clean_media_root,
    execute,
    make_edit,
    settings,
    storage,
)

# --- the section ---------------------------------------------------------------------


def test_ranges_are_rounded_sorted_and_merged():
    cuts = CutsConfig.create({"removed": [[5.0, 6.0], [1.00049, 2.0], [1.5, 2.5], [2.52, 3.0]]})
    # 1.0–2.5 and 2.52–3.0 merge: the 0.02 s left between them is a sliver, not a piece.
    assert cuts.removed == ((1.0, 3.0), (5.0, 6.0))


def test_nothing_removed_is_no_section():
    assert CutsConfig.create(None) is None
    assert CutsConfig.create({"removed": []}) is None
    assert CutsConfig.create([[1.0, 1.02]]) is None  # shorter than a useful cut


@pytest.mark.parametrize(
    "value",
    [
        "1-2",
        [[2.0, 1.0]],
        [[-1.0, 1.0]],
        [[1.0]],
        [[1.0, float("nan")]],
        [[True, 2.0]],
        [[i, i + 0.5] for i in range(301)],
    ],
)
def test_invalid_ranges_are_refused(value):
    with pytest.raises(ValueError):
        CutsConfig.create(value)


def test_earlier_edits_keep_their_snapshot_and_fingerprint():
    plain = EditConfig.create(layout="center_crop", captions_enabled=False)
    empty = EditConfig.create(layout="center_crop", captions_enabled=False, cuts={"removed": []})
    assert "cuts" not in plain.snapshot()
    assert plain.fingerprint() == empty.fingerprint()


def test_cuts_are_part_of_the_snapshot_and_round_trip():
    config = EditConfig.create(
        layout="center_crop", captions_enabled=False, cuts={"removed": [[0.5, 1.25]]}
    )
    snapshot = config.snapshot()
    assert snapshot["cuts"] == {"version": CUTS_VERSION, "removed": [[0.5, 1.25]]}
    assert EditConfig.from_snapshot(snapshot) == config
    plain = EditConfig.create(layout="center_crop", captions_enabled=False)
    assert config.fingerprint() != plain.fingerprint()


def test_unknown_cuts_version_is_refused():
    snapshot = EditConfig.create(
        layout="center_crop", captions_enabled=False, cuts=[[0.5, 1.0]]
    ).snapshot()
    snapshot["cuts"]["version"] = "cuts_v9"
    with pytest.raises(ValueError):
        EditConfig.from_snapshot(snapshot)


# --- the time map ----------------------------------------------------------------------


def test_kept_parts_and_the_time_map():
    cuts = CutsConfig.create([[1.0, 2.0], [4.0, 4.5]])
    assert cuts.kept(6.0) == [(0.0, 1.0), (2.0, 4.0), (4.5, 6.0)]
    assert cuts.output_duration(6.0) == pytest.approx(4.5)
    assert cuts.to_output(0.5) == 0.5
    assert cuts.to_output(1.5) == pytest.approx(1.0)  # inside a cut: lands on the join
    assert cuts.to_output(3.0) == pytest.approx(2.0)
    assert cuts.to_output(5.0) == pytest.approx(3.5)
    assert cuts.span(1.2, 1.8) is None  # entirely cut away
    assert cuts.span(0.8, 2.4) == pytest.approx((0.8, 1.4))  # a cut runs through it
    assert CutsConfig.create([[0.0, 1.0]]).kept(3.0) == [(1.0, 3.0)]  # leading silence
    assert CutsConfig.create([[2.0, 3.0]]).kept(3.0) == [(0.0, 2.0)]  # trailing silence


def test_cuts_must_fit_the_clip_and_leave_something():
    CutsConfig.create([[1.0, 3.02]]).check(3.0)  # container rounding at the end is fine
    with pytest.raises(ValueError, match="after the end"):
        CutsConfig.create([[1.0, 4.0]]).check(3.0)
    with pytest.raises(ValueError, match="at least one second"):
        CutsConfig.create([[0.0, 2.5]]).check(3.0)


def test_the_framing_path_moves_with_the_cuts_and_jumps_at_a_join():
    points = crop_points_from(
        [
            CropPoint(0.0, 0.3, 0.5, 0.3, 1.0),
            CropPoint(2.0, 0.5, 0.5, 0.3, 1.0),
            CropPoint(4.0, 0.7, 0.5, 0.3, 1.0),
        ]
    )
    cuts = CutsConfig.create([[1.0, 3.0]])
    moved = remap_crop_points(cuts, points, 4.0)
    validated = crop_points_from(moved)  # still a valid path: ordered, same crop size
    times = [p.timestamp for p in validated]
    assert times[0] == 0.0 and times[-1] <= cuts.output_duration(4.0)
    # Just before the join the crop holds the framing at 1.0 s; at the join it is the 3.0 s one.
    before = max((p for p in validated if p.timestamp < 1.0), key=lambda p: p.timestamp)
    at_join = next(p for p in validated if p.timestamp == pytest.approx(1.0))
    assert before.center_x == pytest.approx(0.4) and at_join.center_x == pytest.approx(0.6)
    assert all(abs(p.center_x - 0.5) > 1e-6 for p in validated)  # the 2.0 s keyframe was cut


def test_graph_joins_pieces_with_short_audio_fades():
    graph = tighten_graph([(0.0, 1.0), (2.0, 3.5)], has_audio=True)
    assert "trim=start=0.000:end=1.000" in graph and "atrim=start=2.000:end=3.500" in graph
    assert "afade=t=in" in graph and "concat=n=2:v=1:a=1[v][a]" in graph
    silent = tighten_graph([(0.0, 1.0)], has_audio=False)
    assert "atrim" not in silent and silent.endswith("concat=n=1:v=1:a=0[v]")


@requires_ffmpeg
def test_tightened_clip_has_exactly_the_kept_length(tmp_path):
    source = generate_video(tmp_path / "clip.mp4", seconds=3.0)
    out = tighten_clip(source, tmp_path, [(0.0, 1.0), (2.0, 3.0)], RenderOptions())
    meta = probe(out)
    assert meta.duration_seconds == pytest.approx(2.0, abs=0.15)
    assert meta.audio_codec is not None and meta.video_codec == "h264"
    assert source.stat().st_size > 0  # the clip itself is untouched


# --- the render ----------------------------------------------------------------------


def with_cuts(db_session, edit, removed):
    config = EditConfig.from_snapshot(edit.config)
    config = EditConfig.create(
        layout=config.layout.value,
        captions_enabled=config.captions_enabled,
        caption_style=config.caption_style.value if config.caption_style else None,
        caption_position=config.caption_position.value if config.caption_position else None,
        cuts=removed,
    )
    edit.config = config.snapshot()
    edit.config_fingerprint = config.fingerprint()
    db_session.commit()
    return edit


@requires_ffmpeg
def test_captions_follow_the_cuts(db_session, settings, storage):  # noqa: F811
    # The clip covers 2–5 s of the source; its transcript lines sit at 1.0–3.5 and 3.5–6.0.
    edit = with_cuts(db_session, make_edit(db_session, storage), [[0.2, 1.2]])
    composer = SpyComposer(db_session, edit)
    execute(edit, db_session, settings, storage, composer)

    (call,) = composer.calls
    assert call["source"].name == "tightened.mkv"  # composed from the kept parts

    def seconds(stamp: str) -> float:
        h, m, s = stamp.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    dialogues = [
        line.split(",", 9)
        for line in composer.captions_text.splitlines()
        if line.startswith("Dialogue:")
    ]
    assert dialogues
    for fields in dialogues:
        assert 0.0 <= seconds(fields[1]) < seconds(fields[2]) <= 2.0 + 0.01  # the Short is 2 s


@requires_ffmpeg
@requires_libass
def test_real_render_with_cuts_is_shorter_and_valid(db_session, settings, storage):  # noqa: F811
    edit = with_cuts(db_session, make_edit(db_session, storage), [[0.5, 1.5]])
    result = run_clip_edit(
        edit.id, db_session, settings=settings, storage=storage, task_id="task-1"
    )
    assert result.status == ClipEditStatus.READY, result.error_message
    assert result.duration_seconds == pytest.approx(2.0, abs=0.3)
    assert (result.width, result.height) == (1080, 1920) and result.audio_codec == "aac"


def test_cuts_the_clip_no_longer_allows_fail_safely(db_session, settings, storage):  # noqa: F811
    edit = make_edit(db_session, storage, captions=False)
    snapshot = dict(edit.config)
    snapshot["cuts"] = {"version": CUTS_VERSION, "removed": [[1.0, 9.0]]}
    edit.config = snapshot
    db_session.commit()
    result = execute(edit, db_session, settings, storage, SpyComposer(db_session, edit))
    assert result.status == ClipEditStatus.FAILED and result.error_code == "invalid_cuts"


# --- the API ---------------------------------------------------------------------------


def test_api_accepts_cuts_and_checks_them_against_the_clip(client, db_session):
    sign_up(client)
    ctx = ready_clip(db_session, "owner@example.com")  # a 20 s clip

    created = client.post(ctx["base"], json={**BLUR_BOLD, "cuts": {"removed": [[2, 3], [0, 1]]}})
    assert created.status_code == 201, created.text
    assert created.json()["configuration"]["cuts"] == {
        "version": CUTS_VERSION,
        "removed": [[0.0, 1.0], [2.0, 3.0]],
    }

    beyond = client.post(ctx["base"], json={**BLUR_BOLD, "cuts": {"removed": [[15, 25]]}})
    assert beyond.status_code == 422 and "end of the clip" in beyond.json()["detail"]
    nearly_all = client.post(ctx["base"], json={**BLUR_BOLD, "cuts": {"removed": [[0, 19.5]]}})
    assert nearly_all.status_code == 422
    malformed = client.post(ctx["base"], json={**BLUR_BOLD, "cuts": {"removed": [[3, 2]]}})
    assert malformed.status_code == 422
    unknown = client.post(ctx["base"], json={**BLUR_BOLD, "cuts": {"removed": [], "x": 1}})
    assert unknown.status_code == 422
