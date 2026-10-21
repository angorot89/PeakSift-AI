"""Operator commands for semantic visual search (never exposed to creators).

    python -m app.cli.semantic status
    python -m app.cli.semantic reindex [--stale] [--missing] [--failed] [--project ID]
                                       [--limit N] [--dry-run]

``status`` counts assets per visual-search state for the server's current model. ``reindex``
enqueues indexing for the selected assets — by default those whose index is **stale** (made by
another model) or **missing**; ``--failed`` also retries failed ones (a fresh attempt budget is
not granted: an index that used every attempt stays failed). Jobs run on the workers like any
upload's; nothing is embedded in this process. ``--limit`` bounds one run (default 500), so a
large library can be reindexed in batches. Output names counts and asset ids only.
"""

import argparse
import sys
import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.models import VisualAsset
from app.services.semantic.indexing import TooManyAttempts
from app.services.semantic.lifecycle import start_indexing
from app.services.semantic.registry import configured_identity
from app.services.semantic.state import SemanticState, semantic_state


def _assets(db: Session, project: uuid.UUID | None):
    statement = (
        select(VisualAsset)
        .options(selectinload(VisualAsset.semantic_indexes))
        .order_by(VisualAsset.created_at, VisualAsset.id)
    )
    if project is not None:
        statement = statement.where(VisualAsset.project_id == project)
    return db.scalars(statement)


def status(db: Session, settings: Settings) -> int:
    identity = configured_identity(settings)
    if identity is None:
        print("Visual search is turned off (SEMANTIC_PROVIDER=disabled).")
        return 0
    counts = Counter(semantic_state(a.semantic_indexes, identity).value for a in _assets(db, None))
    print(f"model: {identity.provider} {identity.model} {identity.model_version} "
          f"({identity.embedding_version}, {identity.dimensions} dimensions)")  # fmt: skip
    for state in SemanticState:
        if state != SemanticState.UNAVAILABLE:
            print(f"{state.value:>12}  {counts.get(state.value, 0)}")
    return 0


def reindex(db: Session, settings: Settings, args: argparse.Namespace) -> int:
    identity = configured_identity(settings)
    if identity is None:
        print("Visual search is turned off; nothing to reindex.", file=sys.stderr)
        return 1
    wanted = set()
    if args.stale or not (args.missing or args.failed):
        wanted.add(SemanticState.STALE)
    if args.missing or not (args.stale or args.failed):
        wanted.add(SemanticState.NOT_INDEXED)
    if args.failed:
        wanted.add(SemanticState.FAILED)
    started = skipped = exhausted = 0
    for asset in _assets(db, args.project):
        if started >= args.limit:
            break
        state = semantic_state(asset.semantic_indexes, identity)
        if state not in wanted:
            continue
        if args.dry_run:
            print(f"would index  {asset.id}  ({state.value})")
            started += 1
            continue
        try:
            index = start_indexing(db, asset, settings, retry=state == SemanticState.FAILED)
        except TooManyAttempts:
            exhausted += 1
            continue
        if index is None:
            skipped += 1
        else:
            started += 1
            print(f"queued  {asset.id}  ({state.value})")
    verb = "would queue" if args.dry_run else "queued"
    print(f"{verb} {started}, skipped {skipped}, out of attempts {exhausted}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="count assets per visual-search state")
    run = commands.add_parser("reindex", help="queue indexing for stale/missing/failed assets")
    run.add_argument("--stale", action="store_true", help="indexes made by another model")
    run.add_argument("--missing", action="store_true", help="assets never indexed")
    run.add_argument("--failed", action="store_true", help="retry failed indexes too")
    run.add_argument("--project", type=uuid.UUID, help="only this project's assets")
    run.add_argument("--limit", type=int, default=500, help="at most this many (default 500)")
    run.add_argument("--dry-run", action="store_true", help="list, do not queue")
    args = parser.parse_args(argv)
    if args.command == "reindex" and args.limit < 1:
        parser.error("--limit must be at least 1")
    settings = get_settings()
    with SessionLocal() as db:
        if args.command == "status":
            return status(db, settings)
        return reindex(db, settings, args)


if __name__ == "__main__":
    raise SystemExit(main())
