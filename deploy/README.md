# Deploying PeakSift (single host, Docker Compose)

`docker-compose.prod.yml` runs the whole product behind one HTTPS origin:

| Service | Image | Role |
| --- | --- | --- |
| `proxy` | `nginx:1.27-alpine` | TLS, `/api/…` → API (prefix removed), `/…` → frontend; streams uploads and Range responses unbuffered; port 80 only redirects |
| `frontend` | `deploy/frontend.Dockerfile` | Next.js standalone server, user `node` |
| `api` | `deploy/backend.Dockerfile` target `api` | gunicorn + `uvicorn-worker` (`WEB_CONCURRENCY`, default 2), user `peaksift` (uid 10001) |
| `worker` | target `worker` | Celery, one job per process (`CELERY_CONCURRENCY`, default 1), FFmpeg with libass and the caption fonts |
| `migrate` | target `api` | one-shot `alembic upgrade head` before the API and worker start |
| `postgres`, `redis` | official images | data and the job broker / rate limiter (password-protected) |
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
- **Scratch:** `/work` volumes hold only in-flight job files. Run
  `docker compose … exec worker python -m app.cli.media cleanup --apply` daily to remove
  leftovers of crashed jobs and orphaned objects.
- **Upgrades:** rebuild and `up -d`; `migrate` applies new migrations before the API and
  worker start.
