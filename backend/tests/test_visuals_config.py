"""The visuals section of an edit: allow-listed modes and options, normalization (rounding,
defaults, options that do not apply dropped, order), the overlap policy, snapshots and
fingerprints — and the checks against real assets and the clip."""

import uuid

import pytest

from app.models import VisualAsset
from app.services.clip_edit.config import EditConfig
from app.services.visuals.assets import VisualsProblem, check_visuals
from app.services.visuals.config import MAX_ELEMENTS, VISUALS_VERSION, VisualsConfig

IMAGE, VIDEO = str(uuid.uuid4()), str(uuid.uuid4())


def element(**overrides):
    item = {"asset_id": IMAGE, "mode": "cutaway", "start_seconds": 2.0, "end_seconds": 5.0}
    item.update(overrides)
    return item


def visuals(*items):
    return VisualsConfig.create({"elements": list(items)})


def test_options_are_normalized_per_mode():
    config = visuals(
        element(position="top_left", size="large", opacity=0.5),  # cutaway: only fit applies
        element(mode="pip", start_seconds=6.004, end_seconds=8.996, fit="fit"),
        element(mode="overlay", start_seconds=9, end_seconds=11, opacity=0.756, position="center"),
    )
    cutaway, pip, overlay = (e.snapshot() for e in config.elements)
    assert cutaway == {
        "asset_id": IMAGE, "mode": "cutaway", "start_seconds": 2.0, "end_seconds": 5.0,
        "asset_offset_seconds": 0.0, "loop": False, "fit": "fill",
    }  # fmt: skip
    assert pip["start_seconds"] == 6.0 and pip["end_seconds"] == 9.0
    assert (pip["position"], pip["size"]) == ("top_right", "medium") and "fit" not in pip
    assert "opacity" not in pip
    assert (overlay["position"], overlay["opacity"]) == ("center", 0.76)


def test_order_and_noise_do_not_change_the_fingerprint():
    a = element(start_seconds=1.0, end_seconds=3.0)
    b = element(mode="pip", asset_id=VIDEO, start_seconds=2.0, end_seconds=4.0)
    first = EditConfig.create(
        layout="center_crop", captions_enabled=False, visuals={"elements": [a, b]}
    )
    second = EditConfig.create(
        layout="center_crop", captions_enabled=False,
        visuals={"elements": [b, {**a, "start_seconds": 1.001}]},
    )  # fmt: skip
    assert first.fingerprint() == second.fingerprint()
    assert first.snapshot()["visuals"]["version"] == VISUALS_VERSION
    assert [e["mode"] for e in first.snapshot()["visuals"]["elements"]] == ["cutaway", "pip"]


def test_edits_without_visuals_keep_their_earlier_snapshot_and_fingerprint():
    plain = EditConfig.create(layout="center_crop", captions_enabled=False)
    empty = EditConfig.create(
        layout="center_crop", captions_enabled=False, visuals={"elements": []}
    )
    assert "visuals" not in plain.snapshot() and plain.fingerprint() == empty.fingerprint()
    assert visuals() is None and VisualsConfig.create(None) is None


def test_snapshots_round_trip():
    config = EditConfig.create(
        layout="blur_background", captions_enabled=False,
        visuals={"elements": [
            element(mode="overlay", opacity=0.4, size="small", position="bottom_left")
        ]},
    )  # fmt: skip
    assert EditConfig.from_snapshot(config.snapshot()) == config
    with pytest.raises(ValueError):
        VisualsConfig.from_snapshot({"version": "visuals_v0", "elements": []})


def test_a_cutaway_and_an_inset_may_share_time_but_not_two_of_a_kind():
    assert visuals(element(), element(mode="pip", asset_id=VIDEO, start_seconds=3, end_seconds=6))
    assert visuals(element(), element(start_seconds=5.0, end_seconds=7.0))  # touching is fine
    with pytest.raises(ValueError, match="Two cutaways"):
        visuals(element(), element(start_seconds=4.0, end_seconds=8.0))
    with pytest.raises(ValueError, match="picture-in-picture or overlay"):
        visuals(element(mode="pip"), element(mode="overlay", start_seconds=4.9, end_seconds=6.0))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"mode": "splitscreen"}, "Unsupported visual mode"),
        ({"start_seconds": -1}, "must not be negative"),
        ({"start_seconds": "2"}, "must be a number"),
        ({"end_seconds": float("inf")}, "finite"),
        ({"end_seconds": 2.3}, "at least 0.5 seconds"),
        ({"asset_id": "moon.png"}, "visual asset id"),
        ({"fit": "stretch"}, "Unsupported fit"),
        ({"mode": "pip", "position": "center"}, "corner"),
        ({"mode": "pip", "position": "middle"}, "Unsupported position"),
        ({"mode": "pip", "size": "huge"}, "Unsupported size"),
        ({"mode": "overlay", "opacity": 0.1}, "Opacity must be between"),
        ({"mode": "overlay", "opacity": True}, "must be a number"),
        ({"loop": "yes"}, "loop must be true or false"),
        ({"asset_offset_seconds": -0.5}, "must not be negative"),
    ],
)
def test_invalid_elements_are_refused(overrides, message):
    with pytest.raises(ValueError, match=message):
        visuals(element(**overrides))


def test_the_element_count_is_bounded():
    many = [element(start_seconds=i, end_seconds=i + 0.5) for i in range(MAX_ELEMENTS + 1)]
    with pytest.raises(ValueError, match=f"at most {MAX_ELEMENTS}"):
        visuals(*many)


# --- against real assets and the clip ------------------------------------------------------------


def asset(kind: str, duration: float | None = None) -> VisualAsset:
    return VisualAsset(kind=kind, duration_seconds=duration, width=1920, height=1080)


ASSETS = {IMAGE: asset("image"), VIDEO: asset("video", 6.0)}


@pytest.mark.parametrize(
    ("item", "code", "status"),
    [
        (element(asset_id=str(uuid.uuid4())), "visual_asset_unavailable", 409),
        (element(end_seconds=20.5), "visual_outside_clip", 422),
        (element(asset_offset_seconds=1.0), "visual_image_options", 422),
        (element(loop=True), "visual_image_options", 422),
        (element(asset_id=VIDEO, mode="overlay"), "visual_overlay_video", 422),
        (element(asset_id=VIDEO, asset_offset_seconds=6.0), "visual_offset_outside", 422),
        (element(asset_id=VIDEO, asset_offset_seconds=4.0), "visual_video_too_short", 422),
    ],
)
def test_assets_and_clip_bounds_are_checked(item, code, status):
    with pytest.raises(VisualsProblem) as problem:
        check_visuals(visuals(item), ASSETS, clip_duration=20.0)
    assert (problem.value.code, problem.value.status) == (code, status)


def test_fitting_and_looping_videos_are_accepted():
    check_visuals(
        visuals(
            element(asset_id=VIDEO, asset_offset_seconds=3.0),  # 3 s used of the remaining 3 s
            element(asset_id=VIDEO, mode="pip", start_seconds=10, end_seconds=19, loop=True),
            element(mode="overlay", start_seconds=19, end_seconds=20.0),
        ),
        ASSETS,
        clip_duration=20.0,
    )
