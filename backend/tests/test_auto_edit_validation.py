"""The authoritative plan validator: handles become ids only here, every choice is checked against
what exists and the recipe, optional problems degrade with an honest note, systemic ones are
refused, and explanations are product copy (never a handle, never an id)."""

import json
from dataclasses import replace

import pytest

from app.services.auto_edit.contract import (
    MUSIC_HANDLE,
    AudioOption,
    BrollOption,
    Capabilities,
    TimedLine,
    VisualOption,
    parse_proposal,
)
from app.services.auto_edit.fallback import FallbackAutoEditPlanner
from app.services.auto_edit.recipes import CURRENT_RECIPES, current_recipe
from app.services.auto_edit.validation import (
    PlanRejected,
    clean_text,
    hook_grounded,
    validate_plan,
)
from app.services.clip_edit.config import CaptionPosition
from tests.test_auto_edit_contract import GOOD, UUID, context

ANALYSIS = "0f0e0d0c-0000-4000-8000-00000000000a"
TRACK = "0f0e0d0c-0000-4000-8000-00000000000b"
BRIDGE_ID = "6f1c0a1e-0000-4000-8000-000000000001"
LAUNCH_ID = "6f1c0a1e-0000-4000-8000-000000000005"
SUGGESTION_ID = "6f1c0a1e-0000-4000-8000-000000000002"
LAB_ID = "6f1c0a1e-0000-4000-8000-000000000006"
MUSIC_ID = "6f1c0a1e-0000-4000-8000-000000000003"
SFX_ID = "6f1c0a1e-0000-4000-8000-000000000004"

LINES = (
    TimedLine(0.0, 3.0, "Then she added the second weight and the entire thing folded."),
    TimedLine(3.0, 7.0, "Here is the lesson I learned about every bridge we build."),
    TimedLine(7.0, 12.7, "A structure is only as strong as its weakest joint."),
    TimedLine(12.7, 16.4, "We had reinforced the middle and forgotten the corners."),
)
JOINT = BrollOption("suggestion_1", 10.2, 12.7, "bridge joint", "Shows the weak joint",
                    ("visual_asset_1",), ("visual_asset_1",))  # fmt: skip
LAB = BrollOption("suggestion_2", 3.5, 6.0, "lesson bench", "The lesson", ("visual_asset_2",),
                  ("visual_asset_2",))  # fmt: skip
BRIDGE = VisualOption("visual_asset_1", "image", "toothpick-bridge.jpg", "Bridge model",
                      ("bridge", "joint"), "landscape")  # fmt: skip
LAUNCH = VisualOption("visual_asset_2", "video", "launch.mp4", "", ("lesson",), "landscape", 1.0)


def ctx(recipe="punchy", **overrides):
    fields = {
        "recipe": current_recipe(recipe).summary(),
        "lines": LINES,
        "clip_duration": 16.4,
        "capabilities": Capabilities(
            smart_reframe=True,
            reframe_confidence="high",
            word_timing=True,
            phrase_timing=True,
            text_overlays=True,
            visuals=True,
        ),  # fmt: skip
        "candidate_hook": "Our bridge collapsed",
        "title": "The Weakest Link",
        "broll": (JOINT, LAB),
        "visual_assets": (BRIDGE, LAUNCH),
        "music": AudioOption(MUSIC_HANDLE, "calm.mp3", 8.0),
        "sound_effects": (AudioOption("sfx_1", "whoosh.wav", 0.8, transition=True),),
        "reframe_analysis_id": ANALYSIS,
        "caption_track_id": TRACK,
        "visual_ids": {"visual_asset_1": BRIDGE_ID, "visual_asset_2": LAUNCH_ID},
        "suggestion_ids": {"suggestion_1": SUGGESTION_ID, "suggestion_2": LAB_ID},
        "audio_ids": {MUSIC_HANDLE: MUSIC_ID, "sfx_1": SFX_ID},
        **overrides,
    }
    return context(**fields)


