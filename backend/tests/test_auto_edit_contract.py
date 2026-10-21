"""The planner contract: a strict proposal schema (extra keys, unknown options and oversized text
are refused), safe errors, an inlined JSON schema for structured output, and a planner view
that carries facts and symbolic handles but never an id."""

import json
import re

import pytest

from app.services.auto_edit.contract import (
    MUSIC_HANDLE,
    SUGGESTION_HANDLE,
    VISUAL_HANDLE,
    AudioOption,
    AutoEditContext,
    AutoEditPlanner,
    AutoEditProposal,
    BrollOption,
    Capabilities,
    PlannerConfigurationError,
    PlannerOutputError,
    PlannerResult,
    PlannerTimeoutError,
    PlannerUnavailableError,
    TimedLine,
    VisualOption,
    orientation,
    parse_proposal,
    proposal_json_schema,
)
from app.services.auto_edit.recipes import current_recipe

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

GOOD = {
    "layout": {"mode": "smart_reframe"},
    "captions": {"enabled": True, "preset": "punch", "position": "bottom"},
    "hook": {"enabled": True, "text": "Our bridge collapsed", "style": "headline",
             "duration_seconds": 2.0},
    "visuals": [{"suggestion": "suggestion_1", "asset": "visual_asset_1", "mode": "cutaway"}],
    "audio": {"use_music": False, "music_level": "low", "ducking": "medium",
              "transition_sounds": False},
    "explanations": {"layout": "Strong face tracking.", "captions": "Fast delivery.",
                     "hook": "The opening claim.", "visuals": "Shows the joint.",
                     "audio": "Original audio only."},
}  # fmt: skip


def context(**overrides) -> AutoEditContext:
    fields = {
        "clip_duration": 16.44,
        "lines": (TimedLine(0.0, 3.1, "A structure is only as strong as its weakest joint."),),
        "capabilities": Capabilities(
            smart_reframe=True, reframe_confidence="high", word_timing=True, phrase_timing=True,
            text_overlays=True, visuals=True,
        ),  # fmt: skip
        "recipe": current_recipe("punchy").summary(),
        "source_orientation": "landscape",
        "title": "The Weakest Link",
        "candidate_hook": "Our bridge collapsed",
        "broll": (
            BrollOption("suggestion_1", 10.2, 12.7, "joint", "The lesson", ("visual_asset_1",)),
        ),
        "visual_assets": (
            VisualOption("visual_asset_1", "image", "toothpick-bridge.jpg", "Bridge model",
                         ("bridge", "joint"), "landscape"),
        ),  # fmt: skip
        "music": AudioOption(MUSIC_HANDLE, "calm.mp3", 40.0),
        "sound_effects": (AudioOption("sfx_1", "whoosh.wav", 0.8, transition=True),),
        "visual_ids": {"visual_asset_1": "6f1c0a1e-0000-4000-8000-000000000001"},
        "suggestion_ids": {"suggestion_1": "6f1c0a1e-0000-4000-8000-000000000002"},
        "audio_ids": {MUSIC_HANDLE: "6f1c0a1e-0000-4000-8000-000000000003",
                      "sfx_1": "6f1c0a1e-0000-4000-8000-000000000004"},
    }  # fmt: skip
    fields.update(overrides)
    return AutoEditContext(**fields)


def test_a_good_proposal_parses():
    proposal = parse_proposal(GOOD, provider="The model")
    assert isinstance(proposal, AutoEditProposal)
    assert proposal.visuals[0].asset == "visual_asset_1"


def with_change(path: list, value):
    data = json.loads(json.dumps(GOOD))
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return data


