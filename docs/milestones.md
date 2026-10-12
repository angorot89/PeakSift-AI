# Milestones

## Milestone 1 — Foundation V0.1 *(complete)*

Delivered:

- Repository structure and documentation
- Next.js frontend with a landing page
- FastAPI backend with `GET /health`
- PostgreSQL + SQLAlchemy 2 + Alembic; `users` and `projects` tables
- Email/password authentication (Argon2id, JWT in an HttpOnly cookie)
- Project API: create, list, detail (owner-scoped)
- Frontend: login, register, dashboard, projects list/new/detail, protected routes
- Backend tests, Ruff, ESLint, production build, GitHub Actions CI

Definition of done — a user can register → log in → open the dashboard → create a project → view their projects → open a project → log out → log in again, with data persisted.

## Milestone 2 — Video Upload V0.2 *(complete)*

Delivered:

- `videos` table and `Video` model (status `uploaded` → `processing_metadata` → `ready` | `failed`)
- Secure local media storage (`MEDIA_ROOT`): generated UUID keys, chunked writes, no path escapes, nothing committed
- `POST /projects/{id}/videos`: authenticated, owner-only upload of MP4/MOV/WebM, streamed with a configurable size limit, layered validation, cleanup on failure
- ffprobe metadata extraction (duration, resolution, frame rate, codecs) with a timeout and safe error messages
- `GET /projects/{id}/videos`, `GET /projects/{id}/videos/{video_id}`: owner-scoped metadata
- `GET /videos/{video_id}/content`: owner-only streaming with HTTP Range support
- Frontend: drag-and-drop/file-picker upload with real progress, metadata display, failure state, native `<video>` preview
- Hardening pass (CORS-aware 500s, interrupted/chunked uploads, fd cleanup) and CI with FFmpeg

Definition of done — a user can open a project → upload a source video → see real ffprobe metadata → preview the video → log out and back in with the video still there.

## Milestone 3 — Transcription V0.3 *(complete)*

Delivered:

- `transcriptions` and `transcript_segments` tables; one current transcription per video; status `queued` → `extracting_audio` → `transcribing` → `completed` | `failed`
- Normalized audio extraction (ffmpeg → mono 16 kHz 64 kbps MP3) with timeout, validation and cleanup
- Redis + Celery background jobs (`acks_late`, one job per worker, visibility timeout above the hard limit, eager mode for tests)
- Provider contract with explicit capabilities and a hard timestamp rule (segment timestamps required, never fabricated)
- faster-whisper local provider (lazy, per-process model cache, CPU on macOS; audio decoded with ffmpeg) and OpenAI hosted provider (`whisper-1` + `verbose_json` for timestamps; text-only GPT-4o models refused for timing)
- Long-audio chunking (default 10 min) with absolute-timestamp shifting and cleanup
- Pipeline: idempotent on database state, fencing token against concurrent runs, bounded retries for transient provider errors only, real progress and heartbeats, stale-job detection, safe failure recording
- API: start / status / retry / paginated transcript, owner-scoped
- Frontend: Transcribe button, honest polled status, failure and stalled states with retry, timestamped transcript viewer with Load more and Copy
- Hardening and CI (Redis service, real worker smoke, no model downloads, no API keys)

Definition of done — a user can start a transcription on a ready video → see it queued, prepared and transcribed in the background → read the timestamped transcript → retry a failed job → log out and back in with the transcript still there.

## Milestone 4 — AI Clip Detection V0.4 *(next — not started)*

- Timestamped transcript → candidate moments
- AI scoring/ranking of candidates

## Milestone 5 — Clip Generation V0.5

- Cut selected moments into short-form vertical clips

## Milestone 6 — Creator Intelligence & Metadata

- Titles, hooks, descriptions, and other metadata for generated clips

## Later

- Clip editor (captions, hooks, sound effects)
- Global asset libraries
- Morocco Mode (localization layer extending Global). Before any Moroccan accuracy claim, benchmark Darija, Arabic/French code-switching, Moroccan names, local slang and noisy streamer audio — none of that has been tested yet.
- Additional localization
