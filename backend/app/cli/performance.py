"""Operator commands for performance analytics (never exposed to creators).

    python -m app.cli.performance status
    python -m app.cli.performance sync-due
    python -m app.cli.performance backfill --user USER_ID

``status`` counts published videos per remote status and syncs per status. ``sync-due`` starts
the syncs that are due now (what Celery beat runs; useful from cron where beat is not run).
``backfill`` links and syncs one creator's earlier PeakSift uploads (only those) — the same as
the creator granting analytics access; it does nothing for a creator who has not granted it.
Jobs run on the workers. Output names counts and ids only — never titles, tokens or metrics.
"""

import argparse
import sys
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.models import AnalyticsSync, PublishedContent
from app.services.performance.lifecycle import schedule_due, start_backfill
from app.services.performance.sync import has_analytics_grant
from app.services.publishing import connections


def status(db: Session, settings: Settings) -> int:
    print(f"analytics enabled: {settings.youtube_analytics_enabled} "
          f"(provider: {settings.performance_provider})")  # fmt: skip
    for label, column in (("published videos", PublishedContent.remote_status),
                          ("syncs", AnalyticsSync.status)):  # fmt: skip
        print(f"{label}:")
        for value, count in db.execute(select(column, func.count()).group_by(column)).all():
            print(f"  {value:>15}  {count}")
    return 0


def backfill(db: Session, settings: Settings, user_id: uuid.UUID) -> int:
    if not settings.youtube_analytics_enabled:
        print("Analytics is not enabled on this server.", file=sys.stderr)
        return 1
    if not has_analytics_grant(connections.get_connection(db, user_id)):
        print("This creator has not granted analytics access.", file=sys.stderr)
        return 1
    print(f"started {start_backfill(db, user_id, settings)} syncs")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="count published videos and syncs")
    commands.add_parser("sync-due", help="start the syncs that are due now")
    run = commands.add_parser("backfill", help="sync one creator's earlier PeakSift uploads")
    run.add_argument("--user", type=uuid.UUID, required=True, help="the creator's user id")
    args = parser.parse_args(argv)
    settings = get_settings()
    with SessionLocal() as db:
        if args.command == "status":
            return status(db, settings)
        if args.command == "sync-due":
            print(f"started {schedule_due(db, settings)} syncs")
            return 0
        return backfill(db, settings, args.user)


if __name__ == "__main__":
    raise SystemExit(main())
