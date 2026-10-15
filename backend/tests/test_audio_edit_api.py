"""Edits with an audio section: request validation and the checks of referenced assets
(same project, right kind, start inside the track, effects inside the clip)."""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.models import AudioAsset, Project
from tests.test_clip_edit_api import ready_clip, sign_up

OWNER = "audio-owner@example.com"


def asset(db: Session, project_id: uuid.UUID, kind: str = "music", duration: float = 60.0):
    row = AudioAsset(
        project_id=project_id,
        kind=kind,
        display_name=f"{kind}.mp3",
        storage_key=f"audio/{uuid.uuid4().hex}.mp3",
        content_type="audio/mpeg",
        file_size=10,
        sha256=uuid.uuid4().hex * 2,
        container="mp3",
        codec="mp3",
        duration_seconds=duration,
        sample_rate=44100,
        channels=2,
        waveform_peaks=[1, 2, 3],
    )
    db.add(row)
    db.commit()
    return str(row.id)


@pytest.fixture
def ctx(client, db_session):
    sign_up(client, OWNER)
    ctx = ready_clip(db_session, OWNER)  # a 20 s clip
    ctx["project_id"] = ctx["video"].project_id
    ctx["music"] = asset(db_session, ctx["project_id"])
    ctx["hit"] = asset(db_session, ctx["project_id"], kind="sfx", duration=1.0)
    return ctx


def body(audio):
    return {"layout": "center_crop", "captions_enabled": False, "audio": audio}


def test_assets_must_belong_to_the_clips_project_and_have_the_right_kind(client, db_session, ctx):
    other_project = Project(name="Other", user_id=ctx["video"].project.user_id)
    db_session.add(other_project)
    db_session.commit()
    foreign = asset(db_session, other_project.id)
    for audio in (
        {"music": {"asset_id": foreign}},
        {"music": {"asset_id": str(uuid.uuid4())}},
        {"music": {"asset_id": ctx["hit"]}},  # a sound effect is not music
        {"sfx": [{"asset_id": ctx["music"], "at_seconds": 1}]},  # nor music an effect
        {"sfx": [{"asset_id": str(uuid.uuid4()), "at_seconds": 1}]},
    ):
        response = client.post(ctx["base"], json=body(audio))
        assert response.status_code == 409, (audio, response.text)
        assert foreign not in response.text


def test_music_must_start_inside_the_track_and_effects_inside_the_clip(client, ctx):
    late_start = {"music": {"asset_id": ctx["music"], "source_start_seconds": 60}}
    assert client.post(ctx["base"], json=body(late_start)).status_code == 422
    late_hit = {"sfx": [{"asset_id": ctx["hit"], "at_seconds": 20.5}]}
    assert client.post(ctx["base"], json=body(late_hit)).status_code == 422


@pytest.mark.parametrize(
    "audio",
    [
        {"music": {"asset_id": "x", "gain_db": -10}},
        {"music": {"gain_db": -10}},
        {"music": {"asset_id": str(uuid.uuid4()), "gain_db": "loud"}},
        {"music": {"asset_id": str(uuid.uuid4()), "filter": "volume=10"}},
        {"source_gain_db": 12},
        {"source_gain_db": "nan"},
        {"sfx": [{"asset_id": str(uuid.uuid4()), "at_seconds": i} for i in range(13)]},
        {"mixer": "custom"},
    ],
)
def test_malformed_audio_requests_are_422(client, ctx, audio):
    assert client.post(ctx["base"], json=body(audio)).status_code == 422


def test_valid_audio_edits_are_created_once_and_keep_their_exact_assets(client, ctx, monkeypatch):
    queued = []
    monkeypatch.setattr(
        "app.api.clip_edits.enqueue_clip_edit",
        lambda edit_id, *, task_id: queued.append(edit_id),
    )
    audio = {
        "music": {"asset_id": ctx["music"], "gain_db": -18, "ducking": "strong"},
        "sfx": [{"asset_id": ctx["hit"], "at_seconds": 2}],
    }
    first = client.post(ctx["base"], json=body(audio))
    assert first.status_code == 201, first.text
    snapshot = first.json()["configuration"]["audio"]
    assert (
        snapshot["music"]["asset_id"] == ctx["music"] and snapshot["music"]["ducking"] == "strong"
    )
    assert [cue["asset_id"] for cue in snapshot["sfx"]] == [ctx["hit"]]
    again = client.post(ctx["base"], json=body(audio))
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    plain = client.post(ctx["base"], json=body(None))
    assert plain.status_code == 201 and plain.json()["id"] != first.json()["id"]
    assert "audio" not in plain.json()["configuration"]
    assert len(queued) == 2
