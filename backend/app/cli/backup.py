"""Backups you can prove restorable.

    python -m app.cli.backup create <dir> [--copy-media] [--upload]
    python -m app.cli.backup verify <dir>
    python -m app.cli.backup restore-test <dir>

``create`` writes ``database.dump`` (pg_dump custom format) and ``manifest.json`` (revision,
row counts, media inventory, checksums) into a new directory; ``--copy-media`` also copies
every database-referenced media object (with SHA-256) and ``--upload`` copies the backup to
the secondary bucket (``BACKUP_S3_*``). ``verify`` recomputes everything; ``restore-test``
restores into a temporary database and a temporary bucket (S3 media) or directory (local
media), checks it, and removes all of it. Output never contains credentials. Exit status is
0 only when every check passes.
"""

import argparse
import sys
from contextlib import contextmanager
from pathlib import Path

from app.core.config import get_settings, storage_problems
from app.services import backup
from app.services.storage import S3StorageProvider, media_storage


def _print(report: backup.Report) -> int:
    for name, ok, detail in report.checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}{f' — {detail}' if detail else ''}")
    print("OK" if report.ok else "FAILED")
    return 0 if report.ok else 1


def _secondary(settings):
    if not settings.backup_s3_bucket:
        raise SystemExit("--upload needs BACKUP_S3_BUCKET (and its endpoint and keys)")
    check = settings.model_copy(update={
        "storage_backend": "s3",
        **{f"s3_{name}": getattr(settings, f"backup_s3_{name}") for name in (
            "endpoint_url", "region", "bucket", "access_key_id", "secret_access_key",
            "path_style", "secure")},
    })  # fmt: skip
    problems = storage_problems(check)
    if problems:
        raise SystemExit("Backup storage is not configured: " + "; ".join(problems))
    return S3StorageProvider.from_settings(settings, prefix="backup_s3")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.backup", description=__doc__.split("\n\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("create")
    make.add_argument("directory", type=Path)
    make.add_argument("--copy-media", action="store_true", help="also copy every media object")
    make.add_argument("--upload", action="store_true", help="copy to the BACKUP_S3_* bucket")
    for name in ("verify", "restore-test"):
        commands.add_parser(name).add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    settings = get_settings()

    try:
        if args.command == "create":
            secondary = _secondary(settings) if args.upload else None
            from app.core.database import SessionLocal
            from app.main import app as api

            with SessionLocal() as db:
                manifest = backup.create(
                    args.directory, settings, db, media_storage(settings),
                    copy_media=args.copy_media, app_version=api.version,
                )  # fmt: skip
            media = manifest["media"]
            print(f"backup written: {len(manifest['tables'])} tables, "
                  f"{media['count']} media objects ({media['bytes']} bytes)"
                  f"{', copied' if media['copied'] else ''}; "
                  f"{len(media['missing_at_backup'])} referenced objects missing")  # fmt: skip
            if secondary is not None:
                prefix = backup.upload(args.directory, secondary)
                print(f"uploaded to the backup bucket under {prefix}")
            return _print(backup.verify(args.directory, settings))
        if args.command == "verify":
            return _print(backup.verify(args.directory, settings))
        return _print(backup.restore_test(args.directory, settings, _media_target(settings)))
    except backup.BackupError as error:
        print(f"FAILED: {error}")
        return 1


def _media_target(settings):
    """A temporary bucket on the media S3 service when this key may create one; otherwise
    (e.g. a key limited to its own bucket, as in deploy/) a temporary directory."""
    if settings.storage_backend != "s3":
        return backup.temporary_directory_storage

    @contextmanager
    def target():
        client = S3StorageProvider.from_settings(settings)._client
        try:
            context = backup.temporary_bucket(client)
            storage = context.__enter__()
        except Exception:  # noqa: BLE001 — not allowed to create buckets
            print("note: this key cannot create a bucket; restoring media to a temporary directory")
            with backup.temporary_directory_storage() as storage:
                yield storage
            return
        try:
            yield storage
        finally:
            context.__exit__(None, None, None)

    return target


if __name__ == "__main__":
    sys.exit(main())