def proposal(**changes):
    data = json.loads(json.dumps(GOOD))
    for path, value in changes.items():
        node = data
        keys = path.split("__")
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = value
    return parse_proposal(data, provider="test")


def validate(recipe="punchy", context=None, **changes):
    return validate_plan(proposal(**changes), context or ctx(recipe), current_recipe(recipe))


# --- a good plan ----------------------------------------------------------------------------------


def test_a_good_proposal_becomes_a_normal_edit_configuration():
    plan = validate()
    snapshot = plan.configuration.snapshot()
    assert snapshot["layout"] == "smart_reframe" and snapshot["reframe"]["analysis_id"] == ANALYSIS
    captions = snapshot["captions"]
    assert (captions["style"], captions["position"], captions["timing"]) == (
        "punch", "bottom", "aligned_word"
    )  # fmt: skip
    assert captions["track_id"] == TRACK
    assert snapshot["hook"] == {"text": "Our bridge collapsed", "style": "headline",
                                "position": "top", "duration": 2.0}  # fmt: skip
    (element,) = snapshot["visuals"]["elements"]
    assert element["asset_id"] == BRIDGE_ID and element["mode"] == "cutaway"
    assert (element["start_seconds"], element["end_seconds"]) == (10.2, 12.7)
    assert element["fit"] == "fill" and element.get("transition", "none") == "none"
    assert snapshot["audio"]["music"] is None and snapshot["audio"]["normalize"] is True
    assert plan.used_suggestion_ids == (SUGGESTION_ID,)
    assert plan.explanations["notes"] == []
    assert plan.configuration.fingerprint()  # a real, hashable edit configuration


@pytest.mark.parametrize(
    "sentence",
    [
        "center_crop for a clean and simple look.",
        "boxed captions for a clear read.",
        "ok",
        "Used the candidate hook to draw attention.",
        "Chosen from the JSON input.",
    ],
)
def test_identifier_like_or_lowercase_explanations_are_rewritten(sentence):
    plan = validate(layout__mode="center_crop", explanations__layout=sentence)
    assert plan.explanations["sections"]["layout"]["reason"] == (
        "Fills the vertical frame from the centre."
    )


def test_explanations_are_product_copy_without_handles_or_ids():
    plan = validate(
        explanations__visuals="Adds visual_asset_1 at suggestion_1.",  # names handles
        explanations__layout="Strong face tracking is available.",
    )
    sections = plan.explanations["sections"]
    assert sections["layout"]["reason"] == "Strong face tracking is available."
    assert "visual_asset" not in sections["visuals"]["reason"]
    assert sections["visuals"]["reason"] == (
        "Supports “bridge joint” with a visual whose name or tags match it."
    )
    assert sections["visuals"]["items"][0]["asset_name"] == "toothpick-bridge.jpg"
    assert not UUID.search(json.dumps(plan.explanations))


# --- layout ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("recipe", "overrides", "expected"),
    [
        ("punchy", {"reframe_analysis_id": None}, "blur_background"),
        ("clean", {"capabilities": Capabilities(True, "mixed", True, True, True, True)},
         "blur_background"),  # Clean needs high confidence
        ("punchy", {"capabilities": Capabilities(False, None, True, True, True, True),
                    "source_orientation": "portrait"}, "center_crop"),
    ],
)  # fmt: skip
def test_smart_reframe_needs_a_usable_analysis(recipe, overrides, expected):
    plan = validate(recipe, ctx(recipe, **overrides))
    assert plan.configuration.layout.value == expected
    assert plan.configuration.reframe_analysis_id is None
    assert any("Smart Reframe was not used" in note for note in plan.explanations["notes"])


def test_other_layouts_are_kept():
    assert validate(layout__mode="center_crop").configuration.layout.value == "center_crop"


# --- captions -------------------------------------------------------------------------------------


