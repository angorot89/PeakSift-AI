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


def test_valid_audio_is_refused_clearly_until_the_mixer_renders_it(client, ctx):
    audio = {
        "music": {"asset_id": ctx["music"]},
        "sfx": [{"asset_id": ctx["hit"], "at_seconds": 2}],
    }
    response = client.post(ctx["base"], json=body(audio))
    assert response.status_code == 409 and "not available" in response.json()["detail"]
