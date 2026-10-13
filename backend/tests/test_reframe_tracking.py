"""Temporal association and subject selection on controlled detections (no detector)."""

import pytest

from app.services.reframe.detection import BoundingBox, DetectionType, SubjectDetection
from app.services.reframe.tracking import (
    MIN_OBSERVATIONS,
    SWITCH_HOLD_SECONDS,
    associate,
    track_subjects,
)

PERIOD = 0.5  # 2 fps
GAP = 1.5  # the default REFRAME_MAX_GAP_SECONDS


def face(t, cx, cy=0.4, w=0.06, h=0.11, conf=0.9):
    return SubjectDetection(t, DetectionType.FACE, conf, BoundingBox(cx - w / 2, cy - h / 2, w, h))


def frames(n, *people):
    """``people`` are functions t -> face or None; returns [(t, [faces...])] at 2 fps."""
    out = []
    for i in range(n):
        t = i * PERIOD
        out.append((t, [f for p in people if (f := p(t)) is not None]))
    return out


def run(fr):
    return track_subjects(fr, max_gap=GAP, sample_period=PERIOD)


def primary_x(result):
    return [None if s.primary is None else round(s.primary.center_x, 3) for s in result.samples]


def test_single_stationary_face_is_one_track_followed_throughout():
    result = run(frames(10, lambda t: face(t, 0.3)))
    assert len(result.tracks) == 1 and result.switches == 0
    assert primary_x(result) == [0.3] * 10
    assert all(s.primary.observed for s in result.samples)


def test_single_moving_face_stays_one_track():
    result = run(frames(20, lambda t: face(t, 0.2 + 0.06 * t)))  # crosses 60% of the frame
    assert len(result.tracks) == 1 and result.switches == 0
    assert primary_x(result)[-1] == pytest.approx(0.2 + 0.06 * 9.5, abs=1e-3)


def test_a_gap_longer_than_the_limit_starts_a_new_track():
    result = run(frames(12, lambda t: None if 1.5 <= t <= 3.0 else face(t, 0.4)))  # 2 s gap
    assert len(result.tracks) == 2
    assert [s.primary is None for s in result.samples][3:7] == [False, False, True, True]


def test_a_missed_detection_is_interpolated_not_dropped():
    def person(t):
        return None if t in (2.0, 2.5) else face(t, 0.2 + 0.05 * t)

    result = run(frames(10, person))
    assert len(result.tracks) == 1
    gap = [s for s in result.samples if s.timestamp in (2.0, 2.5)]
    assert all(s.primary is not None and not s.primary.observed for s in gap)
    assert gap[0].primary.center_x == pytest.approx(0.3, abs=1e-6)  # linear between 1.5 and 3.0


def test_a_face_lost_at_the_end_is_held_with_decaying_confidence_then_released():
    result = run(frames(10, lambda t: face(t, 0.5) if t <= 2.0 else None))
    held = {s.timestamp: s.primary for s in result.samples}
    assert held[2.5] is not None and held[2.5].confidence == pytest.approx(0.6)  # 1/3 of the gap
    assert held[3.0] is not None and held[3.0].confidence == pytest.approx(0.3)
    assert held[3.5] is None and held[4.5] is None  # the gap is over: fallback, not a teleport


def test_two_separated_faces_are_two_tracks_and_the_larger_is_followed():
    result = run(
        frames(10, lambda t: face(t, 0.25, w=0.05, h=0.09), lambda t: face(t, 0.75, w=0.09, h=0.16))
    )
    assert len(result.tracks) == 2 and result.switches == 0
    assert set(primary_x(result)) == {0.75}
    assert all(len(s.others) == 1 for s in result.samples)


def test_crossing_faces_keep_their_identities():
    left = lambda t: face(t, 0.2 + 0.1 * t, w=0.06)  # noqa: E731
    right = lambda t: face(t, 0.8 - 0.1 * t, w=0.06, cy=0.45)  # noqa: E731
    tracks = associate(frames(12, left, right), max_gap=GAP, sample_period=PERIOD)
    assert len(tracks) == 2
    a, b = sorted(tracks, key=lambda t: t.observations[0].box.center_x)
    assert a.observations[-1].box.center_x > 0.6 and b.observations[-1].box.center_x < 0.4


def test_a_new_face_does_not_steal_the_frame_instantly():
    host = lambda t: face(t, 0.4, w=0.06)  # noqa: E731
    guest = lambda t: face(t, 0.7, w=0.12) if t >= 2.0 else None  # noqa: E731  bigger, appears later
    result = run(frames(16, host, guest))
    by_time = {s.timestamp: round(s.primary.center_x, 2) for s in result.samples}
    assert by_time[2.0] == 0.4 and by_time[2.5] == 0.4  # hysteresis holds the current subject
    switch_at = min(t for t, x in by_time.items() if x == 0.7)
    assert switch_at >= 2.0 + SWITCH_HOLD_SECONDS - 1e-9
    assert result.switches == 1