@pytest.mark.parametrize(
    "data",
    [
        with_change(["layout", "mode"], "zoom_and_pan"),
        with_change(["captions", "preset"], "rainbow"),
        with_change(["captions", "position"], "left"),
        with_change(["hook", "style"], "comic"),
        with_change(["hook", "text"], "x" * 121),
        with_change(["hook", "duration_seconds"], 30),
        with_change(["audio", "music_level"], "-3 dB"),
        with_change(["audio", "ducking"], "off"),
        with_change(
            ["visuals"],
            [{"suggestion": "suggestion_1", "asset": "visual_asset_1", "mode": "overlay"}],
        ),  # fmt: skip
        with_change(["visuals"], [GOOD["visuals"][0]] * 9),
        with_change(["explanations", "audio"], "y" * 201),
        with_change(["layout", "ffmpeg_filter"], "crop=1:1"),  # unknown keys are refused
        with_change(["audio", "music_gain_db"], 6),
        with_change(["visuals"], [{**GOOD["visuals"][0], "asset_id": "6f1c0a1e"}]),
        {k: v for k, v in GOOD.items() if k != "hook"},
        [],
        "not json",
    ],
)
def test_anything_outside_the_contract_is_refused(data):
    with pytest.raises(PlannerOutputError) as caught:
        parse_proposal(data, provider="The local model")
    message = caught.value.message
    assert message.startswith("The local model returned a plan that does not match")
    # Untrusted values are never echoed into stored or shown errors.
    for leaked in ("zoom_and_pan", "rainbow", "crop=1:1", "comic", "-3 dB"):
        assert leaked not in message
    assert caught.value.code == "planner_output" and caught.value.fallback_ok


def test_the_json_schema_is_inlined_and_closed():
    schema = proposal_json_schema()
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    assert schema["additionalProperties"] is False
    for section in ("layout", "captions", "hook", "audio", "explanations"):
        assert schema["properties"][section]["additionalProperties"] is False
    assert schema["properties"]["visuals"]["items"]["additionalProperties"] is False
    assert set(schema["required"]) == {"layout", "captions", "hook", "visuals", "audio",
                                       "explanations"}  # fmt: skip


def test_the_planner_view_has_handles_and_facts_but_never_ids():
    view = context().planner_view()
    text = json.dumps(view)
    assert not UUID.search(text)
    assert "6f1c0a1e" not in text
    # Categories, never scores: a match without the strong tier is only "possible".
    assert view["broll_suggestions"][0]["matching_assets"] == [
        {"asset": "visual_asset_1", "strength": "possible"}
    ]
    assert "score" not in text and "similarity" not in text
    assert view["available"]["music"] == MUSIC_HANDLE
    assert view["available"]["transition_sounds"] == ["sfx_1"]
    assert view["recipe"]["recipe"] == "punchy"
    assert view["available"]["smart_reframe"] is True
    assert view["transcript"][0]["text"].startswith("A structure")


def test_without_music_or_sounds_the_view_says_so():
    view = context(music=None, sound_effects=()).planner_view()
    assert view["available"]["music"] is None and view["available"]["transition_sounds"] == []


def test_handles_follow_a_fixed_shape():
    assert SUGGESTION_HANDLE.match("suggestion_1") and SUGGESTION_HANDLE.match("suggestion_12")
    assert not SUGGESTION_HANDLE.match("suggestion_0")
    assert not SUGGESTION_HANDLE.match("6f1c0a1e-0000-4000-8000-000000000002")
    assert VISUAL_HANDLE.match("visual_asset_3") and not VISUAL_HANDLE.match("visual_asset_")
    assert not VISUAL_HANDLE.match("../media/secret.jpg")


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1920, 1080, "landscape"),
        (1080, 1920, "portrait"),
        (1000, 1000, "square"),
        (None, None, "landscape"),
    ],  # fmt: skip
)
def test_orientation(width, height, expected):
    assert orientation(width, height) == expected


def test_error_kinds():
    assert PlannerUnavailableError("down").fallback_ok
    assert PlannerTimeoutError("slow").code == "planner_timeout"
    assert not PlannerConfigurationError("bad model").fallback_ok


def test_a_planner_satisfies_the_protocol():
    class Fake:
        name, model = "fake", "fake-1"

        def plan(self, ctx):
            return PlannerResult(parse_proposal(GOOD, provider="Fake"), self.name, self.model)

    assert isinstance(Fake(), AutoEditPlanner)
    assert Fake().plan(context()).proposal.layout.mode == "smart_reframe"