def test_a_preset_outside_the_recipe_becomes_the_recipe_default():
    plan = validate("clean")  # GOOD asks for Punch; Clean offers Focus / Minimal / Boxed
    assert plan.configuration.caption_style.value == "focus"
    assert any("caption style was changed" in note for note in plan.explanations["notes"])


def test_a_position_outside_the_recipe_becomes_the_default():
    assert validate("clean", captions__position="top").configuration.caption_position.value == (
        "bottom"
    )


def test_without_word_timing_captions_use_phrases():
    plan = validate(context=ctx(caption_track_id=None))
    assert plan.configuration.caption_timing.value == "phrase_fallback"
    assert plan.configuration.caption_track_id is None


def test_without_any_timing_captions_are_left_out():
    caps = Capabilities(True, "high", False, False, True, True)
    plan = validate(context=ctx(capabilities=caps, caption_track_id=None))
    assert not plan.configuration.captions_enabled
    assert any("no transcript timing" in note for note in plan.explanations["notes"])


def test_captions_off_stays_off():
    assert not validate(captions__enabled=False).configuration.captions_enabled


# --- hook -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "NASA destroyed our bridge",  # a name nobody mentioned
        "We lost 500 dollars on this bridge",  # a number nobody said
        "Billionaires hate this one weird investing trick",  # not what the clip says
        "x" * 80,  # too long for the renderer
        "",
    ],
)
def test_an_ungrounded_or_unusable_hook_falls_back_to_the_candidates_own(text):
    plan = validate(hook__text=text)
    assert plan.configuration.hook.text == "Our bridge collapsed"
    assert any("clip's own hook was used" in note for note in plan.explanations["notes"])


def test_without_a_usable_candidate_hook_there_is_no_hook():
    plan = validate(context=ctx(candidate_hook=None), hook__text="NASA destroyed our bridge")
    assert plan.configuration.hook is None
    assert any("no hook was added" in note for note in plan.explanations["notes"])


def test_a_grounded_hook_from_the_speakers_words_is_kept():
    plan = validate(hook__text="Only as strong as its weakest joint")
    assert plan.configuration.hook.text == "Only as strong as its weakest joint"


def test_a_hook_repeating_the_first_caption_is_replaced():
    plan = validate(hook__text="Then she added the second weight and the entire thing folded.")
    assert plan.configuration.hook.text == "Our bridge collapsed"


def test_unsafe_characters_never_reach_the_hook():
    plan = validate(hook__text="Our\u0000 bridge‮​ collapsed ")
    assert plan.configuration.hook.text == "Our bridge collapsed"


def test_markup_stays_inert_text():
    plan = validate(hook__text="{\\i}<b>Our bridge collapsed</b>")
    # Kept as literal text; the caption renderer escapes it (no override tag can form).
    assert plan.configuration.hook.text == "{\\i}<b>Our bridge collapsed</b>"


def test_markup_with_unsaid_numbers_is_not_grounded():
    plan = validate(hook__text="{\\pos(1,1)} Our bridge collapsed")
    assert plan.configuration.hook.text == "Our bridge collapsed"


def test_hook_style_and_length_follow_the_recipe():
    plan = validate("minimal", hook__style="boxed", hook__duration_seconds=9)
    hook = plan.configuration.hook
    assert hook.style.value == "minimal" and hook.duration == 1.5


def test_the_hook_never_shares_the_captions_position():
    recipe = replace(current_recipe("punchy"), caption_positions=(CaptionPosition.TOP,))
    plan = validate_plan(proposal(captions__position="top"), ctx(), recipe)
    assert plan.configuration.caption_position.value == "top"
    assert plan.configuration.hook.position.value == "center"


def test_no_hook_when_the_server_cannot_draw_text():
    caps = Capabilities(True, "high", True, True, False, True)
    plan = validate(context=ctx(capabilities=caps))
    assert plan.configuration.hook is None and not plan.configuration.captions_enabled