def test_dominant_face_leaving_hands_over_once():
    host = lambda t: face(t, 0.4, w=0.1) if t < 3.0 else None  # noqa: E731
    guest = lambda t: face(t, 0.7, w=0.05)  # noqa: E731
    result = run(frames(16, host, guest))
    xs = primary_x(result)
    assert xs[0] == 0.4 and xs[-1] == 0.7 and result.switches == 1
    # The guest was on screen with the host all along: a hand-over, not a shot change.
    assert not any(s.cut for s in result.samples)


def test_short_detection_glitch_never_steers():
    host = lambda t: face(t, 0.4)  # noqa: E731
    glitch = lambda t: face(t, 0.9, w=0.2, h=0.3) if t == 2.5 else None  # noqa: E731  one-frame false positive
    result = run(frames(10, host, glitch))
    assert set(primary_x(result)) == {0.4} and result.switches == 0
    assert MIN_OBSERVATIONS == 2


def test_alternating_scores_do_not_flicker_between_people():
    # Two similar faces whose sizes trade places every sample: the subject must not alternate.
    a = lambda t: face(t, 0.3, w=0.06 if int(t * 2) % 2 else 0.07)  # noqa: E731
    b = lambda t: face(t, 0.7, w=0.07 if int(t * 2) % 2 else 0.06)  # noqa: E731
    result = run(frames(20, a, b))
    assert result.switches == 0 and len(set(primary_x(result))) == 1


def test_ties_are_broken_deterministically():
    a = lambda t: face(t, 0.3)  # noqa: E731
    b = lambda t: face(t, 0.7)  # noqa: E731
    first, second = run(frames(8, a, b)), run(frames(8, b, a))
    assert primary_x(first) == primary_x(second)


def test_no_detections_gives_no_subject():
    result = run(frames(6))
    assert (
        result.tracks == []
        and all(s.primary is None for s in result.samples)
        and result.switches == 0
    )


def test_output_is_deterministic():
    fr = frames(
        20, lambda t: face(t, 0.2 + 0.05 * t), lambda t: face(t, 0.8, w=0.05) if t > 3 else None
    )
    assert run(fr) == run(fr)


def test_a_far_jump_starts_a_new_track_rather_than_teleporting():
    # Same size, but the face jumps across the frame between two samples (e.g. a cut).
    jumper = lambda t: face(t, 0.15 if t < 2.5 else 0.85)  # noqa: E731
    tracks = associate(frames(10, jumper), max_gap=GAP, sample_period=PERIOD)
    assert len(tracks) == 2


# --- shot changes (hand-offs) -----


def test_a_hard_cut_hands_the_frame_to_the_new_face_at_once():
    # Shot 1: a face on the left until 3 s. Shot 2: a different face on the right from 3.5 s.
    shot1 = lambda t: face(t, 0.2) if t < 3.5 else None  # noqa: E731
    shot2 = lambda t: face(t, 0.8) if t >= 3.5 else None  # noqa: E731
    result = run(frames(14, shot1, shot2))
    xs = primary_x(result)
    # No waiting on the old face's held box: the very first sample of shot 2 follows it.
    assert xs[:7] == [0.2] * 7 and xs[7:] == [0.8] * 7
    cuts = [s.timestamp for s in result.samples if s.cut]
    assert cuts == [3.5] and result.switches == 1


def test_a_brief_miss_of_the_subject_is_not_a_cut():
    # The subject is missed for one sample while a second face (seen all along) is visible.
    host = lambda t: None if t == 2.0 else face(t, 0.4, w=0.1)  # noqa: E731
    guest = lambda t: face(t, 0.8, w=0.05)  # noqa: E731
    result = run(frames(12, host, guest))
    assert set(primary_x(result)) == {0.4} and result.switches == 0
    assert not any(s.cut for s in result.samples)


def test_a_face_returning_after_a_long_absence_is_followed_without_a_cut_flag():
    # Gone for 3 s (longer than the gap limit): centre fallback in between, then a new track.
    person = lambda t: None if 2.0 <= t < 5.0 else face(t, 0.7)  # noqa: E731
    result = run(frames(16, person))
    xs = primary_x(result)
    assert xs[0] == 0.7 and xs[-1] == 0.7 and None in xs
    assert len(result.tracks) == 2 and not any(s.cut for s in result.samples)
