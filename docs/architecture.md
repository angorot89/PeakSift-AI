# Architecture

Two sections: what is **built** (Milestones 1–2) and what is **planned**. Planned parts are decided milestone by milestone and may change.

## Built (Milestones 1–2)

```
┌───────────────────┐   HTTP/JSON + HttpOnly cookie   ┌───────────────────┐        ┌────────────┐
│  Next.js frontend │ ──────────────────────────────▶ │  FastAPI backend  │ ─────▶ │ PostgreSQL │
│  (App Router)     │ ◀────────────────────────────── │  SQLAlchemy 2     │        │ users,     │
│  <video> preview  │ ◀── Range-streamed bytes ────── │  Alembic          │        │ projects,  │
└───────────────────┘                                 │  ffprobe          │        │ videos     │
                                                      └────────┬──────────┘        └────────────┘
                                                               ▼
                                                      ┌───────────────────┐
                                                      │ MEDIA_ROOT (local │
                                                      │ files, dev only)  │
                                                      └───────────────────┘
```

### Frontend (`frontend/`)

- Next.js App Router, TypeScript, Tailwind CSS.
- Pages: landing (`/`), `/login`, `/register`, and a signed-in area (`/dashboard`, `/projects`, `/projects/new`, `/projects/[id]`) under one route group that wraps pages in a client-side guard and an app shell.
- Auth state lives in a small React context (`AuthProvider`). On load it calls `GET /auth/me`; the backend is the authority. Tokens are never stored in JavaScript-accessible storage.
- A single fetch wrapper (`lib/api.ts`) adds the API base URL (`NEXT_PUBLIC_API_URL`), sends cookies, and turns error bodies into messages. Uploads use a small `XMLHttpRequest` helper (`lib/videos.ts`) because `fetch` cannot report upload progress.
- The project page's **Source video** section uploads a file, shows the metadata the API returns (only fields that exist), and renders a native `<video controls>` for ready videos.

### Backend (`backend/`)

- FastAPI with routers for `health`, `auth`, `projects`, `videos` (upload + metadata) and `video_content` (streaming); request/response schemas (Pydantic) are separate from ORM models.
- Settings from environment variables via pydantic-settings; `DATABASE_URL` and `SECRET_KEY` are required.
- SQLAlchemy 2 with a **synchronous** engine and one session per request (`get_db`). Async was deliberately not introduced.
- Alembic migrations are the only way the schema changes; `alembic check` runs in CI to catch model/migration drift.
- Services: `storage.py` (local media files), `video_upload.py` (validation + storage), `ffprobe.py` (metadata), `video_processing.py` (status transitions).

### Video pipeline (Milestone 2)

```
POST /projects/{id}/videos
  → validate (filename sanitised, .mp4/.mov/.webm, plausible MIME, non-empty)
  → stream to MEDIA_ROOT/videos/<uuid>.<ext> in 1 MiB chunks, enforcing MAX_VIDEO_UPLOAD_BYTES
  → insert `videos` row (status uploaded)            — file deleted if this fails
  → ffprobe (argument list, JSON output, FFPROBE_TIMEOUT_SECONDS)
  → status ready + duration/width/height/fps/codecs, or status failed + safe error_message
  → response (same shape as GET /projects/{id}/videos/{video_id})
```

Probing is synchronous in Milestone 2; no queue or worker exists. The browser then fetches `GET /videos/{video_id}/content` (owner-only, HTTP `Range` support) for preview.

### Storage

- Development storage is the local filesystem under `MEDIA_ROOT` (default `backend/media`, git-ignored). Keys are application-generated (`videos/<uuid4>.<ext>`); the original filename is metadata only. `path_for` is the single chokepoint that proves a key resolves inside the root.
- Nothing under `MEDIA_ROOT` is served statically. Object storage (S3/R2) is planned and will implement the same `save / exists / delete / path_for` surface.

### Authentication

- Passwords: Argon2id (`pwdlib`). Never logged or returned.
- Session: HS256 JWT (`PyJWT`), `sub` = user UUID, with `iat`/`exp` (default 7 days).
- Transport: `HttpOnly`, `SameSite=Lax`, `Path=/` cookie; `Secure` in production. CORS allows only the configured frontend origin, with credentials. The `<video>` element relies on the frontend and API being same-site so the cookie accompanies media requests.
- Logout clears the cookie; there is no server-side revocation yet.
- Validation errors never echo submitted values; unhandled errors become a generic JSON 500 that still carries CORS headers.

### Data model

| Table      | Columns                                                                 |
| ---------- | ----------------------------------------------------------------------- |
| `users`    | `id` (uuid), `email` (unique, indexed), `password_hash`, `created_at`   |
| `projects` | `id` (uuid), `user_id` (FK → users, cascade delete), `name`, `status`, `created_at`, `updated_at` |
| `videos`   | `id` (uuid), `project_id` (FK → projects, cascade delete), `original_filename`, `storage_key` (unique), `content_type`, `file_size`, `duration_seconds`, `width`, `height`, `fps`, `video_codec`, `audio_codec`, `status`, `error_message`, `created_at`, `updated_at` |

Timestamps are timezone-aware. Project `status` is currently always `created`. Video `status` is `uploaded` → `processing_metadata` → `ready` | `failed`; the metadata columns stay empty until probing fills them. A project may own several videos at the database level; the UI surfaces the latest.

### Testing and CI

- Backend: pytest against a dedicated PostgreSQL test database; migrations are applied at the start of the session and every test is rolled back. Media tests use a throwaway `MEDIA_ROOT`; video fixtures are generated at test time with `ffmpeg` (none are committed). Integration tests skip locally without FFmpeg and are required in CI (`REQUIRE_FFMPEG=1`).
- Frontend: ESLint and a production build.
- GitHub Actions runs both on every push to `main` and every pull request; the backend job installs FFmpeg.

## Planned (later milestones)

```
Backend ──▶ Object storage (source videos, generated clips)
        ──▶ Background processing (transcription, clip detection, rendering)
```

1. **Transcription (Milestone 3)** — audio extracted with FFmpeg and transcribed with timestamps.
2. **Clip detection (Milestone 4)** — AI analyses the transcript (later other signals) to propose and score candidate moments.
3. **Clip generation (Milestone 5)** — FFmpeg cuts and reformats selected moments into vertical clips.
4. **Creator intelligence (Milestone 6)** — titles, hooks and metadata.

Long-running work will move outside the request cycle; the mechanism (and object storage) is chosen when first needed. None of this exists yet.

## Localization

The Global experience is the base. Morocco Mode, when built, extends it (additional analysis context and asset libraries) rather than forking it. No localization code exists yet.

## Principles

- Configuration and secrets via environment variables; only `.env.example` files are committed.
- Keep the system simple; add components only when a milestone requires them.
- The API is the security boundary; frontend route guards are a convenience.
- User-supplied names never become paths or command arguments.
