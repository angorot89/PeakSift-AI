"""Measure semantic search costs on this machine: text embedding and the scoped vector scan.

    python scripts/semantic_search_probe.py --database-url postgresql+psycopg://…/scratch_db \\
        [--model-dir ./models/clip-vit-b-32] [--assets 200] [--frames 8] [--other-projects 50]

The database must be an EMPTY scratch database the operator created for this (never the
application's): the probe migrates it, fills it with synthetic unit vectors — one project with
``--assets`` assets of ``--frames`` frames, plus ``--other-projects`` projects of the same size
that a scoped search must ignore — measures, and downgrades it again. With ``--model-dir`` the
real text encoder is timed (first query including the model load, then warm queries); without
it the deterministic fake provider stands in. Prints medians in milliseconds; nothing is sent
anywhere. These are local measurements, not cloud benchmarks.
"""

import argparse
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

QUERIES = ["rocket launch", "bridge structure", "city skyline at night", "a microphone", "salad"]


def _median_ms(samples: list[float]) -> float:
    return round(statistics.median(samples) * 1000, 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--model-dir")
    parser.add_argument("--assets", type=int, default=200)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--other-projects", type=int, default=50)
    args = parser.parse_args()
    os.environ["DATABASE_URL"] = args.database_url
    os.environ["SEMANTIC_PROVIDER"] = "clip_onnx" if args.model_dir else "fake"
    if args.model_dir:
        os.environ["SEMANTIC_MODEL_DIR"] = args.model_dir

    import numpy as np
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from app.core.config import get_settings
    from app.models import EMBEDDING_DIMENSIONS
    from app.services.semantic.registry import configured_identity, get_provider
    from app.services.semantic.search import QUERY_CACHE, query_vector, thresholds_for, visual_scores

    backend = Path(__file__).resolve().parents[1]
    config = Config(backend / "alembic.ini")
    config.set_main_option("script_location", str(backend / "alembic"))
    engine = create_engine(args.database_url)
    with engine.connect() as connection:
        if connection.execute(text("SELECT to_regclass('public.users')")).scalar():
            print("Refusing: the database is not empty (use a scratch database).", file=sys.stderr)
            return 1
    command.upgrade(config, "head")
    settings = get_settings()
    identity = configured_identity(settings)
    thresholds = thresholds_for(identity)
    rng = np.random.default_rng(7)
    try:
        # --- fill: one searched project, plus others the scan must not touch ------------
        started = time.perf_counter()
        target = None
        with engine.begin() as connection:
            user = uuid.uuid4()
            connection.execute(
                text("INSERT INTO users (id, email, password_hash, created_at) "
                     "VALUES (:id, :email, 'x', now())"),
                {"id": user, "email": f"probe-{user.hex[:8]}@example.com"},
            )  # fmt: skip
            for p in range(1 + args.other_projects):
                project = uuid.uuid4()
                target = target or project
                connection.execute(
                    text("INSERT INTO projects (id, user_id, name, status, created_at, updated_at)"
                         " VALUES (:id, :user, 'probe', 'created', now(), now())"),
                    {"id": project, "user": user},
                )  # fmt: skip
                assets, indexes, vectors = [], [], []
                for a in range(args.assets):
                    asset, index = uuid.uuid4(), uuid.uuid4()
                    assets.append({"id": asset, "project": project, "key": f"probe/{asset.hex}.mp4",
                                   "sha": f"{p:08d}{a:08d}".ljust(64, "0")})  # fmt: skip
                    indexes.append({"id": index, "asset": asset})
                    raw = rng.standard_normal((args.frames, EMBEDDING_DIMENSIONS))
                    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
                    for f in range(args.frames):
                        vectors.append({"id": uuid.uuid4(), "index": index, "frame": f,
                                        "time": 0.5 + f, "vector": str(raw[f].tolist())})  # fmt: skip
                connection.execute(
                    text("INSERT INTO visual_assets (id, project_id, kind, display_name, "
                         "storage_key, content_type, file_size, sha256, width, height, "
                         "duration_seconds, fps, codec, container, has_alpha, has_audio, "
                         "description, tags, created_at, updated_at) VALUES (:id, :project, "
                         "'video', 'VID.mp4', :key, 'video/mp4', 1, :sha, 1280, 720, 10, 30, "
                         "'h264', 'mp4', false, false, '', '[]', now(), now())"),
                    assets,
                )  # fmt: skip
                connection.execute(
                    text("INSERT INTO visual_semantic_indexes (id, visual_asset_id, status, "
                         "attempt, provider, model, model_version, embedding_version, dimensions,"
                         " source_sha256, config, frames_total, frames_done, embedding_count, "
                         "reused, created_at, updated_at, completed_at) VALUES (:id, :asset, "
                         f"'ready', 1, '{identity.provider}', '{identity.model}', "
                         f"'{identity.model_version}', '{identity.embedding_version}', "
                         f"{identity.dimensions}, repeat('0', 64), '{{}}', {args.frames}, "
                         f"{args.frames}, {args.frames}, false, now(), now(), now())"),
                    indexes,
                )  # fmt: skip
                connection.execute(
                    text("INSERT INTO visual_asset_embeddings (id, index_id, frame_index, "
                         "frame_time, embedding, created_at) VALUES (:id, :index, :frame, :time,"
                         " CAST(:vector AS vector), now())"),
                    vectors,
                )  # fmt: skip
            connection.execute(text("ANALYZE"))
        total = (1 + args.other_projects) * args.assets * args.frames
        print(f"filled {total} vectors ({1 + args.other_projects} projects × {args.assets} "
              f"assets × {args.frames} frames) in {time.perf_counter() - started:.1f} s")  # fmt: skip

        # --- text embedding ---------------------------------------------------------------
        provider = get_provider(settings)
        QUERY_CACHE.clear()
        t0 = time.perf_counter()
        query_vector(provider, thresholds, QUERIES[0])
        cold = time.perf_counter() - t0
        warm = []
        for query in QUERIES[1:] * 4:
            QUERY_CACHE.clear()
            t0 = time.perf_counter()
            query_vector(provider, thresholds, query)
            warm.append(time.perf_counter() - t0)
        cached = []
        for _ in range(20):
            t0 = time.perf_counter()
            query_vector(provider, thresholds, QUERIES[1])
            cached.append(time.perf_counter() - t0)
        print(f"text embedding ({identity.provider}): first {cold * 1000:.0f} ms (includes "
              f"loading the text encoder), warm median {_median_ms(warm)} ms, cached "
              f"{_median_ms(cached)} ms")  # fmt: skip

        # --- the scoped scan ----------------------------------------------------------------
        vector = query_vector(provider, thresholds, QUERIES[0])
        with Session(engine) as db:
            visual_scores(db, target, identity, vector)  # warm the plan cache
            scans = []
            for _ in range(20):
                t0 = time.perf_counter()
                found = visual_scores(db, target, identity, vector)
                scans.append(time.perf_counter() - t0)
        print(f"scoped vector scan: {len(found)} assets ({args.assets * args.frames} vectors of "
              f"{total}) median {_median_ms(scans)} ms, max {max(scans) * 1000:.1f} ms")  # fmt: skip
        return 0
    finally:
        command.downgrade(config, "base")


if __name__ == "__main__":
    raise SystemExit(main())
