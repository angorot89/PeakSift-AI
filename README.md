# PeakSift AI

**Find the moments worth clipping.**

PeakSift AI is a short-form clipping and creation platform. Creators bring long-form content — videos, streams, podcasts, interviews, recordings — and PeakSift helps them find the strongest moments and turn them into short-form clips for TikTok, YouTube Shorts, and Instagram Reels.

## Current status

**Milestones 1–5 are complete** (Foundation V0.1, Video Upload V0.2, Transcription V0.3, AI Clip Detection V0.4, Clip Generation V0.5). What exists today:

- A landing page.
- Email/password accounts: register, log in, log out, with an HttpOnly session cookie.
- Projects: create a project, list your projects, open a project.
- **Source video upload** on a project: MP4, MOV or WebM, with real upload progress.
- **Metadata extraction** with ffprobe: duration, resolution, frame rate, video/audio codecs — shown on the project page, or a clear failure state for unreadable files.
- **Owner-only preview** of the uploaded video with a native player (HTTP Range streaming).
- **Background transcription**: one click turns a ready video into a timestamped transcript. Audio is normalized with FFmpeg, split into 10-minute chunks and transcribed by a Celery worker with faster-whisper (local, default) or OpenAI (`whisper-1`); the project page polls real progress, shows failures and stalled jobs with retry, and renders the transcript with `HH:MM:SS` timestamps, paging and copy.
- **AI clip detection**: on a transcribed video, pick an AI provider and model (local Ollama or hosted OpenAI, from server allow-lists) and start a background run. The transcript is analysed in bounded windows, every proposal is validated against the transcript, deduplicated and ranked, and the project page shows candidate cards — title, time range, duration, a 0–100 editorial score with its breakdown, hook, rationale, transcript excerpt — with an in-page preview of that range of the original video and save/dismiss decisions. Details: [docs/clip-detection.md](docs/clip-detection.md).
- **Clip generation**: **Generate clip** on a candidate renders exactly its validated time range from the original upload into a private MP4 (H.264 + AAC, fast-start, original aspect ratio and orientation) in the background worker with FFmpeg, validates it with ffprobe, then shows the rendered clip in the page with **Download MP4**. Real render states, failure messages and retry; clips persist across sessions. Details: [docs/clip-generation.md](docs/clip-generation.md).
- PostgreSQL schema (`users`, `projects`, `videos`, `transcriptions`, `transcript_segments`, `clip_detection_runs`, `clip_candidates`, `clips`) managed with Alembic migrations.
- Automated tests (backend 765), linting and CI with PostgreSQL, Redis and FFmpeg (including real clip renders).

**Not built yet** (see [docs/milestones.md](docs/milestones.md)):

| Feature                                                              | Milestone |
| -------------------------------------------------------------------- | --------- |
| Short-form editing (vertical layouts, captions, trimming)            | 6 (next)  |
| Creator intelligence & metadata, publishing                          | later     |
| Asset libraries, Morocco Mode                                        | later     |

The dashboard's Videos and Clips cards do not show counts yet. Generated clips keep the source's aspect ratio — vertical 9:16 layouts and captions are Milestone 6.

## Architecture (as built)

```
Browser ──▶ Next.js frontend (:3000) ──fetch, cookie──▶ FastAPI backend (:8000) ──▶ PostgreSQL
                                                              │                         ▲
                                                              ├──▶ MEDIA_ROOT (videos, normalized audio)
                                                              ├──▶ ffprobe (metadata)   │ status, segments, candidates
                                                              └──▶ Redis ──▶ Celery worker ──▶ transcription: ffmpeg → chunks → faster-whisper | OpenAI
                                                                                           ├─▶ clip detection: transcript windows → Ollama | OpenAI → validate → rank
                                                                                           └─▶ clip rendering: ffmpeg (libx264/aac) → ffprobe → MEDIA_ROOT/clips/
```

- **Frontend** — Next.js App Router, TypeScript, Tailwind CSS. Talks to the API with `credentials: "include"`; asks `GET /auth/me` to learn who is signed in. No tokens in browser storage.
- **Backend** — FastAPI, SQLAlchemy 2 (sync), Alembic, psycopg 3. Argon2id password hashing; HS256 JWT delivered in an HttpOnly `SameSite=Lax` cookie; CORS limited to the frontend origin. Uploads are streamed to local storage and probed with ffprobe synchronously; transcription and clip detection run in a Celery worker over Redis, with the database as the source of truth for job state.
- **Database** — PostgreSQL. `users`, `projects`, `videos`, `transcriptions`, `transcript_segments`, `clip_detection_runs`, `clip_candidates` tables, UUID keys, timezone-aware timestamps.

