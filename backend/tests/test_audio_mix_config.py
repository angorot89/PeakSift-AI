"""The audio section of an edit configuration: validation, normalization, snapshot and
fingerprint semantics, and the API's checks of the referenced audio assets."""

import math
import uuid

import pytest

from app.services.audio_mix.config import (
    AUDIO_MIX_VERSION,
    MAX_SFX_CUES,
    AudioMix,
    DuckingStrength,
)
from app.services.clip_edit.config import EditConfig

MUSIC = str(uuid.uuid4())
HIT = str(uuid.uuid4())
WHOOSH = str(uuid.uuid4())


def full(**overrides):
    data = {
        "source_gain_db": -1.5,
        "normalize": True,
        "music": {
            "asset_id": MUSIC,
            "gain_db": -18,
            "source_start_seconds": 12.5,
            "loop": True,
            "fade_in_seconds": 0.5,
            "fade_out_seconds": 1.0,
            "ducking": "medium",
        },
        "sfx": [
            {"asset_id": HIT, "at_seconds": 3.2, "gain_db": -6},
            {"asset_id": WHOOSH, "at_seconds": 0.4, "gain_db": -9},
        ],
    }
    data.update(overrides)
    return data


def edit(audio=None, **kwargs):
    return EditConfig.create(layout="center_crop", captions_enabled=False, audio=audio, **kwargs)


def test_defaults_are_conservative_and_explicit():
    mix = AudioMix.create({"music": {"asset_id": MUSIC}})
    assert mix.source_gain_db == 0 and mix.normalize is True
    music = mix.music
    assert (music.gain_db, music.source_start_seconds, music.loop) == (-16.0, 0.0, True)
    assert (music.fade_in_seconds, music.fade_out_seconds) == (0.5, 1.0)
    assert music.ducking == DuckingStrength.MEDIUM


def test_values_are_rounded_and_cues_sorted_by_time():
    mix = AudioMix.create(
        full(source_gain_db=-1.54, sfx=[{"asset_id": HIT, "at_seconds": 3.214, "gain_db": -6.04}])
    )
    assert mix.source_gain_db == -1.5
    assert mix.sfx[0].at_seconds == 3.21 and mix.sfx[0].gain_db == -6.0
    ordered = AudioMix.create(full())
    assert [cue.at_seconds for cue in ordered.sfx] == [0.4, 3.2]


@pytest.mark.parametrize(
    "bad",
    [
        {"source_gain_db": math.nan},
        {"source_gain_db": math.inf},
        {"source_gain_db": 7},
        {"source_gain_db": -25},
        {"source_gain_db": "0"},
        {"source_gain_db": True},
        {"normalize": "yes"},
        {"music": {"asset_id": MUSIC, "gain_db": 1}},
        {"music": {"asset_id": MUSIC, "gain_db": -41}},
        {"music": {"asset_id": MUSIC, "source_start_seconds": -1}},
        {"music": {"asset_id": MUSIC, "fade_in_seconds": 11}},
        {"music": {"asset_id": MUSIC, "fade_out_seconds": -0.1}},
        {"music": {"asset_id": MUSIC, "loop": 1}},
        {"music": {"asset_id": MUSIC, "ducking": "maximum"}},
        {"music": {"asset_id": "../../etc/passwd"}},
        {"music": {"asset_id": None}},
        {"music": "aevalsrc=sin(t)"},
        {"sfx": [{"asset_id": HIT, "at_seconds": -0.5}]},
        {"sfx": [{"asset_id": HIT, "at_seconds": math.nan}]},
        {"sfx": [{"asset_id": HIT, "at_seconds": 1, "gain_db": 7}]},
        {"sfx": [{"asset_id": HIT}]},
        {"sfx": {"asset_id": HIT}},
        {"sfx": [{"asset_id": HIT, "at_seconds": i} for i in range(MAX_SFX_CUES + 1)]},
    ],
)
def test_invalid_values_are_refused(bad):
    with pytest.raises(ValueError):
        AudioMix.create(full(**bad))


