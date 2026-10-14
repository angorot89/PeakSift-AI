"""Smart crop path planning on controlled subject samples (no detector, no FFmpeg)."""

import math

import pytest

from app.core.config import Settings, get_settings
from app.models.reframe import KeyframeMode, ReframeConfidence
from app.services.reframe.config import ReframeConfig
from app.services.reframe.path import CropGeometry, crop_center_at, plan_crop_path
from app.services.reframe.tracking import SubjectSample, TrackPoint

CONFIG = ReframeConfig.from_settings(Settings(**get_settings().model_dump()))
W, H = 1920, 1080
CROP = 1080 * 9 / 16 / 1920  # 0.3164
PERIOD = 0.5


def point(t, cx, cy=0.4, w=0.06, h=0.11, conf=0.9, track=0):
    return TrackPoint(track, t, cx, cy, w, h, conf, True)


def samples(duration, primary, others=lambda t: ()):
    out = []
    for i in range(int(duration / PERIOD) + 1):
        t = i * PERIOD
        p = primary(t)
        out.append(
            SubjectSample(
                t,
                None if p is None else point(t, **p) if isinstance(p, dict) else p,
                tuple(others(t)),
            )
        )
    return out


def plan(s, duration=10.0, width=W, height=H, config=CONFIG, switches=0):
    return plan_crop_path(
        s,
        source_width=width,
        source_height=height,
        duration=duration,
        config=config,
        switches=switches,
    )


def centers(p):
    return [k.center_x for k in p.keyframes]


def face_inside(p, t, cx, w=0.06):
    c, _ = crop_center_at(p.keyframes, t)
    return (
        c - p.geometry.crop_width / 2 <= cx - w / 2 + 1e-9
        and cx + w / 2 <= c + p.geometry.crop_width / 2 + 1e-9
    )


# --- geometry -----


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((1920, 1080), (CROP, 1.0, "x")),
        ((3840, 2160), (CROP, 1.0, "x")),
        ((1080, 1080), (0.5625, 1.0, "x")),
        ((1080, 1920), (1.0, 1.0, None)),
        ((1080, 2400), (1.0, 0.8, "y")),
    ],
)
def test_crop_geometry_is_9_16_without_stretching(size, expected):
    g = CropGeometry.for_source(*size)
    assert (
        (g.crop_width, g.crop_height, g.axis) == pytest.approx(expected)
        if expected[2]
        else (g.crop_width, g.crop_height, g.axis) == expected
    )
    pixel_w, pixel_h = g.crop_width * size[0], g.crop_height * size[1]
    assert pixel_w / pixel_h == pytest.approx(9 / 16, rel=1e-3)
    assert pixel_w <= size[0] + 1e-6 and pixel_h <= size[1] + 1e-6


def test_invalid_sources_are_refused():
    with pytest.raises(ValueError):
        CropGeometry.for_source(0, 1080)
    with pytest.raises(ValueError):
        plan([], duration=0)


# --- single subject -----


def test_stationary_centered_subject_never_moves_and_is_sparse():
    p = plan(samples(10, lambda t: {"cx": 0.5}))
    assert set(centers(p)) == {0.5} and len(p.keyframes) == 2
    assert p.confidence_level == ReframeConfidence.HIGH and p.fallback_fraction == 0


@pytest.mark.parametrize("cx", [0.12, 0.88])
def test_stationary_subject_near_an_edge_is_framed_and_crop_stays_inside(cx):
    p = plan(samples(10, lambda t: {"cx": cx}))
    assert all(CROP / 2 - 1e-9 <= c <= 1 - CROP / 2 + 1e-9 for c in centers(p))
    assert p.subject_in_crop_fraction == 1.0 and face_inside(p, 5.0, cx)


def test_subject_moving_left_to_right_is_followed_smoothly():
    p = plan(samples(12, lambda t: {"cx": 0.2 + 0.05 * t}), duration=12)  # 0.2 → 0.8
    cs = centers(p)
    assert all(b >= a - 1e-9 for a, b in zip(cs, cs[1:], strict=False))  # never pans backwards
    assert p.subject_in_crop_fraction == 1.0
    assert p.max_pan_speed <= CONFIG.max_pan_per_second + 1e-9