Details: [docs/architecture.md](docs/architecture.md), [backend/README.md](backend/README.md), [frontend/README.md](frontend/README.md).

## Local development

### Prerequisites

- Node.js 20.9+
- Python 3.11+
- PostgreSQL 14+ — either Docker (`docker compose up -d`, which creates the `peaksift` and `peaksift_test` databases) or a local installation
- FFmpeg (`ffprobe` for metadata, `ffmpeg` for audio): `brew install ffmpeg` / `apt install ffmpeg`. Without it uploads end in status `failed` and transcription cannot run.
- Redis 7+ — Docker Compose (included) or `brew install redis && brew services start redis`. Broker for background jobs; the API starts without it, but starting a transcription or a clip detection answers `503` until it is reachable.
- Ollama (optional, for local AI clip detection): `brew install ollama`, `ollama serve`, `ollama pull llama3.2:3b`. Without it the local provider is listed as unavailable; the hosted OpenAI provider needs `OPENAI_API_KEY` instead.

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

### 3. Celery worker (transcription, clip detection, clip rendering)

In a second terminal, same virtualenv and directory:

```bash
cd backend && source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info
```

The default speech-to-text provider is faster-whisper on CPU (`FASTER_WHISPER_MODEL=small`, `int8`); the model (~460 MB) is downloaded on the first transcription, never at startup. On macOS, CPU mode is the supported path — there is no Apple-GPU acceleration in this stack. Set `FASTER_WHISPER_MODEL=tiny` to try the mechanics quickly, or `TRANSCRIPTION_PROVIDER=openai` with `OPENAI_API_KEY` for the hosted provider.

