"""Backups that can be proven restorable.

A backup is a directory:

    database.dump    pg_dump custom format (no owners or privileges)
    manifest.json    what the backup contains and how to check it
    media/<key>      optional: a copy of every database-referenced media object

The manifest records the format, application version, Alembic revision, the dump's size and
SHA-256, the row count of every table, and the media inventory (keys and sizes; SHA-256 of
each copied object). :func:`verify` recomputes all of it and asks ``pg_restore`` to read the
archive; :func:`restore_test` restores into a *temporary* database (and a temporary bucket or
directory for media), checks revision, row counts, media keys and checksums, then drops
everything it created. Database passwords reach ``pg_dump``/``pg_restore`` only through the
environment, never their arguments; nothing secret is written to the manifest.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.media_migration import MediaObject, media_objects, migrate
from app.services.storage import LocalStorageProvider, StorageProvider

FORMAT = "peaksift-backup/1"
DUMP = "database.dump"
MANIFEST = "manifest.json"
MEDIA = "media"
TIMEOUT_SECONDS = 6 * 3600
DUMP_CHECKS = frozenset(
    {"database dump present", "database dump size", "database dump checksum",
     "dump readable by pg_restore"}
)  # fmt: skip


class BackupError(Exception):
    """A backup could not be made, read or restored (the message is safe to print)."""


@dataclass
class Report:
    ok: bool = True
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))
        self.ok = self.ok and ok


# --- PostgreSQL tools ------------------------------------------------------------------------


def _libpq(database_url: str) -> tuple[dict[str, str], str]:
    """Environment for libpq tools and the database name; the password stays in the env."""
    url = make_url(database_url)
    env = {**os.environ}
    for var, value in (("PGHOST", url.host), ("PGPORT", url.port), ("PGUSER", url.username),
                       ("PGPASSWORD", url.password), ("PGDATABASE", url.database)):  # fmt: skip
        if value is not None:
            env[var] = str(value)
        else:
            env.pop(var, None)
    return env, url.database or ""


def _run(command: list[str], env: dict[str, str], what: str) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command, env=env, capture_output=True, timeout=TIMEOUT_SECONDS, check=False
        )
    except FileNotFoundError:
        raise BackupError(f"{what}: the PostgreSQL tool is not installed") from None
    except subprocess.TimeoutExpired:
        raise BackupError(f"{what}: timed out") from None
    if result.returncode != 0:
        # stderr can name hosts or users; only the exit code is reported.
        raise BackupError(f"{what} failed (exit {result.returncode})")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _table_counts(engine) -> dict[str, int]:
    with engine.connect() as connection:
        tables = sorted(inspect(connection).get_table_names())
        return {
            table: connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
            for table in tables
        }


def _revision(engine) -> str | None:
    with engine.connect() as connection:
        try:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:  # noqa: BLE001 — a database without migrations
            return None


# --- create ------------------------------------------------------------------------------------


def create(
    destination: Path,
    settings: Settings,
    db: Session,
    storage: StorageProvider,
    *,
    copy_media: bool = False,
    app_version: str = "",
) -> dict:
    """Write a backup into ``destination`` (which must not exist yet); return the manifest."""
    destination = Path(destination)
    if destination.exists():
        raise BackupError("The backup destination already exists")
    destination.mkdir(parents=True)
    os.chmod(destination, 0o700)  # the dump holds user data
    env, _ = _libpq(settings.database_url)
    dump = destination / DUMP
    _run([settings.pg_dump_path, "--format=custom", "--no-owner", "--no-privileges",
          f"--lock-wait-timeout={settings.backup_lock_wait_timeout_seconds}s",
          "--file", str(dump)], env, "pg_dump")  # fmt: skip

    engine = create_engine(settings.database_url)
    try:
        counts, revision = _table_counts(engine), _revision(engine)
    finally:
        engine.dispose()

    inventory = [{"kind": item.kind, "key": item.key} for item in media_objects(db)]
    sizes: dict[str, int | None] = {}
    for item in inventory:
        try:
            sizes[item["key"]] = storage.size(item["key"])
        except Exception:  # noqa: BLE001 — recorded as missing, reported by verify
            sizes[item["key"]] = None
    copied = False
    if copy_media:
        report = migrate(db, storage, LocalStorageProvider(destination / MEDIA))
        if report.failed or report.conflicts:
            raise BackupError("Some media objects could not be copied")
        copied = True
    objects = []
    for item in inventory:
        entry = {**item, "bytes": sizes[item["key"]]}
        local = destination / MEDIA / item["key"]
        if copied and local.is_file():
            entry["sha256"] = sha256_file(local)
        objects.append(entry)

    manifest = {
        "format": FORMAT,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "app_version": app_version,
        "alembic_revision": revision,
        "database": {"file": DUMP, "bytes": dump.stat().st_size, "sha256": sha256_file(dump)},
        "tables": counts,
        "media": {
            "backend": storage.backend,
            "copied": copied,
            "count": len(objects),
            "bytes": sum(o["bytes"] or 0 for o in objects),
            "missing_at_backup": sorted(o["key"] for o in objects if o["bytes"] is None),
            "objects": objects,
        },
    }
    (destination / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def upload(source: Path, secondary: StorageProvider) -> str:
    """Copy a backup directory into secondary storage under ``backups/<name>/``."""
    source = Path(source)
    name = "".join(ch for ch in source.name if ch.isalnum() or ch in "-_") or "backup"
    prefix = f"backups/{name}"
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        key = f"{prefix}/{path.relative_to(source).as_posix()}"
        if not secondary.exists(key):
            secondary.put_file(path, key)
    return prefix


# --- verify -------------------------------------------------------------------------------------


def load_manifest(source: Path) -> dict:
    try:
        manifest = json.loads((Path(source) / MANIFEST).read_text())
    except (OSError, ValueError):
        raise BackupError("The backup has no readable manifest") from None
    if manifest.get("format") != FORMAT:
        raise BackupError("Unknown backup format")
    return manifest


def verify(source: Path, settings: Settings) -> Report:
    source = Path(source)
    report = Report()
    manifest = load_manifest(source)
    dump = source / DUMP
    report.check("database dump present", dump.is_file())
    if dump.is_file():
        report.check("database dump size", dump.stat().st_size == manifest["database"]["bytes"])
        report.check("database dump checksum", sha256_file(dump) == manifest["database"]["sha256"])
        try:
            env, _ = _libpq(settings.database_url)
            _run([settings.pg_restore_path, "--list", str(dump)], env, "pg_restore --list")
            report.check("dump readable by pg_restore", True)
        except BackupError as error:
            report.check("dump readable by pg_restore", False, str(error))
    media = manifest["media"]
    report.check(
        "every referenced media object existed at backup time",
        not media["missing_at_backup"],
        f"{len(media['missing_at_backup'])} missing",
    )
    if media["copied"]:
        bad = [
            o["key"]
            for o in media["objects"]
            if o["bytes"] is not None
            and (
                not (source / MEDIA / o["key"]).is_file()
                or sha256_file(source / MEDIA / o["key"]) != o.get("sha256")
            )
        ]
        report.check("media copies match their checksums", not bad, f"{len(bad)} mismatched")
    return report


# --- disposable restore -----------------------------------------------------------------------


@contextmanager
def temporary_database(settings: Settings) -> Iterator[str]:
    """A new, empty database on the same server, dropped afterwards. Yields its URL."""
    base = make_url(settings.database_url)
    name = f"peaksift_restore_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            yield base.set(database=name).render_as_string(hide_password=False)
        finally:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


@contextmanager
def temporary_directory_storage() -> Iterator[StorageProvider]:
    directory = Path(tempfile.mkdtemp(prefix="peaksift-restore-"))
    try:
        yield LocalStorageProvider(directory)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@contextmanager
def temporary_bucket(client) -> Iterator[StorageProvider]:
    """A new bucket for the restore test, emptied and removed afterwards."""
    from app.services.storage import S3StorageProvider

    name = f"peaksift-restore-{uuid.uuid4().hex[:12]}"
    client.create_bucket(Bucket=name)
    try:
        yield S3StorageProvider(client, name)
    finally:
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=name):
            for item in page.get("Contents", []):
                client.delete_object(Bucket=name, Key=item["Key"])
        client.delete_bucket(Bucket=name)


def restore_test(
    source: Path,
    settings: Settings,
    media_target: Callable[[], object] = temporary_directory_storage,
) -> Report:
    """Restore into throwaway places and prove the backup is complete and consistent."""
    source = Path(source)
    report = verify(source, settings)
    if any(not ok for name, ok, _ in report.checks if name in DUMP_CHECKS):
        return report  # nothing trustworthy to restore (media problems are reported, not fatal)
    manifest = load_manifest(source)
    with temporary_database(settings) as url:
        env, name = _libpq(url)
        try:
            _run([settings.pg_restore_path, "--no-owner", "--no-privileges", "--exit-on-error",
                  "--dbname", name, str(source / DUMP)], env, "pg_restore")  # fmt: skip
            report.check("database restored into a temporary database", True)
        except BackupError as error:
            report.check("database restored into a temporary database", False, str(error))
            return report
        engine = create_engine(url)
        try:
            report.check(
                "schema revision matches", _revision(engine) == manifest["alembic_revision"]
            )
            counts = _table_counts(engine)
            different = sorted(t for t, n in manifest["tables"].items() if counts.get(t) != n)
            report.check("every table has its row count", not different, ", ".join(different))
            with Session(engine) as db:
                restored_keys = sorted(item.key for item in media_objects(db))
        finally:
            engine.dispose()
        expected = sorted(o["key"] for o in manifest["media"]["objects"])
        report.check(
            "restored rows reference exactly the backed-up media", restored_keys == expected
        )

    if manifest["media"]["copied"]:
        with media_target() as target:
            inventory = [
                MediaObject(o["kind"], o["key"])
                for o in manifest["media"]["objects"]
                if o["bytes"] is not None
            ]
            copied = migrate(None, LocalStorageProvider(source / MEDIA), target, objects=inventory)
            report.check(
                f"media restored into temporary {target.backend} storage",
                copied.ok and len(copied.copied) == len(inventory),
                f"{len(copied.copied)} of {len(inventory)}",
            )
            mismatched = [
                o["key"] for o in manifest["media"]["objects"]
                if o.get("sha256") and _object_sha256(target, o["key"], o["bytes"]) != o["sha256"]
            ]  # fmt: skip
            report.check("restored media matches its checksums", not mismatched,
                         f"{len(mismatched)} mismatched")  # fmt: skip
    return report


def _object_sha256(storage: StorageProvider, key: str, size: int) -> str:
    digest = hashlib.sha256()
    if size:
        for chunk in storage.iter_range(key, 0, size - 1):
            digest.update(chunk)
    return digest.hexdigest()