def test_reversing_subject_is_followed_without_overshoot():
    def path(t):
        return {"cx": 0.3 + 0.06 * t if t <= 5 else 0.6 - 0.06 * (t - 5)}

    p = plan(samples(10, path))
    assert p.subject_in_crop_fraction == 1.0
    assert max(centers(p)) <= 0.6 + CROP / 2 and min(centers(p)) >= CROP / 2 - 1e-9


def test_detection_jitter_inside_the_dead_zone_causes_no_movement():
    p = plan(samples(10, lambda t: {"cx": 0.5 + (0.012 if int(t * 2) % 2 else -0.012)}))
    assert max(centers(p)) - min(centers(p)) < 1e-9 and len(p.keyframes) == 2


def test_dead_zone_tolerates_slow_drift_then_follows():
    drift = CONFIG.dead_zone * CROP * 0.8
    p = plan(samples(10, lambda t: {"cx": 0.5 + drift * min(1, t / 5)}))
    assert max(centers(p)) - min(centers(p)) < 1e-9  # stayed inside the dead zone: no pan


def test_large_detector_jump_is_never_a_teleport():
    p = plan(samples(10, lambda t: {"cx": 0.2 if t < 5 else 0.8}))
    assert p.max_pan_speed <= CONFIG.max_pan_per_second + 1e-9
    # Every stretch of the path respects the pan limit, and when the jump is first seen the
    # camera is still on its way (no teleport).
    for t0 in [x / 10 for x in range(0, 95)]:
        a, _ = crop_center_at(p.keyframes, t0)
        z, _ = crop_center_at(p.keyframes, t0 + 0.5)
        assert abs(z - a) <= CONFIG.max_pan_per_second * 0.5 + 1e-6
    final, _ = crop_center_at(p.keyframes, 9.9)
    at_jump, _ = crop_center_at(p.keyframes, 5.0)
    assert final - at_jump > 0.1


def test_lost_subject_eases_to_centre_fallback():
    p = plan(samples(12, lambda t: {"cx": 0.2} if t < 4 else None))
    assert p.fallback_fraction == pytest.approx(17 / 25, abs=1e-3)
    assert p.confidence_level == ReframeConfidence.MIXED
    assert crop_center_at(p.keyframes, 11.5)[0] == pytest.approx(0.5)
    assert p.max_pan_speed <= CONFIG.max_pan_per_second + 1e-9
    modes = [k.mode for k in p.keyframes]
    assert KeyframeMode.TRACKED in modes and KeyframeMode.FALLBACK in modes


def test_no_detections_is_a_valid_centre_fallback_path():
    p = plan(samples(8, lambda t: None))
    assert set(centers(p)) == {0.5} and p.confidence_level == ReframeConfidence.FALLBACK
    assert p.overall_confidence == 0 and p.fallback_fraction == 1
    assert all(k.mode == KeyframeMode.FALLBACK and k.confidence == 0 for k in p.keyframes)
    assert plan([], duration=5).keyframes[-1].timestamp == 5


# --- two people -----


def test_two_people_close_together_are_framed_as_a_group():
    s = samples(10, lambda t: point(t, 0.44, track=0), lambda t: (point(t, 0.58, track=1),))
    p = plan(s)
    late = [k for k in p.keyframes if k.timestamp >= 2]
    assert all(k.mode == KeyframeMode.GROUP for k in late)
    c, _ = crop_center_at(p.keyframes, 6)
    assert c == pytest.approx(0.51, abs=0.03)
    assert face_inside(p, 6, 0.44) and face_inside(p, 6, 0.58)


def test_two_people_far_apart_keep_the_primary_without_split_screen():
    s = samples(10, lambda t: point(t, 0.2, track=0), lambda t: (point(t, 0.8, track=1),))
    p = plan(s)
    assert all(k.mode == KeyframeMode.TRACKED for k in p.keyframes)
    assert face_inside(p, 5, 0.2) and not face_inside(p, 5, 0.8)


