"""Copying media between backends: copy-first, resumable, never destructive, verifiable."""

import io
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.cli import media as cli
from app.models import AudioAsset, AudioAssetKind, Project, User, Video
from app.services.media_migration import media_objects, migrate, verify
from app.services.storage import LocalStorageProvider
from tests.storage_backends import provider

CONTENT = {"video": bytes(range(256)) * 9, "audio": b"ID3" + bytes(1500)}


@pytest.fixture
def local(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "media")


@pytest.fixture
def s3(tmp_path, monkeypatch):
    with provider("s3-moto", tmp_path, monkeypatch) as bucket:
        yield bucket


@pytest.fixture
def library(db_session: Session, local: LocalStorageProvider) -> dict[str, str]:
    """Two videos and an audio asset in the database, with their bytes in ``local``."""
    user = User(email=f"m-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    project = Project(name="Library", owner=user)
    keys = {}
    rows = []
    for name in ("first", "second"):
        key = local.generate_key("mp4")
        local.save(io.BytesIO(CONTENT["video"]), key)
        rows.append(Video(project=project, original_filename=f"{name}.mp4", storage_key=key,
                          content_type="video/mp4", file_size=len(CONTENT["video"])))  # fmt: skip
        keys[name] = key
    audio = local.generate_key("mp3", category="audio")
    local.save(io.BytesIO(CONTENT["audio"]), audio)
    rows.append(
        AudioAsset(
            project=project, kind=AudioAssetKind.MUSIC, display_name="m.mp3", storage_key=audio,
            content_type="audio/mpeg", file_size=len(CONTENT["audio"]), sha256="a" * 64,
            container="mp3", codec="mp3", duration_seconds=3.0, sample_rate=44100, channels=2,
            waveform_peaks=[0, 50, 100],
        )
    )  # fmt: skip
    keys["audio"] = audio
    db_session.add_all([user, project, *rows])
    db_session.commit()
    return keys


def files(storage: LocalStorageProvider) -> dict[str, bytes]:
    return {
        p.relative_to(storage.root).as_posix(): p.read_bytes()
        for p in storage.root.rglob("*")
        if p.is_file()
    }


def test_the_database_lists_every_object_that_must_exist(db_session, library):
    found = {(item.kind, item.key) for item in media_objects(db_session)}
    assert found == {
        ("video", library["first"]),
        ("video", library["second"]),
        ("audio", library["audio"]),
    }


def test_a_dry_run_reports_and_writes_nothing(db_session, library, local, s3):
    report = migrate(db_session, local, s3, dry_run=True)

    assert sorted(report.copied) == sorted(library.values()) and report.ok
    assert report.bytes_copied == 2 * len(CONTENT["video"]) + len(CONTENT["audio"])
    assert not any(s3.exists(key) for key in library.values())


def test_migration_copies_everything_and_is_resumable(db_session, library, local, s3):
    before = files(local)

    first = migrate(db_session, local, s3)
    assert sorted(first.copied) == sorted(library.values()) and first.ok
    for name, key in library.items():
        expected = CONTENT["audio"] if name == "audio" else CONTENT["video"]
        assert b"".join(s3.iter_range(key, 0, len(expected) - 1)) == expected

    again = migrate(db_session, local, s3)  # interrupted or repeated runs pick up where they were
    assert again.copied == [] and sorted(again.present) == sorted(library.values())
    assert files(local) == before  # the source is never modified or deleted


def test_a_partially_migrated_library_finishes_the_rest(db_session, library, local, s3):
    s3.put_file(local.path_for(library["first"]), library["first"])

    report = migrate(db_session, local, s3)

    assert report.present == [library["first"]]
    assert sorted(report.copied) == sorted([library["second"], library["audio"]])


def test_missing_sources_and_conflicts_are_reported_never_papered_over(
    db_session, library, local, s3
):
    local.delete(library["second"])
    s3.save(io.BytesIO(b"something else"), library["audio"])  # a different object, same key

    report = migrate(db_session, local, s3)

    assert report.copied == [library["first"]]
    assert report.missing_source == [library["second"]]
    assert report.conflicts == [library["audio"]] and not report.ok
    assert b"".join(s3.iter_range(library["audio"], 0, 13)) == b"something else"  # untouched


def test_verify_confirms_a_complete_copy(db_session, library, local, s3):
    migrate(db_session, local, s3)

    assert verify(db_session, local, s3).ok
    assert verify(db_session, local, s3, checksum=True).ok


def test_verify_finds_absent_resized_and_altered_objects(db_session, library, local, s3):
    migrate(db_session, local, s3)
    s3.delete(library["first"])
    s3.delete(library["second"])
    s3.save(io.BytesIO(CONTENT["video"][:-1]), library["second"])  # wrong size
    s3.delete(library["audio"])
    s3.save(io.BytesIO(bytes(len(CONTENT["audio"]))), library["audio"])  # same size, new bytes

    sized = verify(db_session, local, s3)
    assert sized.failed == [library["first"]] and sized.mismatched == [library["second"]]
    assert library["audio"] in sized.present  # sizes alone cannot see it…

    summed = verify(db_session, local, s3, checksum=True)
    assert sorted(summed.mismatched) == sorted([library["second"], library["audio"]])  # …SHA can


def test_the_cli_migrates_verifies_and_exits_non_zero_on_problems(
    db_session, library, local, s3, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "provider", lambda name, settings: local if name == "local" else s3)
    monkeypatch.setattr("app.core.database.SessionLocal", lambda: _Borrowed(db_session))

    assert cli.main(["migrate", "--from", "local", "--to", "s3", "--dry-run"]) == 0
    assert not s3.exists(library["first"])
    assert cli.main(["migrate", "--from", "local", "--to", "s3"]) == 0
    assert cli.main(["verify", "--from", "local", "--to", "s3", "--checksum"]) == 0
    s3.delete(library["audio"])
    assert cli.main(["verify", "--from", "local", "--to", "s3"]) == 1

    out = capsys.readouterr().out
    assert "3 copied" in out and f"absent  audio  {library['audio']}" in out
    with pytest.raises(SystemExit):
        cli.main(["migrate", "--from", "s3", "--to", "s3"])


class _Borrowed:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


def test_the_cli_refuses_an_unconfigured_bucket_without_echoing_values():
    from app.core.config import get_settings

    settings = get_settings().model_copy(
        update={"s3_bucket": "Not_A_Bucket", "s3_secret_access_key": None,
                "s3_access_key_id": "visible-key-id"}
    )  # fmt: skip
    with pytest.raises(SystemExit) as excinfo:
        cli.provider("s3", settings)
    message = str(excinfo.value)
    assert "S3_BUCKET" in message and "set together" in message
    assert "Not_A_Bucket" not in message and "visible-key-id" not in message
