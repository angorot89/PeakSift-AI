# PeakSift AI

**Find the moments worth clipping.**

PeakSift AI is a short-form clipping and creation platform. Creators bring long-form content — videos, streams, podcasts, interviews, recordings — and PeakSift helps them find the strongest moments and turn them into short-form clips for TikTok, YouTube Shorts, and Instagram Reels.

## Current status

**Milestone 1 — Foundation V0.1** and **Milestone 2 — Video Upload V0.2** are complete. What exists today:

- A landing page.
- Email/password accounts: register, log in, log out, with an HttpOnly session cookie.
- Projects: create a project, list your projects, open a project.
- **Source video upload** on a project: MP4, MOV or WebM, with real upload progress.
- **Metadata extraction** with ffprobe: duration, resolution, frame rate, video/audio codecs — shown on the project page, or a clear failure state for unreadable files.
- **Owner-only preview** of the uploaded video with a native player (HTTP Range streaming).
- PostgreSQL schema (`users`, `projects`, `videos`) managed with Alembic migrations.
- Automated tests (backend 182), linting and CI with FFmpeg.

**Not built yet** (see [docs/milestones.md](docs/milestones.md)):

| Feature                                   | Milestone |
| ----------------------------------------- | --------- |
| Transcription                             | 3 (next)  |
| AI clip detection                         | 4         |
| Clip generation                           | 5         |
| Creator intelligence & metadata           | 6         |
| Editor, asset libraries, Morocco Mode     | later     |

The dashboard's Videos and Clips cards do not show counts yet because those features are not built.

## Architecture (as built)

```
Browser ──▶ Next.js frontend (:3000) ──fetch, cookie──▶ FastAPI backend (:8000) ──▶ PostgreSQL
                                                              │
                                                              ├──▶ MEDIA_ROOT (uploaded videos, local files)
                                                              └──▶ ffprobe (metadata)
```

- **Frontend** — Next.js App Router, TypeScript, Tailwind CSS. Talks to the API with `credentials: "include"`; asks `GET /auth/me` to learn who is signed in. No tokens in browser storage.
- **Backend** — FastAPI, SQLAlchemy 2 (sync), Alembic, psycopg 3. Argon2id password hashing; HS256 JWT delivered in an HttpOnly `SameSite=Lax` cookie; CORS limited to the frontend origin. Uploads are streamed to local storage and probed with ffprobe synchronously.
- **Database** — PostgreSQL. `users`, `projects`, `videos` tables, UUID keys, timezone-aware timestamps.

Details: [docs/architecture.md](docs/architecture.md), [backend/README.md](backend/README.md), [frontend/README.md](frontend/README.md).

## Local development

### Prerequisites

- Node.js 20.9+
- Python 3.11+
- PostgreSQL 14+ — either Docker (`docker compose up -d`, which creates the `peaksift` and `peaksift_test` databases) or a local installation
- FFmpeg (provides `ffprobe`; `brew install ffmpeg` / `apt install ffmpeg`). Without it the app runs, but every upload ends in status `failed`.

### 1. Database

```bash
docker compose up -d                 # or: createdb peaksift && createdb peaksift_test
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

Uploaded videos are written under `backend/media/` (`MEDIA_ROOT`), which is git-ignored.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:3000
```

Open **http://localhost:3000** (not `127.0.0.1`) so the auth cookie, CORS origin and video preview line up.

### Checks

```bash
cd backend && ruff check . && ruff format --check . && pytest
cd frontend && npm run lint && npm run build
```

Backend tests use a separate database (`TEST_DATABASE_URL`, default `peaksift_test`) and a temporary media directory; they never touch your development data. Video fixtures are generated with `ffmpeg` at test time — the ffprobe integration tests skip when FFmpeg is missing locally and are mandatory in CI.

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

## Security model (high level)

- Every project and video endpoint is scoped to the signed-in owner; anything else is a `404`.
- Browser-supplied filenames are metadata only. Files are stored under application-generated UUID keys, and the single path-resolution function refuses anything outside `MEDIA_ROOT`.
- Uploads are validated in layers (extension, MIME plausibility, size during streaming, then ffprobe proving the bytes are readable media). Oversized, empty or unreadable uploads leave no stray files.
- ffprobe is invoked with an argument list (no shell) and a timeout; its stderr is never stored or returned.
- Nothing in `MEDIA_ROOT` is served statically; the only way to read bytes is the authenticated, owner-only content endpoint.
- Error responses never include filesystem paths, storage keys or submitted values.

## Known limitations

- Local filesystem storage only; object storage (S3/R2) is a later milestone.
- Metadata probing runs inside the upload request (no background jobs yet); very large files make the upload response wait for ffprobe.
- The frontend does not know the size limit in advance; an oversized file is rejected by the API with a `413` message.
- Deleting is not implemented; replacing a video keeps the previous file and record.
- Transcription and AI clip detection do not exist yet — the UI says so.

## Routes

**Frontend:** `/`, `/login`, `/register`, `/dashboard`, `/projects`, `/projects/new`, `/projects/[id]`

**API:** `GET /health` · `POST /auth/register` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` · `GET /projects` · `POST /projects` · `GET /projects/{id}` · `POST /projects/{id}/videos` · `GET /projects/{id}/videos` · `GET /projects/{id}/videos/{video_id}` · `GET /videos/{video_id}/content` — see [backend/README.md](backend/README.md#api).

## Continuous integration

Every push to `main` and every pull request runs [GitHub Actions](.github/workflows/ci.yml): the frontend job runs `npm ci`, lint and build; the backend job installs FFmpeg, runs Ruff, applies and checks the Alembic migrations against a PostgreSQL service container, and runs the test suite including the real-ffprobe video tests (fixtures are generated with `ffmpeg` at test time; no media is stored in the repository). CI validates only — nothing is deployed.

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
