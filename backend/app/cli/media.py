"""Operator commands for media storage.

    python -m app.cli.media migrate --from local --to s3 [--dry-run]
    python -m app.cli.media verify  --from local --to s3 [--checksum]

Both backends are built from the current settings (MEDIA_ROOT for ``local``; the S3_*
settings for ``s3``, which may be filled in before STORAGE_BACKEND is switched). Output
names storage keys and counts only, never credentials. Exit status is 0 only when every
object is accounted for.
"""

import argparse
import sys

from app.core.config import Settings, get_settings, storage_problems
from app.services.media_migration import MediaObject, Report, migrate, verify
from app.services.storage import LocalStorageProvider, S3StorageProvider, StorageProvider

BACKENDS = ("local", "s3")


def provider(name: str, settings: Settings) -> StorageProvider:
    if name == "local":
        return LocalStorageProvider(settings.media_root)
    problems = storage_problems(settings.model_copy(update={"storage_backend": "s3"}))
    if problems:
        raise SystemExit("S3 is not configured: " + "; ".join(problems))
    return S3StorageProvider.from_settings(settings)


def _printer(verbose: bool):
    def show(status: str, item: MediaObject) -> None:
        if verbose or status not in ("ok", "present", "copied"):
            print(f"{status:>14}  {item.kind:<5}  {item.key}")

    return show


def _summary(action: str, report: Report) -> int:
    print(
        f"{action}: {len(report.copied)} copied ({report.bytes_copied} bytes), "
        f"{len(report.present)} already present, {len(report.missing_source)} missing at "
        f"source, {len(report.conflicts)} conflicts, {len(report.mismatched)} mismatched, "
        f"{len(report.failed)} failed"
    )
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.media", description=__doc__.split("\n\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("migrate", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--from", dest="source", choices=BACKENDS, required=True)
        command.add_argument("--to", dest="destination", choices=BACKENDS, required=True)
        command.add_argument("--verbose", action="store_true", help="list every object")
    commands.choices["migrate"].add_argument(
        "--dry-run", action="store_true", help="report what would be copied; write nothing"
    )
    commands.choices["verify"].add_argument(
        "--checksum", action="store_true", help="also compare SHA-256 of every object"
    )
    args = parser.parse_args(argv)
    if args.source == args.destination:
        parser.error("--from and --to must differ")

    from app.core.database import SessionLocal

    settings = get_settings()
    source, destination = provider(args.source, settings), provider(args.destination, settings)
    show = _printer(args.verbose)
    with SessionLocal() as db:
        if args.command == "migrate":
            report = migrate(db, source, destination, dry_run=args.dry_run, progress=show)
            return _summary("dry run" if args.dry_run else "migrate", report)
        report = verify(db, source, destination, checksum=args.checksum, progress=show)
        return _summary("verify", report)


if __name__ == "__main__":
    sys.exit(main())
