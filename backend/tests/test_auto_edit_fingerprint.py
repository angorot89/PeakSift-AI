"""What a plan depends on: equal facts give equal fingerprints (whatever their order), and every
meaningful change gives a new one."""

from dataclasses import replace

import pytest

from app.services.auto_edit.fingerprint import (
    AudioAssetFacts,
    PlanSources,
    SuggestionFacts,
    VisualAssetFacts,
    source_fingerprint,
)

REQUEST = {
    "recipe": "punchy",
    "recipe_version": "punchy_v1",
    "planner_version": "auto_edit_planner_v1",
    "provider": "ollama",
    "model": "llama3.2:3b",
    "music_asset_id": None,
    "generation": 1,
}
BRIDGE = VisualAssetFacts(
    id="a1", kind="image", name="toothpick-bridge.jpg", description="Bridge model",
    tags=("bridge", "corners"), width=1600, height=900, duration=None, has_alpha=False,
)  # fmt: skip
LAUNCH = VisualAssetFacts(
    id="a2", kind="video", name="launch.mp4", description="", tags=(), width=1280, height=720,
    duration=6.0, has_alpha=False,
)  # fmt: skip
MUSIC = AudioAssetFacts(id="m1", kind="music", name="calm.mp3", duration=40.0)
JOINT = SuggestionFacts(id="s1", start=10.2, end=12.7, query="bridge joint", status="suggested")
LAB = SuggestionFacts(id="s2", start=3.0, end=5.0, query="lab bench", status="suggested")
SOURCES = PlanSources(
    clip_id="c1",
    clip_artifact="clips/c1.mp4",
    clip_duration=16.44,
    transcript_fingerprint="t" * 64,
    caption_track_id="track-1",
    reframe_analysis_id="frame-1",
    reframe_confidence="high",
    broll_analysis_id="broll-1",
    suggestions=(JOINT, LAB),
    visual_assets=(BRIDGE, LAUNCH),
    audio_assets=(MUSIC,),
)


def test_the_fingerprint_is_stable_and_order_independent():
    reordered = replace(
        SOURCES,
        suggestions=(LAB, JOINT),
        visual_assets=(LAUNCH, replace(BRIDGE, tags=("corners", "bridge"))),
    )
    assert source_fingerprint(SOURCES, REQUEST) == source_fingerprint(reordered, dict(REQUEST))
    assert len(source_fingerprint(SOURCES, REQUEST)) == 64


def test_float_noise_does_not_create_a_new_plan():
    noisy = replace(SOURCES, clip_duration=16.4400001)
    assert source_fingerprint(noisy, REQUEST) == source_fingerprint(SOURCES, REQUEST)


@pytest.mark.parametrize(
    "changed",
    [
        replace(SOURCES, clip_artifact="clips/c1-rerender.mp4"),
        replace(SOURCES, transcript_fingerprint="u" * 64),
        replace(SOURCES, caption_track_id=None),
        replace(SOURCES, caption_track_id="track-2"),
        replace(SOURCES, reframe_analysis_id=None),
        replace(SOURCES, reframe_confidence="fallback"),
        replace(SOURCES, broll_analysis_id="broll-2"),
        replace(SOURCES, suggestions=(replace(JOINT, status="dismissed"), LAB)),
        replace(SOURCES, suggestions=(JOINT,)),
        replace(SOURCES, visual_assets=(replace(BRIDGE, tags=("bridge", "joint")), LAUNCH)),
        replace(SOURCES, visual_assets=(replace(BRIDGE, description="Truss"), LAUNCH)),
        replace(SOURCES, visual_assets=(BRIDGE,)),
        replace(SOURCES, audio_assets=()),
        replace(SOURCES, audio_assets=(MUSIC, AudioAssetFacts("x1", "sfx", "whoosh.wav", 0.8))),
    ],
)
def test_meaningful_input_changes_make_a_new_plan(changed):
    assert source_fingerprint(changed, REQUEST) != source_fingerprint(SOURCES, REQUEST)


@pytest.mark.parametrize(
    "change",
    [
        {"recipe": "minimal", "recipe_version": "minimal_v1"},
        {"recipe_version": "punchy_v2"},
        {"planner_version": "auto_edit_planner_v2"},
        {"provider": "fallback"},
        {"model": "llama3.1:8b"},
        {"music_asset_id": "m1"},
        {"generation": 2},
    ],
)
def test_request_changes_make_a_new_plan(change):
    assert source_fingerprint(SOURCES, {**REQUEST, **change}) != source_fingerprint(
        SOURCES, REQUEST
    )
