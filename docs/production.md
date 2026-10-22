# Running PeakSift in production (V1.0)

The deployment itself — images, HTTPS proxy, Compose stack, start-up — is in
[deploy/README.md](../deploy/README.md). This page is the operator's reference for what the
application expects and provides once it runs.

## Configuration that production enforces

`APP_ENV=production` makes the API **and** the workers refuse to start (naming the setting,
never its value) unless:

- `SECRET_KEY` is a real random secret (not a placeholder; enough variety);
- `FRONTEND_URL` is an explicit `https://` origin — **HTTPS is required** (Secure cookies,
  OAuth redirects);
- `ALLOWED_HOSTS` lists the host names the API answers to (no wildcards);
- `TRUSTED_PROXIES` (if set) lists IPs/CIDRs only — only those may set `X-Forwarded-For` /
  `-Proto`, which also decide the client address used by rate limits;
- `DATABASE_URL`, `REDIS_URL` and `STORAGE_BACKEND` are set explicitly; with local storage
  `MEDIA_ROOT` is absolute; `WORK_ROOT`, if set, is absolute;
- eager Celery is off, rate limiting is on, and the publishing provider is `youtube`.

Validation errors never echo values (`hide_input_in_errors`), and an empty variable means
"unset". Interactive API docs are off in production.

## Storage

- **Media storage** (`STORAGE_BACKEND=local|s3`) holds only finished, persistent media:
  source videos, audio assets, rendered clips and edited shorts. With `s3`, use a
  **private** bucket (never public, no ACLs) and a key limited to that bucket; MinIO, AWS S3
  and Cloudflare R2 work (`S3_PATH_STYLE=true` for MinIO). The HTTP API — owner checks,
  `200`/`206`/`416`, Range — is identical on both backends. An unreachable storage service
  is a `503`, never a "missing file".
- **Scratch** (`WORK_ROOT`, owner-only) holds what a job needs while it runs; each attempt
  has its own directory, removed when it ends. Never back it up.
- **Moving to S3:** `python -m app.cli.media migrate --from local --to s3 --dry-run`, then
  without `--dry-run`, then `verify --checksum`, then switch `STORAGE_BACKEND` (copy-first,
  resumable, never deletes the source). Details in backend/README.md.
- **Deleting:** a project (confirmed by its exact name), an edit or an unused audio file
  removes its rows, then its files; failures are counted and left for
  `python -m app.cli.media cleanup --apply` (run it daily on every worker host; it also
  removes stale scratch and interrupted writes, never anything younger than the job time
  limit). On AWS, add a lifecycle rule aborting incomplete multipart uploads.

## Health

- `GET /health/live` — the process is up (no dependency is touched).
- `GET /health/ready` — PostgreSQL, Redis and storage answer within 5 s; `503` names only the
  unavailable component. External providers (OpenAI, Google) are deliberately not checked.
- `python -m app.cli.health [--ping]` — the worker's equivalent (database, Redis, storage,
  scratch, FFmpeg/ffprobe with libass; `--ping`: a live worker answers over the broker).

## Logs

JSON lines in production (`ts`, `level`, `logger`, `message`, `request_id`, `task`, `job_id`,
`exception`). Every response carries `X-Request-ID` (kept from the proxy when well formed),
and jobs carry the id of the request that started them, so one id follows a click to the
worker. Credentials, OAuth codes and tokens, signed-URL and upload-session parameters,
cookies and local paths are redacted from every logger; access lines omit query strings.

## Rate limits

Redis fixed windows, `429` with `Retry-After`: login per address (20/min) and per account
(10/15 min), registration per address (10/h), and per user for uploads, transcription,
detection, renders, framing, word timing, YouTube connection and publishing. Budgets are
configurable (`RATE_LIMITS`). If Redis is down, limited endpoints answer `503` instead of
running unlimited.

## Security headers

The frontend sends a Content-Security-Policy that allows only the app and its API (no
third-party origins, no framing, no `eval` in production), plus framing, sniffing, referrer,
permissions and opener protections. The API's responses forbid everything a page could do,
are `no-store` unless they are media, and carry HSTS in production; the proxy adds HSTS for
every page.

## Backups

`python -m app.cli.backup create <dir> --copy-media [--upload]`, `verify <dir>`,
`restore-test <dir>` — a pg_dump plus a manifest of revision, row counts and checksums,
optional media copies and an off-site bucket (`BACKUP_S3_*`), and a disposable restore into a
temporary database and bucket that proves the backup before removing everything. Run
`restore-test` regularly. Details and the disaster-recovery procedure: backend/README.md.

## Publishing

Off until configured: [youtube-setup.md](youtube-setup.md). Design and OAuth security:
[publishing.md](publishing.md).

## Performance analytics (V1.4)

Off unless `YOUTUBE_ANALYTICS_ENABLED=true` (requires publishing, the YouTube Analytics API and
the two read-only scopes on the consent screen; see [youtube-setup.md](youtube-setup.md)).
Production refuses `PERFORMANCE_PROVIDER=fake`. Run exactly one Celery **beat** process for the
scheduler (the Compose `beat` service); `python -m app.cli.performance status` shows synced
videos and syncs by status (counts only). Creators can delete collected metrics themselves.

## Known limitations (V1.0)

- Single host with Docker Compose; no Kubernetes, multi-region, CDN, GPU autoscaling or
  custom-domain UI. Scale by raising `WEB_CONCURRENCY` / `CELERY_CONCURRENCY` or adding
  worker replicas.
- Each render on S3 downloads its input into scratch (no worker-side cache); media files are
  copied sequentially by the migration, cleanup and backup tools.
- YouTube only; videos from unverified Google projects stay private; processing completion is
  not observable with the upload-only scope.
- Pattern-based log redaction cannot recognise a secret without a recognisable shape or key
  name — code still never logs secrets in the first place.
