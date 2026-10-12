# PeakSift AI

**Find the moments worth clipping.**

PeakSift AI is a short-form clipping and creation platform. Creators bring long-form content — videos, streams, podcasts, interviews, recordings — and PeakSift helps them find the strongest moments and turn them into short-form clips for TikTok, YouTube Shorts, and Instagram Reels.

## Current status

**Milestones 1–3 are complete** (Foundation V0.1, Video Upload V0.2, Transcription V0.3). What exists today:

- A landing page.
- Email/password accounts: register, log in, log out, with an HttpOnly session cookie.
- Projects: create a project, list your projects, open a project.
- **Source video upload** on a project: MP4, MOV or WebM, with real upload progress.
- **Metadata extraction** with ffprobe: duration, resolution, frame rate, video/audio codecs — shown on the project page, or a clear failure state for unreadable files.
- **Owner-only preview** of the uploaded video with a native player (HTTP Range streaming).
- **Background transcription**: one click turns a ready video into a timestamped transcript. Audio is normalized with FFmpeg, split into 10-minute chunks and transcribed by a Celery worker with faster-whisper (local, default) or OpenAI (`whisper-1`); the project page polls real progress, shows failures and stalled jobs with retry, and renders the transcript with `HH:MM:SS` timestamps, paging and copy.
- PostgreSQL schema (`users`, `projects`, `videos`, `transcriptions`, `transcript_segments`) managed with Alembic migrations.
- Automated tests (backend 355), linting and CI with PostgreSQL, Redis and FFmpeg.

**Not built yet** (see [docs/milestones.md](docs/milestones.md)):

| Feature                                   | Milestone |
| ----------------------------------------- | --------- |
| AI clip detection                         | 4 (next)  |
| Clip generation                           | 5         |
| Creator intelligence & metadata           | 6         |
| Editor, asset libraries, Morocco Mode     | later     |

The dashboard's Videos and Clips cards do not show counts yet; clip detection is not built.

## Architecture (as built)

```
Browser ──▶ Next.js frontend (:3000) ──fetch, cookie──▶ FastAPI backend (:8000) ──▶ PostgreSQL
                                                              │                         ▲
                                                              ├──▶ MEDIA_ROOT (videos, normalized audio)
                                                              ├──▶ ffprobe (metadata)   │ status + segments
                                                              └──▶ Redis ──▶ Celery worker (ffmpeg → chunks → faster-whisper | OpenAI)
```

- **Frontend** — Next.js App Router, TypeScript, Tailwind CSS. Talks to the API with `credentials: "include"`; asks `GET /auth/me` to learn who is signed in. No tokens in browser storage.
- **Backend** — FastAPI, SQLAlchemy 2 (sync), Alembic, psycopg 3. Argon2id password hashing; HS256 JWT delivered in an HttpOnly `SameSite=Lax` cookie; CORS limited to the frontend origin. Uploads are streamed to local storage and probed with ffprobe synchronously; transcription runs in a Celery worker over Redis, with the database as the source of truth for job state.
- **Database** — PostgreSQL. `users`, `projects`, `videos`, `transcriptions`, `transcript_segments` tables, UUID keys, timezone-aware timestamps.

Details: [docs/architecture.md](docs/architecture.md), [backend/README.md](backend/README.md), [frontend/README.md](frontend/README.md).

## Local development

### Prerequisites

- Node.js 20.9+
- Python 3.11+
- PostgreSQL 14+ — either Docker (`docker compose up -d`, which creates the `peaksift` and `peaksift_test` databases) or a local installation
- FFmpeg (`ffprobe` for metadata, `ffmpeg` for audio): `brew install ffmpeg` / `apt install ffmpeg`. Without it uploads end in status `failed` and transcription cannot run.
- Redis 7+ — Docker Compose (included) or `brew install redis && brew services start redis`. Broker for background jobs; the API starts without it, but starting a transcription answers `503` until it is reachable.

### 1. PostgreSQL and Redis

```bash
docker compose up -d                 # PostgreSQL + Redis; or: createdb peaksift && createdb peaksift_test, brew services start redis
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # set DATABASE_URL and SECRET_KEY (openssl rand -hex 32)
alembic upgrade head
uvicorn app.main:app --reload        # http://localhost:8000 — docs at /docs
```