def test_a_section_that_changes_nothing_is_no_section():
    assert AudioMix.create(None) is None
    assert AudioMix.create({"normalize": False}) is None
    assert AudioMix.create({"normalize": False, "sfx": []}) is None
    assert edit({"normalize": False}).fingerprint() == edit().fingerprint()
    # Normalizing alone, or only a different level, is a real (different) render.
    assert AudioMix.create({}) is not None
    assert AudioMix.create({"normalize": False, "source_gain_db": -3}) is not None


def test_the_snapshot_round_trips_and_names_its_version_and_target():
    config = edit(full())
    snapshot = config.snapshot()["audio"]
    assert snapshot["version"] == AUDIO_MIX_VERSION and snapshot["loudness"] == "social_v1"
    assert snapshot["music"]["asset_id"] == MUSIC
    assert [cue["asset_id"] for cue in snapshot["sfx"]] == [WHOOSH, HIT]
    again = EditConfig.from_snapshot(config.snapshot())
    assert again == config and again.fingerprint() == config.fingerprint()
    assert "loudness" not in edit(full(normalize=False)).snapshot()["audio"]
    assert sorted(config.audio.asset_ids) == sorted([MUSIC, HIT, WHOOSH])


def test_unknown_snapshot_versions_are_refused():
    snapshot = edit(full()).snapshot()
    snapshot["audio"]["version"] = "audio_mix_v0"
    with pytest.raises(ValueError):
        EditConfig.from_snapshot(snapshot)


def test_every_audio_choice_changes_the_fingerprint():
    base = edit(full()).fingerprint()
    variants = [
        full(source_gain_db=-2),
        full(normalize=False),
        full(music=None),
        full(music={**full()["music"], "asset_id": str(uuid.uuid4())}),
        full(music={**full()["music"], "gain_db": -20}),
        full(music={**full()["music"], "source_start_seconds": 13}),
        full(music={**full()["music"], "loop": False}),
        full(music={**full()["music"], "fade_in_seconds": 1}),
        full(music={**full()["music"], "fade_out_seconds": 2}),
        full(music={**full()["music"], "ducking": "strong"}),
        full(music={**full()["music"], "ducking": "off"}),
        full(sfx=[]),
        full(sfx=[{"asset_id": HIT, "at_seconds": 3.3, "gain_db": -6}]),
        full(sfx=[{"asset_id": HIT, "at_seconds": 3.2, "gain_db": -7}]),
        full(sfx=[{"asset_id": WHOOSH, "at_seconds": 3.2, "gain_db": -6}]),
    ]
    prints = {edit(v).fingerprint() for v in variants}
    assert base not in prints and len(prints) == len(variants)
    assert edit().fingerprint() != base


def test_equivalent_requests_share_one_fingerprint():
    a = full(sfx=[{"asset_id": HIT, "at_seconds": 3.2}, {"asset_id": WHOOSH, "at_seconds": 0.4}])
    b = full(sfx=[{"asset_id": WHOOSH, "at_seconds": 0.401}, {"asset_id": HIT, "at_seconds": 3.2}])
    for cue in b["sfx"]:
        cue["gain_db"] = -6.0
    a["sfx"][1]["gain_db"] = -6
    assert edit(a).fingerprint() == edit(b).fingerprint()


def test_plain_edits_keep_their_v06_fingerprints():
    # Pinned in earlier milestones: an audio-less configuration must not change at all.
    assert "audio" not in edit().snapshot()
    assert edit().fingerprint().startswith("4c0faecd")
    pinned = EditConfig.create(
        layout="blur_background", captions_enabled=True, caption_style="bold",
        caption_position="bottom",
    )  # fmt: skip
    assert pinned.fingerprint().startswith("a8c24dde")


def test_the_same_effect_may_be_used_several_times():
    mix = AudioMix.create({"sfx": [{"asset_id": HIT, "at_seconds": t} for t in (1, 2, 2)]})
    assert [cue.at_seconds for cue in mix.sfx] == [1, 2, 2]
