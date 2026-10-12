# Architecture

Two sections: what is **built** (Milestones 1–3) and what is **planned**. Planned parts are decided milestone by milestone and may change.

## Built (Milestones 1–3)

```
┌───────────────────┐   HTTP/JSON + HttpOnly cookie   ┌───────────────────┐        ┌──────────────────┐
│  Next.js frontend │ ──────────────────────────────▶ │  FastAPI backend  │ ─────▶ │ PostgreSQL       │
│  (App Router)     │ ◀────────────────────────────── │  SQLAlchemy 2     │        │ users, projects, │
│  <video> preview  │ ◀── Range-streamed bytes ────── │  Alembic, ffprobe │        │ videos,          │
│  transcript view  │ ◀── polled status / pages ───── │                   │        │ transcriptions,  │
└───────────────────┘                                 └────────┬──────────┘        │ transcript_segs  │
                                                               │ enqueue id        └────────▲─────────┘
                                                               ▼                            │ status, segments
                                                      ┌───────────────────┐        ┌────────┴─────────┐
                                                      │ Redis (broker)    │ ─────▶ │ Celery worker    │
                                                      └───────────────────┘        │ ffmpeg → chunks  │
                                                                                   │ → provider       │
                                                      ┌───────────────────┐        │ (faster-whisper  │
                                                      │ MEDIA_ROOT (local │ ◀────▶ │  or OpenAI)      │
                                                      │ files, dev only)  │        └──────────────────┘
                                                      └───────────────────┘
```

### Frontend (`frontend/`)

- Next.js App Router, TypeScript, Tailwind CSS.
- Pages: landing (`/`), `/login`, `/register`, and a signed-in area (`/dashboard`, `/projects`, `/projects/new`, `/projects/[id]`) under one route group that wraps pages in a client-side guard and an app shell.
- Auth state lives in a small React context (`AuthProvider`). On load it calls `GET /auth/me`; the backend is the authority. Tokens are never stored in JavaScript-accessible storage.
- A single fetch wrapper (`lib/api.ts`) adds the API base URL (`NEXT_PUBLIC_API_URL`), sends cookies, and turns error bodies into messages. Uploads use a small `XMLHttpRequest` helper (`lib/videos.ts`) because `fetch` cannot report upload progress.
- The project page's **Source video** section uploads a file, shows the metadata the API returns (only fields that exist), and renders a native `<video controls>` for ready videos. For ready videos a **Transcription** panel starts the job, polls `GET …/transcription` every 4 s only while it is active, shows real progress, failure/stalled states with retry, and a paginated timestamped transcript viewer.

### Backend (`backend/`)

- FastAPI with routers for `health`, `auth`, `projects`, `videos` (upload + metadata), `video_content` (streaming) and `transcriptions` (start/status/retry/transcript); request/response schemas (Pydantic) are separate from ORM models.
- Settings from environment variables via pydantic-settings; `DATABASE_URL` and `SECRET_KEY` are required.
- SQLAlchemy 2 with a **synchronous** engine and one session per request (`get_db`). Async was deliberately not introduced.
- Alembic migrations are the only way the schema changes; `alembic check` runs in CI to catch model/migration drift.
- Services: `storage.py` (local media files), `video_upload.py` (validation + storage), `ffprobe.py` (metadata), `video_processing.py` (status transitions), `audio_extraction.py` (normalized audio), and the `transcription/` package (provider contract, factory, chunking, pipeline, providers).
- Workers: `app/workers/celery_app.py` (Celery on Redis) and `transcription_tasks.py`; only database ids cross the broker.

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

### Transcription pipeline (Milestone 3)

```
POST …/transcription  →  Transcription row (queued)  →  Celery task id stored  →  202-style quick return
Worker:
  claim (DB state + fencing token)
  → extract normalized audio   transcription/<id>/normalized.mp3   (progress 5)
  → split into 10-minute chunks  transcription/<id>/chunks/NNNN.mp3
  → per chunk: provider.transcribe → validate → shift to absolute time → commit segments, progress, heartbeat
  → completed (full_text, progress 100)   |   failed (error_code, safe error_message, no partial segments)
  → chunk files removed; normalized audio kept for retries
```