Uploaded videos and derived audio are written under `backend/media/` (`MEDIA_ROOT`), which is git-ignored.

### 3. Celery worker (transcription)

In a second terminal, same virtualenv and directory:

```bash
cd backend && source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info
```

The default provider is faster-whisper on CPU (`FASTER_WHISPER_MODEL=small`, `int8`); the model (~460 MB) is downloaded on the first transcription, never at startup. On macOS, CPU mode is the supported path — there is no Apple-GPU acceleration in this stack. Set `FASTER_WHISPER_MODEL=tiny` to try the mechanics quickly, or `TRANSCRIPTION_PROVIDER=openai` with `OPENAI_API_KEY` for the hosted provider.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:3000
```

Open **http://localhost:3000** (not `127.0.0.1`) so the auth cookie, CORS origin and video preview line up.

### Checks

```bash
cd backend && ruff check . && ruff format --check . && pytest
cd backend && python scripts/celery_smoke.py      # real worker round-trip over Redis
cd frontend && npm run lint && npm run build
```

Backend tests use a separate database (`TEST_DATABASE_URL`, default `peaksift_test`), a temporary media directory and Celery eager mode; they never touch your development data, never download a speech model (inference is mocked) and never call OpenAI. Media fixtures are generated with `ffmpeg` at test time; ffmpeg- and Redis-dependent tests skip when those are missing locally and are mandatory in CI.

## Upload flow

1. Open a project and choose (or drag in) an MP4, MOV or WebM file.
2. The browser streams it to `POST /projects/{id}/videos` with a progress bar.
3. The API validates the name, extension and MIME type, writes the file under `MEDIA_ROOT` with a generated key, enforces `MAX_VIDEO_UPLOAD_BYTES` (default 2 GiB), then runs `ffprobe`.
4. The project page shows the result: **Ready** with real metadata and a preview player, or **Failed** with the reason and an option to upload a different file.

### Configuration that matters here

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEDIA_ROOT` | `./media` (relative to `backend/`) | Where uploaded files live |
| `MAX_VIDEO_UPLOAD_BYTES` | `2147483648` (2 GiB) | Upload size limit (`413` beyond it) |
| `FFPROBE_PATH` | `ffprobe` | ffprobe binary |
| `FFPROBE_TIMEOUT_SECONDS` | `30` | Per-file probe limit; exceeding it marks the video `failed` |

## Transcription flow

1. On a ready video, click **Transcribe video**. The API creates the job, queues it in Redis and returns at once.
2. The Celery worker extracts normalized audio (mono 16 kHz 64 kbps MP3), splits it into `TRANSCRIPTION_CHUNK_SECONDS` chunks (default 10 min) and transcribes them in order with the configured provider, committing timestamped segments and real progress after every chunk.
3. The page polls every 4 s while the job is `queued` / `extracting_audio` / `transcribing`, then shows the transcript — `HH:MM:SS` timestamps, 200 segments per page with **Load more**, **Copy transcript** — or a failure/stalled state with **Retry transcription**.

### Providers and timestamps

| Provider (`TRANSCRIPTION_PROVIDER`) | Where it runs | Timestamps | Setup |
| --- | --- | --- | --- |
| `faster_whisper` (default) | locally in the worker (CPU; CUDA optional) | native segment timestamps | nothing besides FFmpeg; model downloads on first use (`FASTER_WHISPER_MODEL`, `_DEVICE`, `_COMPUTE_TYPE`, `_BEAM_SIZE`) |
| `openai` | OpenAI API | `OPENAI_TIMESTAMP_MODEL=whisper-1` with `verbose_json` segment timestamps | `OPENAI_API_KEY` (never committed, never shown); `gpt-4o-mini-transcribe` / `gpt-4o-transcribe` are text-only in the current API and are refused for timing |

PeakSift cuts clips from transcript timestamps, so a provider must return real segment timestamps; text-only responses are never padded with invented times. Provider choice is server configuration.

### Statuses, progress and retries

`queued` → `extracting_audio` → `transcribing` → `completed` | `failed`. Progress is real (5 % once audio is ready, then chunks done ÷ total). Transient provider errors (rate limits, timeouts, 5xx) are retried in-task with exponential backoff; configuration, invalid-audio and malformed-output errors fail immediately with a safe `error_message`. A job whose worker stopped reporting for `TRANSCRIPTION_STALE_AFTER_SECONDS` (30 min) is flagged `is_stale` and can be retried; a Celery task id acts as a fencing token so two workers never both complete the same job.