def test_a_small_background_face_does_not_pull_the_frame():
    s = samples(
        10,
        lambda t: point(t, 0.45, w=0.08, h=0.14),
        lambda t: (point(t, 0.55, w=0.02, h=0.04, track=1),),
    )
    assert all(k.mode == KeyframeMode.TRACKED for k in plan(s).keyframes)


# --- portrait / square / tall -----


def test_portrait_source_is_already_vertical():
    p = plan(samples(6, lambda t: {"cx": 0.2}), width=1080, height=1920)
    assert p.geometry.axis is None and set(centers(p)) == {0.5}
    assert all((k.crop_width, k.crop_height) == (1.0, 1.0) for k in p.keyframes)


def test_square_source_pans_with_a_wider_crop():
    p = plan(samples(6, lambda t: {"cx": 0.85}), width=1080, height=1080)
    assert p.geometry.crop_width == pytest.approx(0.5625)
    assert crop_center_at(p.keyframes, 3)[0] == pytest.approx(1 - 0.5625 / 2)


def test_very_tall_source_pans_vertically():
    s = [SubjectSample(i * 0.5, point(i * 0.5, 0.5, cy=0.2, h=0.06), ()) for i in range(13)]
    p = plan(s, duration=6, width=1080, height=2400)
    assert p.geometry.axis == "y"
    assert all(k.center_x == 0.5 for k in p.keyframes)
    assert crop_center_at(p.keyframes, 3)[1] == pytest.approx(0.4)  # top-clamped: crop 0.8 tall


# --- guarantees -----


@pytest.mark.parametrize("cx", [0.0, 0.03, 0.97, 1.0])
def test_crop_never_leaves_the_source_even_at_the_edges(cx):
    p = plan(samples(10, lambda t: {"cx": cx, "w": 0.04}))
    for k in p.keyframes:
        assert k.center_x - k.crop_width / 2 >= -1e-9 and k.center_x + k.crop_width / 2 <= 1 + 1e-9


def test_keyframes_are_ordered_and_cover_the_clip():
    p = plan(samples(10, lambda t: {"cx": 0.2 + 0.05 * t}), duration=10.3)
    times = [k.timestamp for k in p.keyframes]
    assert times == sorted(times) and times[0] == 0 and times[-1] == pytest.approx(10.3)
    assert len(p.keyframes) < 10.3 / 0.1  # sparse


def test_output_is_deterministic():
    s = samples(10, lambda t: {"cx": 0.3 + 0.04 * t + (0.01 if int(t * 2) % 2 else 0)})
    assert plan(s) == plan(s)


def test_switches_lower_the_confidence():
    s = samples(10, lambda t: {"cx": 0.5})
    assert plan(s, switches=3).overall_confidence < plan(s).overall_confidence


def test_interpolation_between_keyframes_is_linear():
    p = plan(samples(10, lambda t: {"cx": 0.2 if t < 3 else 0.8}))
    a, b = p.keyframes[1], p.keyframes[2]
    mid = (a.timestamp + b.timestamp) / 2
    assert crop_center_at(p.keyframes, mid)[0] == pytest.approx((a.center_x + b.center_x) / 2)
    assert crop_center_at(p.keyframes, -1)[0] == p.keyframes[0].center_x
    assert crop_center_at(p.keyframes, 99)[0] == p.keyframes[-1].center_x


def test_values_are_finite_and_within_the_database_constraints():
    p = plan(samples(10, lambda t: {"cx": 0.5 + 0.4 * math.sin(t)}))
    for k in p.keyframes:
        assert all(
            math.isfinite(v)
            for v in (
                k.timestamp,
                k.center_x,
                k.center_y,
                k.crop_width,
                k.crop_height,
                k.confidence,
            )
        )
        assert 0 <= k.confidence <= 1 and 0 < k.crop_width <= 1 and k.timestamp >= 0


# --- shot changes, fast movement, leaving and returning -----


def cut_samples(left=0.2, right=0.8, at=5.0, duration=10.0):
    """Shot 1 follows a face at ``left`` (track 0); a hard cut at ``at`` hands off to a face at
    ``right`` (track 1) — what tracking reports for a cut."""
    out = []
    for i in range(int(duration / PERIOD) + 1):
        t = i * PERIOD
        if t < at:
            out.append(SubjectSample(t, point(t, left, track=0), ()))
        else:
            out.append(SubjectSample(t, point(t, right, track=1), (), cut=t == at))
    return out