The same worker runs clip detection and clip rendering (CPU `libx264`; your FFmpeg must include the `libx264` and `aac` encoders, as Homebrew's and Ubuntu's builds do). For the local AI provider, start Ollama (`ollama serve`) and pull a model from `OLLAMA_CLIP_MODELS` (default `llama3.2:3b`); the worker never pulls or loads a model itself.

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
cd backend && python scripts/celery_smoke.py      # real worker round-trip over Redis + task registration
cd frontend && npm run lint && npm run build
```

Backend tests use a separate database (`TEST_DATABASE_URL`, default `peaksift_test`), a temporary media directory and Celery eager mode; they never touch your development data, never download a speech model (inference is mocked), never call OpenAI and never need Ollama (the provider is tested against a mocked transport and an in-process fake server). Media fixtures are generated with `ffmpeg` at test time; ffmpeg- and Redis-dependent tests skip when those are missing locally and are mandatory in CI. Opt-in real-model checks: `PEAKSIFT_REAL_WHISPER=1` and `PEAKSIFT_REAL_OLLAMA=1`.

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

## Clip detection flow

1. On a transcribed video, the **AI clip detection** panel lists the providers and models the server allows (`OLLAMA_CLIP_MODELS`, `OPENAI_CLIP_MODELS`) and says why one is unavailable. Click **Find clip moments**; the API records the run and queues it at once.
2. The worker prepares the transcript (normalised, validated, fingerprinted), splits it into bounded overlapping windows (default 5 minutes / 8000 characters), asks the model for candidates per window with a strict JSON schema, **validates every proposal** (snapped to transcript-line boundaries, inside the video, 15–90 s, whole-number scores 0–100, bounded texts — anything else is rejected, never clamped or invented), deduplicates overlaps and ranks by a documented weighted score, then stores the top 10 with the completed status in one transaction.
3. The page polls every 4 s through *Preparing transcript → Analyzing (window i of n) → Validating → Ranking*, then shows ranked cards with an in-page **Preview** of that range (the owner-only video stream), **Save** / **Dismiss**, filters and run history. Failed or stalled runs can be retried (bounded); re-transcribing flags older candidates as belonging to a previous transcript.

Scores are the model's editorial judgement normalised to 0–100 — not predictions of views. Full reference: [docs/clip-detection.md](docs/clip-detection.md).

## Clip generation flow

1. On a candidate card, click **Generate clip**. The API takes the candidate's persisted, validated boundaries (the browser sends no timestamps), re-checks them against the source, records one clip per candidate and queues the render at once; a repeat click returns the same clip.
2. The worker renders the range with FFmpeg — re-encoded (never stream-copied) with input seeking, so the clip starts at the requested frame — to H.264 + AAC in a fast-start MP4 at the source's resolution and orientation, writes it to a per-attempt temp file, validates it with ffprobe (codec, size, duration within 1 s, audio iff the source has audio), renames it atomically to `clips/<id>/clip.mp4` and only then marks the clip `ready`.
3. The card polls every 4 s through *Queued → Rendering → Validating*, then shows the **Rendered clip** player (owner-only Range stream) and **Download MP4** (attachment with a safe filename). Failed or stalled renders show a safe message and **Retry render**.

Full reference: [docs/clip-generation.md](docs/clip-generation.md).

## Security model (high level)

- Every project, video, detection-run, candidate and clip endpoint is scoped to the signed-in owner; anything else is a `404`.
- Rendered clips are private: preview and download go through owner-checked endpoints; candidate titles only influence the sanitised download name, never a storage path.
- Users choose an AI provider and model only from server allow-lists; the Ollama endpoint and the OpenAI key are server configuration and never appear in responses, errors or the frontend. Model output is validated and bounded before anything is stored.
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
- Clip detection analyses windows sequentially and cuts them on time/character budgets, not topics; snapping is line-granular; deduplication is temporal only; small local models yield fewer usable candidates. The hosted provider sends transcript text to OpenAI.
- Clip generation keeps the original aspect ratio (no 9:16 reframing, captions, editor, trimming, music or sound effects), renders on the CPU with a fixed MP4/H.264/AAC profile, reports stage progress rather than frame progress, and has no clip deletion, retention or render cancellation. No publishing integrations.

## Routes

**Frontend:** `/`, `/login`, `/register`, `/dashboard`, `/projects`, `/projects/new`, `/projects/[id]`

**API:** `GET /health` · `POST /auth/register` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` · `GET /projects` · `POST /projects` · `GET /projects/{id}` · `POST /projects/{id}/videos` · `GET /projects/{id}/videos` · `GET /projects/{id}/videos/{video_id}` · `GET /videos/{video_id}/content` · `POST /projects/{id}/videos/{video_id}/transcription` · `GET …/transcription` · `POST …/transcription/retry` · `GET …/transcript` · `GET /clip-detection/providers` · `POST /projects/{id}/videos/{video_id}/clip-detection` · `GET …/clip-detection` · `GET …/clip-detection/{run_id}` · `POST …/clip-detection/{run_id}/retry` · `GET …/clip-detection/{run_id}/candidates` · `GET …/candidates/{candidate_id}` · `POST …/candidates/{candidate_id}/save|dismiss|reset` · `POST …/candidates/{candidate_id}/clip` · `GET …/candidates/{candidate_id}/clip` · `POST …/candidates/{candidate_id}/clip/retry` · `GET /projects/{id}/videos/{video_id}/clips` · `GET /clips/{clip_id}/content` · `GET /clips/{clip_id}/download` — see [backend/README.md](backend/README.md#api).

## Continuous integration

Every push to `main` and every pull request runs [GitHub Actions](.github/workflows/ci.yml): the frontend job runs `npm ci`, lint and build; the backend job installs FFmpeg, runs Ruff, applies and checks the Alembic migrations against a PostgreSQL service container, runs the test suite — including the real-ffmpeg/ffprobe media tests (fixtures generated at test time), audio extraction, chunking and timestamp shifting with synthetic clips, Celery in eager mode, and a live-Redis connection check against a Redis service container — clip detection end-to-end with a fake provider and the real Ollama provider against an in-process fake server, real FFmpeg clip renders end-to-end through the API with Range delivery and download — after checking that FFmpeg provides the `libx264` and `aac` encoders, and finally a tiny real worker smoke (`scripts/celery_smoke.py`: start a worker, round-trip `ping`, verify the transcription, clip detection and clip rendering tasks are registered, stop). Speech-model inference is mocked and `HF_HUB_OFFLINE=1` guarantees CI never downloads a model; `OLLAMA_BASE_URL` points at a closed port so no real inference can happen; there is no OpenAI key in CI. CI validates only — nothing is deployed.

Development happens on feature branches merged through pull requests; see [CLAUDE.md](CLAUDE.md#git-workflow).

## Localization: Global + Morocco Mode (future)

PeakSift will ship a **Global** experience available to everyone.

**Morocco Mode** is a planned future localization layer that *extends* the Global experience — users keep every Global tool and library, plus Darija-aware analysis, Moroccan cultural context, local sound effects and creator assets, and Morocco-specific clip suggestions. It is not a separate app, and **it is not implemented**.

## Repository structure

```
PeakSift-AI/
├── frontend/             # Next.js app — see frontend/README.md
├── backend/              # FastAPI service — see backend/README.md
├── docs/                 # Architecture, milestones, clip detection and clip generation references
├── docker/               # PostgreSQL init script for Docker Compose
├── docker-compose.yml    # Local PostgreSQL
└── .github/workflows/    # CI
```