## Security model (high level)

- Every project and video endpoint is scoped to the signed-in owner; anything else is a `404`.
- Browser-supplied filenames are metadata only. Files are stored under application-generated UUID keys, and the single path-resolution function refuses anything outside `MEDIA_ROOT`.
- Uploads are validated in layers (extension, MIME plausibility, size during streaming, then ffprobe proving the bytes are readable media). Oversized, empty or unreadable uploads leave no stray files.
- ffprobe and ffmpeg are invoked with argument lists (no shell) and timeouts; their stderr is never stored or returned. Only database ids cross the job broker.
- The OpenAI key lives in server settings only — never in responses, logs, task payloads, the frontend or CI.
- Nothing in `MEDIA_ROOT` is served statically; the only way to read bytes is the authenticated, owner-only content endpoint.
- Error responses never include filesystem paths, storage keys or submitted values.

## Known limitations

- Local filesystem storage only; object storage (S3/R2) is a later milestone.
- Metadata probing runs inside the upload request; very large files make the upload response wait for ffprobe.
- The frontend does not know the size limit in advance; an oversized file is rejected by the API with a `413` message.
- Deleting is not implemented; replacing a video keeps the previous file and record (and its transcription).
- Chunk boundaries are plain time cuts, not silence-aware: a word spoken across a boundary can be split between two segments. Chunks are transcribed sequentially (no parallelism, no GPU workers, no provider fallback chains).
- No speaker diarization, word-level timestamps, translation, transcript editing or live transcription. The `speaker` column is reserved and always null.
- A job interrupted by a worker crash restarts from the beginning via the stale rule or retry (no chunk-level resume).
- Transcription quality has only been sanity-checked on synthesised English speech; no Darija/Moroccan benchmarking has been done.
- AI clip detection does not exist yet — the UI says so.

## Routes

**Frontend:** `/`, `/login`, `/register`, `/dashboard`, `/projects`, `/projects/new`, `/projects/[id]`

**API:** `GET /health` · `POST /auth/register` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` · `GET /projects` · `POST /projects` · `GET /projects/{id}` · `POST /projects/{id}/videos` · `GET /projects/{id}/videos` · `GET /projects/{id}/videos/{video_id}` · `GET /videos/{video_id}/content` · `POST /projects/{id}/videos/{video_id}/transcription` · `GET …/transcription` · `POST …/transcription/retry` · `GET …/transcript` — see [backend/README.md](backend/README.md#api).

## Continuous integration

Every push to `main` and every pull request runs [GitHub Actions](.github/workflows/ci.yml): the frontend job runs `npm ci`, lint and build; the backend job installs FFmpeg, runs Ruff, applies and checks the Alembic migrations against a PostgreSQL service container, runs the test suite — including the real-ffmpeg/ffprobe media tests (fixtures generated at test time), audio extraction, chunking and timestamp shifting with synthetic clips, Celery in eager mode, and a live-Redis connection check against a Redis service container — and finally a tiny real worker smoke (`scripts/celery_smoke.py`: start a worker, round-trip `ping`, stop). Speech-model inference is mocked and `HF_HUB_OFFLINE=1` guarantees CI never downloads a model; there is no OpenAI key in CI. CI validates only — nothing is deployed.

Development happens on feature branches merged through pull requests; see [CLAUDE.md](CLAUDE.md#git-workflow).

## Localization: Global + Morocco Mode (future)

PeakSift will ship a **Global** experience available to everyone.

**Morocco Mode** is a planned future localization layer that *extends* the Global experience — users keep every Global tool and library, plus Darija-aware analysis, Moroccan cultural context, local sound effects and creator assets, and Morocco-specific clip suggestions. It is not a separate app, and **it is not implemented**.

## Repository structure

```
PeakSift-AI/
├── frontend/             # Next.js app — see frontend/README.md
├── backend/              # FastAPI service — see backend/README.md
├── docs/                 # Architecture and milestone docs
├── docker/               # PostgreSQL init script for Docker Compose
├── docker-compose.yml    # Local PostgreSQL
└── .github/workflows/    # CI
```
