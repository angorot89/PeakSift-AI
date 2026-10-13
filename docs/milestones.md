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

## Milestone 4 — AI Clip Detection V0.4 *(complete)*

Delivered:

- `clip_detection_runs` and `clip_candidates` tables; many runs per video with history, at most one active; each run pins the transcript snapshot it analysed (id + sha256 fingerprint) and its configuration
- Swappable clip-analysis provider contract with one strict JSON schema and one prompt; local **Ollama** provider (operator-controlled endpoint and model allow-list) and hosted **OpenAI** provider (structured outputs); the user picks provider and model only from server allow-lists
- Transcript preparation: normalisation, timeline validation (never repaired), bounded overlapping analysis windows so multi-hour transcripts are many small requests
- Validation of every proposal (snap to transcript-line boundaries, inside the video, 15–90 s, whole-number scores 0–100, bounded texts; rejections counted, never clamped or invented), IoU deduplication, documented weighted ranking (0.30/0.25/0.15/0.15/0.15)
- Background pipeline on the existing Redis + Celery worker: idempotent on database state, task id committed before enqueue as a fencing token, bounded retries for transient provider errors, real staged progress, stale detection, one-transaction completion, honest time-limit failures
- API: providers (with live diagnostics), start / list / status / retry, paginated ranked candidates, candidate detail, save / dismiss / reset — owner-scoped, no internals exposed
- Frontend: provider/model choice, staged progress, failed/stalled states with bounded retry, run history, candidate cards with score breakdown and transcript excerpt, in-page preview of the candidate range from the original video, save/dismiss with filters
- Hardening, CI (fake provider end-to-end, real provider against an in-process fake Ollama, worker task registration, no models or keys) and documentation ([clip-detection.md](clip-detection.md))

Definition of done — a user can transcribe a video → choose a provider → start detection → watch queued/analyzing/ranking progress → receive ranked, explained candidates → preview each range → save or dismiss → log out and back in with the decisions kept → recover from a provider failure with retry.

## Milestone 5 — Clip Generation V0.5 *(complete)*

Delivered:

- `clips` table: one rendered clip per candidate (unique), boundary snapshot, render status `queued → rendering → validating → ready | failed`, render profile `source_mp4_v1`, validated output metadata
- Private clip storage under `MEDIA_ROOT/clips/<uuid>/` with per-attempt temp files and an atomic rename to `clip.mp4` after validation
- FFmpeg renderer: re-encoded with input seeking (frame-accurate start, never stream copy) to fast-start MP4, H.264 (libx264, yuv420p) + AAC when the source has audio, original resolution, aspect ratio and orientation; ffprobe validation of codec, size, duration and audio
- Background render pipeline on the existing Redis + Celery worker: idempotent on database state, pre-committed task id as fencing token checked on every commit, heartbeats and stale detection, honest stage progress, safe failure codes, bounded retry on the same clip
- API: generate (from the persisted candidate only; dismissed candidates must be restored), status, retry, per-video listing; private Range-streamed preview and attachment download with sanitised filenames — all owner-scoped
- Frontend: Generate clip on candidate cards, real render states, failure and stalled states with retry, rendered clip player, Download MP4, generated clips list
- Hardening (zombie-worker fencing, ready-but-missing reconciliation, FFmpeg kill on abnormal exit, path redaction in logs), CI (libx264/aac gate, real end-to-end renders) and documentation ([clip-generation.md](clip-generation.md))

Definition of done — a user can review a candidate → Generate clip → watch queued/rendering/validating → preview the rendered MP4 → download it → log out and back in with the clip still there → recover from a render failure with retry.

## Milestone 6 — Short-form Editing *(next — not started)*

- Vertical (9:16) layouts and reframing for generated clips
- Captions and caption styles
- Trimming and simple editing of generated clips

## Later

- Creator intelligence & metadata (titles, hooks, descriptions)
- Publishing integrations
- Sound effects and music
- Global asset libraries
- Morocco Mode (localization layer extending Global). Before any Moroccan accuracy claim, benchmark Darija, Arabic/French code-switching, Moroccan names, local slang and noisy streamer audio — none of that has been tested yet.
- Additional localization