def test_hook_grounding_rules():
    sources = "We had spent three weeks gluing toothpicks for 20 kilograms. Our bridge collapsed."
    assert hook_grounded("Three weeks of toothpicks", sources)
    assert (
        hook_grounded("It held 20 kilograms", sources) is False
    )  # half of its words were never said
    assert hook_grounded("Gluing toothpicks for 20 kilograms", sources)
    assert not hook_grounded("Gluing toothpicks for 30 kilograms", sources)
    assert not hook_grounded("The Eiffel Tower collapsed", sources)


# --- visuals --------------------------------------------------------------------------------------


def test_an_invented_suggestion_or_asset_handle_is_ignored_and_counted():
    plan = validate(visuals=[
        {"suggestion": "suggestion_9", "asset": "visual_asset_1", "mode": "cutaway"},
        {"suggestion": "suggestion_1", "asset": "visual_asset_7", "mode": "cutaway"},
    ])  # fmt: skip
    assert plan.configuration.visuals is None
    assert plan.report.unknown_handles == 2 and plan.used_suggestion_ids == ()
    assert any("unknown B-roll suggestion" in note for note in plan.explanations["notes"])


def test_a_real_asset_that_does_not_match_the_suggestion_is_refused():
    plan = validate(visuals=[{"suggestion": "suggestion_1", "asset": "visual_asset_2",
                              "mode": "cutaway"}])  # fmt: skip
    assert plan.configuration.visuals is None and plan.report.unmatched_assets == 1
    assert any("no project asset matched" in note for note in plan.explanations["notes"])


def test_a_video_too_short_for_its_moment_is_left_out():
    plan = validate(visuals=[{"suggestion": "suggestion_2", "asset": "visual_asset_2",
                              "mode": "cutaway"}])  # fmt: skip
    assert plan.configuration.visuals is None
    assert any("cannot fill" in note for note in plan.explanations["notes"])


def test_a_mode_outside_the_recipe_becomes_a_cutaway():
    plan = validate("story", visuals=[{"suggestion": "suggestion_1", "asset": "visual_asset_1",
                                       "mode": "pip"}])  # fmt: skip
    (element,) = plan.configuration.visuals.elements
    assert element.mode.value == "cutaway" and element.transition.value == "fade"


def test_pip_sits_in_a_top_corner():
    plan = validate(visuals=[{"suggestion": "suggestion_1", "asset": "visual_asset_1",
                              "mode": "pip"}])  # fmt: skip
    (element,) = plan.configuration.visuals.elements
    assert element.position.value == "top_right"


def test_pacing_limits_follow_the_recipe():
    long_video = replace(LAUNCH, duration=10.0)
    lab = replace(LAB, matches=("visual_asset_2",))
    context = ctx("minimal", visual_assets=(BRIDGE, long_video), broll=(JOINT, lab))
    both = [
        {"suggestion": "suggestion_2", "asset": "visual_asset_2", "mode": "cutaway"},
        {"suggestion": "suggestion_1", "asset": "visual_asset_1", "mode": "cutaway"},
    ]
    plan = validate("minimal", context=context, visuals=both)
    assert len(plan.configuration.visuals.elements) == 1  # Minimal: at most one visual
    assert any("pacing" in note for note in plan.explanations["notes"])


def test_the_same_suggestion_is_used_once():
    choice = {"suggestion": "suggestion_1", "asset": "visual_asset_1", "mode": "cutaway"}
    plan = validate(visuals=[choice, choice])
    assert len(plan.configuration.visuals.elements) == 1


def test_no_visuals_when_the_server_cannot_draw_them():
    caps = Capabilities(True, "high", True, True, True, False)
    assert validate(context=ctx(capabilities=caps)).configuration.visuals is None


# --- audio ----------------------------------------------------------------------------------------


