# PeakSift AI

**Find the moments worth clipping.**

PeakSift AI is a short-form clipping and creation platform. Creators bring long-form content — videos, streams, podcasts, interviews, recordings — and PeakSift helps them find the strongest moments and turn them into short-form clips for TikTok, YouTube Shorts, and Instagram Reels.

## Current status

**Milestone 1 — Foundation V0.1** is complete. What exists today:

- A landing page.
- Email/password accounts: register, log in, log out, with an HttpOnly session cookie.
- Projects: create a project, list your projects, open a project. A project is just a name and a status for now.
- A dashboard showing your real project count and recent projects.
- PostgreSQL schema (`users`, `projects`) managed with Alembic migrations.
- Automated tests, linting and CI.

**Not built yet** (see [docs/milestones.md](docs/milestones.md)):

| Feature                                   | Milestone |
| ----------------------------------------- | --------- |
| Video upload                              | 2         |
| Transcription                             | 3         |
| AI clip detection                         | 4         |
| Clip generation                           | 5         |
| Creator intelligence & metadata           | 6         |
| Editor, asset libraries, Morocco Mode     | later     |

The dashboard shows `0` for videos and clips because those features do not exist yet.

## Architecture (as built)

```
Browser ──▶ Next.js frontend (:3000) ──fetch, cookie──▶ FastAPI backend (:8000) ──▶ PostgreSQL
```

- **Frontend** — Next.js App Router, TypeScript, Tailwind CSS. Talks to the API with `credentials: "include"`; asks `GET /auth/me` to learn who is signed in. No tokens in browser storage.
- **Backend** — FastAPI, SQLAlchemy 2 (sync), Alembic, psycopg 3. Argon2id password hashing; HS256 JWT delivered in an HttpOnly `SameSite=Lax` cookie; CORS limited to the frontend origin.
- **Database** — PostgreSQL. `users` and `projects` tables, UUID keys, timezone-aware timestamps.

Details: [docs/architecture.md](docs/architecture.md), [backend/README.md](backend/README.md), [frontend/README.md](frontend/README.md).

## Local development

### Prerequisites

- Node.js 20.9+
- Python 3.11+
- PostgreSQL 14+ — either Docker (`docker compose up -d`, which creates the `peaksift` and `peaksift_test` databases) or a local installation

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

### 3. Frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:3000
```

Open **http://localhost:3000** (not `127.0.0.1`) so the auth cookie and CORS origin line up.

### Checks

```bash
cd backend && ruff check . && ruff format --check . && pytest
cd frontend && npm run lint && npm run build
```

Backend tests use a separate database (`TEST_DATABASE_URL`, default `peaksift_test`) and never touch your development data.

## Routes

**Frontend:** `/`, `/login`, `/register`, `/dashboard`, `/projects`, `/projects/new`, `/projects/[id]`

**API:** `GET /health` · `POST /auth/register` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` · `GET /projects` · `POST /projects` · `GET /projects/{id}` — see [backend/README.md](backend/README.md#api).

## Continuous integration

Every push to `main` and every pull request runs [GitHub Actions](.github/workflows/ci.yml): the frontend job runs `npm ci`, lint and build; the backend job installs FFmpeg, runs Ruff, applies and checks the Alembic migrations against a PostgreSQL service container, and runs the test suite including the real-ffprobe video tests (fixtures are generated with `ffmpeg` at test time; no media is stored in the repository). CI validates only — nothing is deployed.

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