def test_a_shot_cut_cuts_the_camera_instead_of_panning_across_the_frame():
    p = plan(cut_samples())
    assert p.camera_cuts == 1
    pairs = [
        (a, b)
        for a, b in zip(p.keyframes, p.keyframes[1:], strict=False)
        if b.timestamp - a.timestamp < 0.01
    ]
    assert len(pairs) == 1
    before, after = pairs[0]
    # Halfway between the last sample of shot 1 (4.5 s) and the first of shot 2 (5.0 s).
    assert after.timestamp == pytest.approx(4.75) and before.timestamp == pytest.approx(4.749)
    assert face_inside(p, 4.7, 0.2) and face_inside(p, 4.8, 0.8)
    # No drift toward the next shot before the cut, no slow pan after it.
    assert all(face_inside(p, t / 10, 0.2) for t in range(0, 47))
    assert all(face_inside(p, t / 10, 0.8) for t in range(48, 101))
    # The diagnostics describe pans only; the cut is not reported as a 600 %/s pan.
    assert p.max_pan_speed <= CONFIG.max_pan_per_second + 1e-6
    assert p.subject_in_crop_fraction >= 0.95


def test_a_hand_off_to_a_nearby_face_stays_smooth():
    p = plan(cut_samples(left=0.45, right=0.5))
    assert p.camera_cuts == 0
    assert all(
        b.timestamp - a.timestamp > 0.01 for a, b in zip(p.keyframes, p.keyframes[1:], strict=False)
    )


def test_cut_keyframes_satisfy_the_renderer_and_database_rules():
    from app.services.clip_edit.smart_crop import crop_points_from, smart_crop_filter
    from app.services.reframe.pipeline import validate_keyframes

    p = plan(cut_samples(at=2.5, duration=6.0), duration=6.0)
    validate_keyframes(p.keyframes, 6.0)
    points = crop_points_from(p.keyframes)
    assert all(b.timestamp > a.timestamp for a, b in zip(points, points[1:], strict=False))
    assert "if(lt(t," in smart_crop_filter(points, W, H, 1080, 1920)


def test_a_fast_moving_subject_stays_in_frame():
    # Crossing 60 % of a landscape frame in 3 s (fast for an on-camera presenter).
    p = plan(samples(6.0, lambda t: {"cx": 0.2 + 0.2 * min(t, 3.0)}), duration=6.0)
    assert p.subject_in_crop_fraction >= 0.9
    assert p.max_pan_speed <= CONFIG.max_pan_per_second + 1e-6


def test_a_subject_leaving_and_returning_is_framed_again():
    def person(t):
        return None if 3.0 <= t < 6.0 else {"cx": 0.75}

    p = plan(samples(10.0, person))
    assert p.camera_cuts == 0
    assert face_inside(p, 1.0, 0.75) and face_inside(p, 9.5, 0.75)
    c, _ = crop_center_at(p.keyframes, 5.5)
    assert c == pytest.approx(0.5, abs=0.05)  # centre fallback while nobody is visible
    assert 0.2 < p.fallback_fraction < 0.4


def test_steady_motion_gives_steady_camera_speed_not_sample_rate_pulses():
    # A face crossing the frame at constant speed, sampled at 2 fps: between samples the target
    # is interpolated, so once the camera has caught up it pans at an even speed.
    p = plan(samples(12.0, lambda t: {"cx": 0.2 + 0.05 * t}), duration=12.0)
    speeds = []
    for i in range(30, 100):  # 3.0 s → 10.0 s, in 0.1 s steps
        a, _ = crop_center_at(p.keyframes, i / 10)
        b, _ = crop_center_at(p.keyframes, (i + 1) / 10)
        speeds.append((b - a) / 0.1)
    assert min(speeds) > 0  # always moving with the subject, never stopping and restarting
    assert max(speeds) - min(speeds) < 0.01  # even speed (the subject moves at 0.05/s)
    assert all(face_inside(p, i / 10, 0.2 + 0.05 * i / 10) for i in range(0, 120))
