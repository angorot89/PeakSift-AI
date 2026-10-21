# Deploying PeakSift (single host, Docker Compose)

`docker-compose.prod.yml` runs the whole product behind one HTTPS origin:

| Service | Image | Role |
| --- | --- | --- |
| `proxy` | `nginx:1.27-alpine` | TLS, `/api/…` → API (prefix removed), `/…` → frontend; streams uploads and Range responses unbuffered; port 80 only redirects |
| `frontend` | `deploy/frontend.Dockerfile` | Next.js standalone server, user `node` |
| `api` | `deploy/backend.Dockerfile` target `api` | gunicorn + `uvicorn-worker` (`WEB_CONCURRENCY`, default 2), user `peaksift` (uid 10001) |
| `worker` | target `worker` | Celery, one job per process (`CELERY_CONCURRENCY`, default 1), FFmpeg with libass and the caption fonts |
| `migrate` | target `api` | one-shot `alembic upgrade head` before the API and worker start |
| `postgres` | `deploy/postgres.Dockerfile` (the official `postgres:16-alpine` image plus pgvector built from a pinned release) | data, including the semantic visual-search vectors |
| `redis` | official image | the job broker / rate limiter (password-protected) |
| `minio`, `minio-init` | `deploy/minio.Dockerfile` (MinIO and `mc` built from source at pinned releases — MinIO no longer publishes community images) | private media bucket; `minio-init` creates it (never public) and an application user limited to it |

Nothing secret is baked into an image or written in the compose file: every credential
comes from `deploy/.env`, which is git-ignored.

## HTTPS is required

Production refuses to start without an `https://` `FRONTEND_URL`: session cookies are
`Secure`, and Google's OAuth redirect must be HTTPS. Put a real certificate for your host in
`deploy/certs/tls.crt` and `deploy/certs/tls.key` (or terminate TLS in a load balancer in
front and adapt the proxy). `scripts/dev-certs.sh` writes a self-signed one **for local
testing only**.

## Start

```bash
cp deploy/.env.example deploy/.env            # replace EVERY value (secrets: 32+ random chars)
deploy/scripts/dev-certs.sh localhost          # local testing only
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build --wait
python3 deploy/scripts/smoke.py https://localhost
```

The API is served at `https://<host>/api` (the frontend is built with `NEXT_PUBLIC_API_URL=/api`),
so the browser talks to one origin. If you publish to YouTube, register
`https://<host>/api/publishing/youtube/callback` as the OAuth redirect URI.

## Operating

- **Health:** the orchestrator can use `GET /api/health/live` (process up) and
  `GET /api/health/ready` (PostgreSQL, Redis, storage); the worker container runs
  `python -m app.cli.health` as its healthcheck.
- **Logs:** JSON lines with request ids on stdout/stderr (`docker compose logs`); the proxy
  logs paths without query strings; secrets are redacted.
- **Models:** the worker keeps speech models in the `models` volume (`HF_HOME`). For smart
  reframing, install the face model once:
  `docker compose -f deploy/docker-compose.prod.yml exec worker python scripts/fetch_reframe_model.py` (it writes to `REFRAME_MODEL_PATH`, `/models/…` in the image)
  (pinned SHA-256; without it, smart framing reports itself unavailable).
  For semantic visual search (V1.3), install the local CLIP model once:
  `docker compose -f deploy/docker-compose.prod.yml exec worker python scripts/fetch_semantic_model.py`
  (about 600 MB into `SEMANTIC_MODEL_DIR`, `/models/clip-vit-b-32`; pinned revisions, size and
  SHA-256). Without it, uploads still work and each asset reports "visual search unavailable";
  after installing, `exec worker python -m app.cli.semantic reindex --failed` indexes them.
  The worker loads the model on its first indexing job (about 1 GB of memory per worker
  process with both encoders; keep `CELERY_CONCURRENCY=1`, or set `SEMANTIC_QUEUE=semantic` and
  run a dedicated worker with `-Q semantic --concurrency 1`). The API mounts the same `models`
  volume read-only and loads only the text encoder, on the first search (about 0.5 GB per API
  process: size `WEB_CONCURRENCY` accordingly, or set `SEMANTIC_PROVIDER=disabled`). After changing the model, `python -m app.cli.semantic
  status` shows stale assets and `reindex` (default: stale and never-indexed) refreshes them.
- **Scratch:** `/work` volumes hold only in-flight job files. Run
  `docker compose … exec worker python -m app.cli.media cleanup --apply` daily to remove
  leftovers of crashed jobs and orphaned objects.
- **Backups:** `docker compose -f deploy/docker-compose.prod.yml exec api python -m app.cli.backup create /work/backup-$(date +%F) --copy-media`, then `verify` and `restore-test` on it (a temporary database is created and dropped; media is restored to a temporary directory because the application key cannot create buckets). Copy the directory off the host — or set `BACKUP_S3_*` and add `--upload` — and run `restore-test` regularly. See backend/README.md "Backups and restore tests".
- **Upgrades:** rebuild and `up -d`; `migrate` applies new migrations before the API and
  worker start.