- **Providers** implement one contract (`ProviderTranscriptionResult` with ordered `ProviderSegment`s) and declare capabilities. The factory refuses any provider without segment timestamps. `faster_whisper` (default, local, lazy-loaded and cached per worker process; audio decoded with ffmpeg) and `openai` (hosted; `whisper-1` + `verbose_json` for structured timestamps — the GPT-4o transcription models are text-only in the installed SDK and are refused as the timestamp model). Timestamps are never fabricated.
- **Reliability:** idempotent on database state (completed/live/stale/failed rules), a Celery task id as fencing token re-checked before every commit, bounded exponential backoff for transient provider errors only, heartbeat-based stale detection surfaced as `is_stale` and retryable from the API/UI, Celery `acks_late` + prefetch 1 with the Redis visibility timeout above the hard time limit.
- **Status** is a separate state machine from the video's (`queued` → `extracting_audio` → `transcribing` → `completed` | `failed`); the frontend polls, no WebSockets.

### Storage

- Development storage is the local filesystem under `MEDIA_ROOT` (default `backend/media`, git-ignored). Keys are application-generated (`videos/<uuid4>.<ext>`, `transcription/<id>/normalized.mp3`, `transcription/<id>/chunks/NNNN.mp3`); the original filename is metadata only. `path_for` is the single chokepoint that proves a key resolves inside the root.
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

| `transcriptions` | `id` (uuid), `video_id` (FK → videos, cascade delete, **unique** — one current transcription per video), `status`, `provider`, `model`, `language`, `language_probability`, `progress_percent` (0–100, checked), `full_text`, `error_code`, `error_message`, `celery_task_id`, `audio_storage_key`, `audio_duration_seconds`, `created_at`, `updated_at`, `started_at`, `completed_at`, `heartbeat_at` |
| `transcript_segments` | `id` (uuid), `transcription_id` (FK → transcriptions, cascade delete), `sequence_index`, `start_time`, `end_time`, `text`, `speaker` (nullable, reserved), `created_at`. Constraints: `start_time >= 0`, `end_time > start_time`, unique `(transcription_id, sequence_index)`; index on `(transcription_id, start_time)` |

Timestamps are timezone-aware. Project `status` is currently always `created`. Video `status` is `uploaded` → `processing_metadata` → `ready` | `failed`; the metadata columns stay empty until probing fills them. A project may own several videos at the database level; the UI surfaces the latest. Transcription `status` is a separate state machine — `queued` → `extracting_audio` → `transcribing` → `completed` | `failed` — answering "what is happening to the speech-to-text job", while video status answers "is this media usable". Segment times are absolute seconds from the start of the video (floats, like the video's `duration_seconds`).

### Testing and CI

- Backend: pytest against a dedicated PostgreSQL test database; migrations are applied at the start of the session and every test is rolled back. Media tests use a throwaway `MEDIA_ROOT`; fixtures are generated at test time with `ffmpeg` (none are committed). Celery runs in eager mode; speech models are mocked (an opt-in real `tiny`-model check exists for macOS). Integration tests skip locally without FFmpeg/Redis and are required in CI (`REQUIRE_FFMPEG=1`, `REQUIRE_REDIS=1`, `HF_HUB_OFFLINE=1`).
- Frontend: ESLint and a production build.
- GitHub Actions runs both on every push to `main` and every pull request; the backend job installs FFmpeg, runs PostgreSQL and Redis service containers, and finishes with a real worker `ping` smoke.

## Planned (later milestones)

```
Backend ──▶ Object storage (source videos, generated clips)
        ──▶ Background processing (transcription, clip detection, rendering)
```

1. **Clip detection (Milestone 4)** — the timestamped transcript (and later other signals) is analysed to propose and score candidate moments.
2. **Clip generation (Milestone 5)** — FFmpeg cuts and reformats selected moments into vertical clips.
3. **Creator intelligence (Milestone 6)** — titles, hooks and metadata.

Object storage replaces `MEDIA_ROOT` when deployment requires it. None of this exists yet.

## Localization

The Global experience is the base. Morocco Mode, when built, extends it (additional analysis context and asset libraries) rather than forking it. No localization code exists yet.

## Principles

- Configuration and secrets via environment variables; only `.env.example` files are committed.
- Keep the system simple; add components only when a milestone requires them.
- The API is the security boundary; frontend route guards are a convenience.
- User-supplied names never become paths or command arguments.