def test_the_audio_choice_keeps_its_units():
    plan = validate(audio__use_music=True, audio__music_level="low", audio__transition_sounds=True)
    choice = plan.explanations["sections"]["audio"]["choice"]
    assert (
        choice == "Original audio, normalized, music -20 dB with medium ducking, 1 transition sound"
    )


def test_an_audio_sentence_about_music_needs_music_in_the_mix():
    plan = validate(
        context=ctx(music=None),
        audio__use_music=False,
        explanations__audio="Kept music levels quiet and ducking strong for the voice.",
    )
    assert plan.explanations["sections"]["audio"]["reason"] == (
        "The voice comes first: the original audio, evenly loud."
    )
    kept = validate(audio__use_music=False, explanations__audio="The voice stays clear and even.")
    assert kept.explanations["sections"]["audio"]["reason"] == "The voice stays clear and even."


def test_music_only_from_the_creators_track_at_recipe_levels():
    plan = validate(audio__use_music=True, audio__music_level="medium", audio__ducking="strong")
    music = plan.configuration.audio.music
    assert music.asset_id == MUSIC_ID and music.gain_db == -16.0
    assert music.ducking.value == "strong" and music.loop  # 8 s track, 16.4 s clip
    plan = validate("minimal", audio__use_music=True, audio__music_level="medium")
    assert plan.configuration.audio.music.gain_db == -24.0  # Minimal: quiet only


def test_no_music_without_a_chosen_track():
    plan = validate(context=ctx(music=None), audio__use_music=True)
    assert plan.configuration.audio.music is None
    assert any("no track was chosen" in note for note in plan.explanations["notes"])


def test_transition_sounds_only_at_cutaways_from_a_matching_effect():
    plan = validate(audio__transition_sounds=True)
    (cue,) = plan.configuration.audio.sfx
    assert cue.asset_id == SFX_ID and cue.at_seconds == 10.15 and cue.gain_db == -10.0
    assert validate("clean", audio__transition_sounds=True).configuration.audio.sfx == ()
    plan = validate(context=ctx(sound_effects=()), audio__transition_sounds=True)
    assert plan.configuration.audio.sfx == ()
    assert any("no matching sound effect" in note for note in plan.explanations["notes"])
    assert validate(visuals=[], audio__transition_sounds=True).configuration.audio.sfx == ()


# --- systemic failure and invariants ------------------------------------------------------------


def test_a_proposal_that_forms_no_valid_configuration_is_rejected():
    with pytest.raises(PlanRejected) as caught:
        validate(context=ctx(caption_track_id="not-a-track-id"))
    assert caught.value.code == "plan_invalid" and "not-a-track-id" not in caught.value.message


@pytest.mark.parametrize("recipe", list(CURRENT_RECIPES))
@pytest.mark.parametrize("variant", ["full", "empty", "portrait", "no_timing"])
def test_the_fallback_plan_always_validates(recipe, variant):
    overrides = {
        "full": {},
        "empty": {"broll": (), "visual_assets": (), "music": None, "sound_effects": (),
                  "lines": (), "candidate_hook": None,
                  "capabilities": Capabilities(False, None, False, False, True, True),
                  "reframe_analysis_id": None, "caption_track_id": None},
        "portrait": {"source_orientation": "portrait", "reframe_analysis_id": None,
                     "capabilities": Capabilities(False, None, True, True, True, True)},
        "no_timing": {"caption_track_id": None,
                      "capabilities": Capabilities(True, "high", False, False, True, True)},
    }[variant]  # fmt: skip
    context = ctx(recipe.value, **overrides)
    result = FallbackAutoEditPlanner().plan(context)
    plan = validate_plan(result.proposal, context, current_recipe(recipe))
    assert plan.report.unknown_handles == 0 and plan.report.unmatched_assets == 0
    assert plan.configuration.fingerprint()


def test_clean_text_removes_control_and_format_characters():
    assert clean_text("a\u0000b​c‮d e\tf", 50) == "a b c d e f"
    assert clean_text("x" * 300, 200) == "x" * 200
