"""Backups: pg_dump + manifest + checksummed media, verified, and restored into throwaway
places to prove they are complete. Runs the real pg_dump/pg_restore against the test
server (the data is committed, because the dump runs in another process, and removed)."""

import io
import json
import os
import shutil
import stat
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

from app.cli import backup as cli
from app.core.config import get_settings
from app.models import AudioAsset, AudioAssetKind, Project, User, Video
from app.services import backup
from app.services.storage import LocalStorageProvider
from tests.storage_backends import provider

pytestmark = pytest.mark.skipif(
    not (
        shutil.which(get_settings().pg_dump_path) and shutil.which(get_settings().pg_restore_path)
    ),
    reason="pg_dump/pg_restore are not installed",
)
VIDEO = os.urandom(5000)
AUDIO = b"ID3" + os.urandom(1500)


@pytest.fixture
def media(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "media")


@pytest.fixture
def library(media):
    """Committed rows (a user, project, video and music) whose bytes live in ``media``."""
    engine = create_engine(get_settings().database_url)
    with Session(engine) as db:
        user = User(email=f"backup-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
        project = Project(name="Backed up", owner=user)
        video_key, audio_key = media.generate_key("mp4"), media.generate_key("mp3", "audio")
        media.save(io.BytesIO(VIDEO), video_key)
        media.save(io.BytesIO(AUDIO), audio_key)
        db.add_all([user, project,
                    Video(project=project, original_filename="v.mp4", storage_key=video_key,
                          content_type="video/mp4", file_size=len(VIDEO)),
                    AudioAsset(project=project, kind=AudioAssetKind.MUSIC, display_name="m.mp3",
                               storage_key=audio_key, content_type="audio/mpeg",
                               file_size=len(AUDIO), sha256="b" * 64, container="mp3",
                               codec="mp3", duration_seconds=2.0, sample_rate=44100,
                               channels=2, waveform_peaks=[1])])  # fmt: skip
        db.commit()
        user_id = user.id
        keys = {"video": video_key, "audio": audio_key}
    session = Session(engine)
    try:
        yield {"db": session, "keys": keys}
    finally:
        session.close()
        with Session(engine) as db:
            db.execute(delete(User).where(User.id == user_id))  # cascades to everything
            db.commit()
        engine.dispose()


def restore_databases() -> list[str]:
    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as connection:
            return list(connection.execute(text(
                "SELECT datname FROM pg_database WHERE datname LIKE 'peaksift_restore_%'"
            )).scalars())  # fmt: skip
    finally:
        engine.dispose()


def make(tmp_path, library, media, **options) -> Path:
    target = tmp_path / "backup-1"
    backup.create(target, get_settings(), library["db"], media, app_version="1.0.0", **options)
    return target


def test_a_backup_records_what_it_holds(tmp_path, library, media):
    target = make(tmp_path, library, media, copy_media=True)

    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["format"] == "peaksift-backup/1" and manifest["app_version"] == "1.0.0"
    assert manifest["alembic_revision"]
    assert manifest["database"]["sha256"] == backup.sha256_file(target / "database.dump")
    assert manifest["tables"]["users"] >= 1 and manifest["tables"]["audio_assets"] >= 1
    objects = {o["key"]: o for o in manifest["media"]["objects"]}
    assert objects[library["keys"]["video"]]["bytes"] == len(VIDEO)
    assert (target / "media" / library["keys"]["audio"]).read_bytes() == AUDIO
    assert manifest["media"]["copied"] and manifest["media"]["missing_at_backup"] == []
    assert stat.S_IMODE(target.stat().st_mode) == 0o700  # user data: owner only
    assert "password" not in json.dumps(manifest).lower()


def test_a_backup_never_overwrites(tmp_path, library, media):
    target = make(tmp_path, library, media)
    with pytest.raises(backup.BackupError):
        backup.create(target, get_settings(), library["db"], media)


def test_verify_passes_then_catches_tampering(tmp_path, library, media):
    target = make(tmp_path, library, media, copy_media=True)
    assert backup.verify(target, get_settings()).ok

    copy = target / "media" / library["keys"]["video"]
    data = copy.read_bytes()
    copy.write_bytes(bytes([data[0] ^ 0xFF]) + data[1:])  # always a change (the bytes are random)
    report = backup.verify(target, get_settings())
    assert (
        not report.ok
        and ("media copies match their checksums", False, "1 mismatched") in report.checks
    )

    dump = target / "database.dump"
    dump.write_bytes(dump.read_bytes()[:-10])
    failing = {name for name, ok, _ in backup.verify(target, get_settings()).checks if not ok}
    assert {"database dump size", "database dump checksum"} <= failing


def test_missing_media_at_backup_time_is_reported(tmp_path, library, media):
    media.delete(library["keys"]["audio"])
    target = make(tmp_path, library, media)
    manifest = backup.load_manifest(target)
    assert manifest["media"]["missing_at_backup"] == [library["keys"]["audio"]]
    assert not backup.verify(target, get_settings()).ok


def test_restore_test_proves_the_backup_and_cleans_up(tmp_path, library, media):
    target = make(tmp_path, library, media, copy_media=True)
    before = restore_databases()

    report = backup.restore_test(target, get_settings())

    assert report.ok, report.checks
    names = [name for name, _, _ in report.checks]
    assert "database restored into a temporary database" in names
    assert "every table has its row count" in names
    assert "restored rows reference exactly the backed-up media" in names
    assert "restored media matches its checksums" in names
    assert restore_databases() == before  # the temporary database was dropped


def test_restore_test_into_a_temporary_bucket(tmp_path, library, media, monkeypatch):
    target = make(tmp_path, library, media, copy_media=True)
    with provider("s3-moto", tmp_path, monkeypatch) as s3:
        client = s3._client
        buckets_before = {b["Name"] for b in client.list_buckets()["Buckets"]}

        report = backup.restore_test(target, get_settings(),
                                     lambda: backup.temporary_bucket(client))  # fmt: skip

        assert report.ok, report.checks
        assert ("media restored into temporary s3 storage", True, "2 of 2") in report.checks
        assert {b["Name"] for b in client.list_buckets()["Buckets"]} == buckets_before


def test_a_corrupt_dump_fails_the_restore_test(tmp_path, library, media):
    target = make(tmp_path, library, media)
    manifest = backup.load_manifest(target)
    dump = target / "database.dump"
    dump.write_bytes(b"not a dump")
    manifest["database"].update(bytes=dump.stat().st_size, sha256=backup.sha256_file(dump))
    (target / "manifest.json").write_text(json.dumps(manifest))
    report = backup.restore_test(target, get_settings())
    assert (
        not report.ok
        and ("dump readable by pg_restore", False, "pg_restore --list failed (exit 1)")
        in report.checks
    )


def test_backups_upload_to_secondary_storage(tmp_path, library, media, monkeypatch):
    target = make(tmp_path, library, media, copy_media=True)
    with provider("s3-moto", tmp_path, monkeypatch) as secondary:
        prefix = backup.upload(target, secondary)
        keys = {item.key for item in secondary.list_objects("backups")}
    assert prefix == "backups/backup-1"
    assert {f"{prefix}/manifest.json", f"{prefix}/database.dump",
            f"{prefix}/media/{library['keys']['video']}"} <= keys  # fmt: skip


def test_the_database_password_never_reaches_the_command_line(monkeypatch):
    env, name = backup._libpq("postgresql+psycopg://app:s3cr3t-pw@db.internal:5433/peaksift")
    assert (env["PGPASSWORD"], env["PGHOST"], env["PGPORT"], env["PGUSER"], name) == (
        "s3cr3t-pw", "db.internal", "5433", "app", "peaksift")  # fmt: skip
    seen = []
    monkeypatch.setattr(backup.subprocess, "run", lambda command, **kw: seen.append(command)
                        or type("R", (), {"returncode": 1})())  # fmt: skip
    with pytest.raises(backup.BackupError) as excinfo:
        backup._run(["pg_dump", "--file", "x"], env, "pg_dump")
    assert "s3cr3t" not in " ".join(seen[0]) and "s3cr3t" not in str(excinfo.value)


def test_the_cli_creates_verifies_and_restore_tests(tmp_path, library, monkeypatch, capsys):
    monkeypatch.setattr(cli, "media_storage", lambda settings: LocalStorageProvider(
        Path(library["keys"] and tmp_path / "media")))  # fmt: skip
    target = tmp_path / "cli-backup"
    assert cli.main(["create", str(target), "--copy-media"]) == 0
    assert cli.main(["verify", str(target)]) == 0
    assert cli.main(["restore-test", str(target)]) == 0
    out = capsys.readouterr().out
    assert "backup written" in out and out.count("OK") >= 3
    with pytest.raises(SystemExit):
        cli.main(["create", str(tmp_path / "other"), "--upload"])  # no backup bucket configured


def test_a_restore_test_still_runs_when_media_was_missing(tmp_path, library, media):
    media.delete(library["keys"]["audio"])
    target = make(tmp_path, library, media, copy_media=True)
    report = backup.restore_test(target, get_settings())
    results = {name: ok for name, ok, _ in report.checks}
    assert results["every referenced media object existed at backup time"] is False
    assert results["database restored into a temporary database"] is True
    assert results["every table has its row count"] is True
    assert not report.ok  # the missing object keeps the overall verdict honest


def test_pg_dump_never_waits_forever_on_a_lock(tmp_path, library, media, monkeypatch):
    seen = []
    real = backup._run

    def spy(command, env, what):
        seen.append(command)
        return real(command, env, what)

    monkeypatch.setattr(backup, "_run", spy)
    make(tmp_path, library, media)
    assert "--lock-wait-timeout=60s" in seen[0]


def test_a_locked_table_fails_the_backup_quickly(tmp_path, library, media):
    import time

    settings = get_settings().model_copy(update={"backup_lock_wait_timeout_seconds": 1})
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as holder:
            holder.execute(text("BEGIN"))
            holder.execute(text("LOCK TABLE users IN ACCESS EXCLUSIVE MODE"))
            started = time.monotonic()
            with pytest.raises(backup.BackupError) as excinfo:
                backup.create(tmp_path / "locked", settings, library["db"], media)
            assert time.monotonic() - started < 30
            assert str(excinfo.value) == "pg_dump failed (exit 1)"
            holder.execute(text("ROLLBACK"))
    finally:
        engine.dispose()


def test_a_key_limited_to_its_bucket_restores_media_to_a_directory(monkeypatch, capsys):
    class LimitedClient:
        def create_bucket(self, **kwargs):
            raise PermissionError("AccessDenied")

    class Provider:
        _client = LimitedClient()

    monkeypatch.setattr(cli.S3StorageProvider, "from_settings", lambda settings: Provider())
    settings = get_settings().model_copy(update={"storage_backend": "s3"})
    with cli._media_target(settings)() as target:
        assert isinstance(target, LocalStorageProvider) and target.root.is_dir()
        root = target.root
    assert not root.exists()  # removed afterwards
    assert "temporary directory" in capsys.readouterr().out
