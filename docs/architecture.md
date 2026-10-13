# Architecture

Two sections: what is **built** (Milestones 1–6) and what is **planned**. Planned parts are decided milestone by milestone and may change.

## Built (Milestones 1–6)

```
┌───────────────────┐   HTTP/JSON + HttpOnly cookie   ┌───────────────────┐        ┌──────────────────┐
│  Next.js frontend │ ──────────────────────────────▶ │  FastAPI backend  │ ─────▶ │ PostgreSQL       │
│  (App Router)     │ ◀────────────────────────────── │  SQLAlchemy 2     │        │ users, projects, │
│  <video> preview  │ ◀── Range-streamed bytes ────── │  Alembic, ffprobe │        │ videos,          │
│  transcript view  │ ◀── polled status / pages ───── │                   │        │ transcriptions,  │
│  candidate cards  │ ◀── runs / candidates ───────── │                   │        │ transcript_segs, │
└───────────────────┘                                 └────────┬──────────┘        │ clip_detection_  │
                                                               │ enqueue id        │ runs, candidates │
                                                               ▼                   └────────▲─────────┘
                                                      ┌───────────────────┐                 │ status, rows
                                                      │ Redis (broker)    │ ─────▶ ┌────────┴─────────┐
                                                      └───────────────────┘        │ Celery worker    │
                                                                                   │ transcription:   │
                                                      ┌───────────────────┐        │  ffmpeg → chunks │
                                                      │ MEDIA_ROOT (local │ ◀────▶ │  → faster-whisper│
                                                      │ files, dev only)  │        │    | OpenAI      │
                                                      └───────────────────┘        │ clip detection:  │
                                                                                   │  windows → Ollama│
                                                      ┌───────────────────┐        │    | OpenAI      │
                                                      │ Ollama (optional, │ ◀────▶ │  → validate      │
                                                      │ local inference)  │        │  → rank          │
                                                      └───────────────────┘        │ clip render:     │
                                                                                   │  ffmpeg → clip   │
                                                                                   │ short-form edit: │
                                                                                   │  transcript→ASS  │
                                                                                   │  → ffmpeg 9:16   │
                                                                                   │    + libass      │
                                                                                   └──────────────────┘
```

### Frontend (`frontend/`)

- Next.js App Router, TypeScript, Tailwind CSS, `lucide-react` icons. A small design system lives in `app/globals.css` (surface/status/motion tokens) and `components/ui/` (Button, Panel, StatusPill, InlineAlert, EmptyState, Skeleton, ProgressBar/WorkingState, MediaFrame).
- Pages: landing (`/`), `/login`, `/register`, and a signed-in area (`/dashboard`, `/projects`, `/projects/new`, `/projects/[id]`) under one route group that wraps pages in a client-side guard and an app shell.
- Auth state lives in a small React context (`AuthProvider`). On load it calls `GET /auth/me`; the backend is the authority. Tokens are never stored in JavaScript-accessible storage.
- A single fetch wrapper (`lib/api.ts`) adds the API base URL (`NEXT_PUBLIC_API_URL`), sends cookies, and turns error bodies into messages. Uploads use a small `XMLHttpRequest` helper (`lib/videos.ts`) because `fetch` cannot report upload progress.
- The project page's **Source video** section uploads a file, shows the metadata the API returns (only fields that exist), and renders a native `<video controls>` for ready videos. For ready videos a **Transcription** panel starts the job, polls `GET …/transcription` every 4 s only while it is active, shows real progress, failure/stalled states with retry, and a paginated timestamped transcript viewer. Once the transcript is complete, an **AI clip detection** panel offers the server's provider/model allow-lists, starts a run, polls `GET …/clip-detection/{run_id}` every 4 s while active with staged progress, handles failed/stalled runs with bounded retry, lists previous runs, and renders the **candidate review** (ranked cards, score breakdown, transcript excerpt, in-page preview of the candidate range from the owner-only stream, save/dismiss with filters). The page is a workflow: a stepper (Upload, Transcribe, Find clips, Generate, Edit) fed by each section's real state, then numbered panels — Source video, Transcript, Clip moments (ranked candidate cards with a compact generated-clip block), Generated clips (thumbnails, short counts, links to the editor). The short-form editor is a separate page, `/projects/[id]/clips/[clipId]` (`components/app/short-editor-view.tsx`, `components/app/editor/*`): a 9:16 stage with a labelled approximate preview or the rendered MP4, visual settings, the render action with real states, and the versions list.

### Backend (`backend/`)

- FastAPI with routers for `health`, `auth`, `projects`, `videos` (upload + metadata), `video_content` (streaming), `transcriptions` (start/status/retry/transcript), `clip_detection` (providers, runs, candidates, decisions), `clips` (generate/status/retry/list), `clip_media` (private clip preview and download, sharing `media_streaming.py` with source preview), `clip_edits` (create/list/status/retry of short-form edits) and `edit_media` (private short preview and download); request/response schemas (Pydantic) are separate from ORM models.
- Settings from environment variables via pydantic-settings; `DATABASE_URL` and `SECRET_KEY` are required.
- SQLAlchemy 2 with a **synchronous** engine and one session per request (`get_db`). Async was deliberately not introduced.
- Alembic migrations are the only way the schema changes; `alembic check` runs in CI to catch model/migration drift.
- Services: `storage.py` (local media files), `video_upload.py` (validation + storage), `ffprobe.py` (metadata), `video_processing.py` (status transitions), `audio_extraction.py` (normalized audio), the `transcription/` package (provider contract, factory, chunking, pipeline, providers) and the `clip_detection/` package (provider contract + shared schema and prompt, factory with allow-lists, Ollama and OpenAI providers, windowing, validation, ranking, config snapshot, pipeline), `clip_render/` (clip artifacts, FFmpeg renderer, pipeline) and `clip_edit/` (edit config, 9:16 composition, captions, caption styles, edit artifacts, pipeline).
- Workers: `app/workers/celery_app.py` (Celery on Redis), `transcription_tasks.py`, `clip_detection_tasks.py`, `clip_render_tasks.py`, `clip_edit_tasks.py` and `dispatch.py` (enqueue helpers; every job's task id is chosen and committed on its row before enqueueing and serves as the attempt token); only database ids cross the broker.

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

### Clip detection pipeline (Milestone 4)

```
POST …/clip-detection {provider, model}  →  ClipDetectionRun row (queued, config snapshot, transcript fingerprint,
                                            pre-chosen Celery task id)  →  enqueue  →  201 at once
Worker:
  claim (DB state + fencing token)
  → preparing_transcript  normalise + validate lines, fingerprint must match the run           (progress 5)
  → analyzing             bounded overlapping windows → provider.analyze (strict JSON schema)
                          → validate each proposal against the window's transcript lines      (5 → 80)
  → validating            fingerprint re-checked (transcript unchanged)                        (85)
  → ranking               IoU deduplication, weighted overall score, deterministic order       (90)
  → completed             all candidate rows + status in one transaction                      (100)
  | failed                error_code + safe error_message, no candidates
```

- **Providers** implement `ClipAnalysisProvider` (`analyze(request) → raw candidates`, `check_availability()`) and share one prompt and one JSON schema. `ollama` talks to an operator-configured Ollama-compatible endpoint over `httpx` (`format` = schema, temperature 0); `openai` uses the SDK's structured outputs. The user picks provider and model **only** from `OLLAMA_CLIP_MODELS` / `OPENAI_CLIP_MODELS`; endpoints and keys never leave the server.
- **Trust boundary:** everything a model returns is *raw* until `validation.py` snaps it to transcript-line boundaries inside the window, shortens overlong clips to a line boundary, checks the video bounds, the 15–90 s duration, whole-number 0–100 scores and bounded texts, and attaches *our* transcript excerpt. Nothing is clamped or invented; failures are rejections. Ranking is `0.30·hook + 0.25·entertainment + 0.15·clarity + 0.15·payoff + 0.15·completeness` with duplicate (IoU > 0.5) removal and a total deterministic order.
- **Reliability:** same model as transcription — idempotent on database state, fencing token re-read before every commit (committed on the row before enqueue), bounded exponential backoff for transient provider errors only, heartbeat-based staleness (`CLIP_DETECTION_STALE_AFTER_SECONDS`), one-transaction completion so a run is never `completed` with a partial set, honest `time_limit` failures, bounded user retries (`CLIP_DETECTION_MAX_ATTEMPTS`), one active run per video (query + partial unique index).
- **Transcript snapshot:** each run stores the sha256 fingerprint of the transcript lines it analysed; a re-generated transcript makes old runs report `transcript_current: false` and blocks their retry — candidates always trace to the exact transcript that produced them.

Full reference: [clip-detection.md](clip-detection.md).

### Clip generation pipeline (Milestone 5)

```
POST …/candidates/{id}/clip  →  re-validate the candidate's [start, end] against the source
                             →  Clip row (queued, boundary snapshot, render_profile source_mp4_v1,
                                pre-chosen task id; unique per candidate)  →  enqueue  →  201 / 200 if it exists
Worker (app/services/clip_render/):
  claim (DB state + fencing token), discard stale/orphaned artifacts
  → rendering    ffmpeg -ss <start> -i <source> -t <duration> → libx264/yuv420p + aac, +faststart
                 into clips/<id>/clip-tmp-<attempt>.mp4, heartbeat while running              (10)
  →              ffprobe validation: h264, size, duration ±1 s, audio iff source has audio   (80)
  → validating   ownership re-checked                                                         (90)
  → atomic rename to clips/<id>/clip.mp4, then one commit: storage_key + metadata + ready     (100)
  | failed       safe error_code/message, all artifacts removed
GET /clips/{id}/content | /download  →  owner check → path_for(storage_key) → Range stream
```

- **Accuracy:** re-encoding with input seeking (never `-c copy`), so the first frame is the first one at or after the candidate start; the output keeps the source's resolution, aspect ratio and (decoded) orientation, rounding odd sizes to even for `yuv420p`.
- **Consistency:** file first, row second — `ready` always means a validated file exists at `storage_key`; a `ready` row whose file vanished is reconciled to `failed`/`artifact_missing` and becomes retryable.
- **Fencing:** every pipeline commit re-reads the task id; a worker taken over by a retry stops at its next heartbeat (FFmpeg killed), never writes the row and only deletes its own per-attempt temp file.
- **Delivery:** one shared Range implementation for source and clip media (200/206/416, chunked reads, `private, no-store`), downloads as attachments with a sanitised title slug.

Full reference: [clip-generation.md](clip-generation.md).

### Short-form editing pipeline (Milestone 6)

```
POST …/clips/{id}/edits {layout, captions…}  →  allow-listed enums → normalized config snapshot + fingerprint
                             →  same fingerprint exists? 200 (failed: 409, use retry)
                             →  ClipEdit row (queued, render_profile vertical_1080x1920_v1, pre-chosen task id)
                             →  enqueue peaksift.render_clip_edit  →  201
Worker (app/services/clip_edit/):
  claim (DB state + attempt token), discard leftovers                                   (5)
  → captions   transcript segments → clip-local cues → escaped ASS in edits/<id>/work-<n>/  (15)
  → rendering  ffmpeg (cwd = workspace): layout filtergraph [+ subtitles=captions.ass]
               → libx264/yuv420p + aac, +faststart, 1080×1920, heartbeat                  (85)
  → validating ffprobe: h264, 1080×1920, fps, duration vs clip, audio iff source         (90)
  → atomic rename to edits/<id>/edited.mp4, then one commit: storage_key + metadata + ready (100)
  | failed      safe error_code/message, all of the edit's files removed
GET /edits/{id}/content | /download  →  owner check → path_for(storage_key) → Range stream
```

- **Derived, never destructive:** the V0.5 clip file is the read-only input; every edit is its own row and file.
- **Untrusted text:** transcript text only reaches the ASS file through escaping (word joiner after backslashes, escaped braces); filtergraphs come from constants; the caption file is a fixed relative name, so no path enters a filtergraph.
- **Ownership:** the same attempt-token fencing as clip rendering, plus per-attempt workspaces; a row deleted mid-render makes the worker stop without writing. Retry locks the row.
- **Renderer checks:** libass presence (`subtitles` filter) and a probe caption that must draw text pixels (fonts) before a captioned render.

Full reference: [short-form-editing.md](short-form-editing.md).

### Storage

- Development storage is the local filesystem under `MEDIA_ROOT` (default `backend/media`, git-ignored). Keys are application-generated (`videos/<uuid4>.<ext>`, `transcription/<id>/normalized.mp3`, `transcription/<id>/chunks/NNNN.mp3`, `clips/<clip-uuid>/clip-tmp-<attempt>.mp4` → `clips/<clip-uuid>/clip.mp4`, `edits/<edit-uuid>/work-<attempt>/{captions.ass,short.mp4}` → `edits/<edit-uuid>/edited.mp4`); the original filename is metadata only. `path_for` is the single chokepoint that proves a key resolves inside the root.
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
| `clip_detection_runs` | `id` (uuid), `video_id` (FK → videos, cascade), `transcription_id` (FK → transcriptions, cascade), `transcript_fingerprint` (sha256), `provider`, `model`, `config` (JSONB snapshot), `status`, `progress_percent` (0–100), `attempt` (≥ 1), `windows_total`, `windows_done`, `error_code`, `error_message`, `celery_task_id`, `created_at`, `updated_at`, `started_at`, `completed_at`, `heartbeat_at`. Partial unique index on `video_id` where status is active (one running detection per video) |
| `clip_candidates` | `id` (uuid), `run_id` (FK → clip_detection_runs, cascade), `video_id` (FK → videos, cascade), `start_time`, `end_time`, `duration_seconds` (checked = end − start), `title` (120), `hook` (300), `rationale` (1000), `category`, `transcript_excerpt`, `overall_score` + five dimension scores (each checked 0–100), `rank` (≥ 1, unique per run), `decision` (`undecided`/`saved`/`dismissed`), `decided_at`, `created_at`, `updated_at`; index on `(video_id, decision)` |
| `clips` | `id` (uuid), `candidate_id` (FK → clip_candidates, cascade, **unique**), `video_id` (FK → videos, cascade), `status`, `progress_percent` (0–100), `attempt` (≥ 1), `start_time`, `end_time`, `duration_seconds` (snapshot; checked start ≥ 0, end > start, duration = end − start), `render_profile`, `storage_key` (unique, internal), `content_type`, `file_size`, `width`, `height`, `fps`, `video_codec`, `audio_codec`, `error_code`, `error_message`, `celery_task_id` (internal), `created_at`, `updated_at`, `started_at`, `completed_at`, `heartbeat_at` |
| `clip_edits` | `id` (uuid), `clip_id` (FK → clips, cascade), `video_id` (FK → videos, cascade), `status`, `progress_percent` (0–100), `attempt` (≥ 1), `config` (JSONB, versioned snapshot), `config_fingerprint` (sha256; **unique with `clip_id`**), `aspect_ratio` (`9:16`), `layout` (`center_crop`/`blur_background`/`fit`), `captions_enabled`, `caption_style`, `caption_position` (both set iff captions are enabled — checked), `output_width`/`output_height` (1080 × 1920), `render_profile`, `storage_key` (unique, internal), `content_type`, `file_size`, `duration_seconds`, `width`, `height`, `fps`, `video_codec`, `audio_codec`, `caption_cue_count`, `error_code`, `error_message`, `celery_task_id` (internal), `created_at`, `updated_at`, `started_at`, `completed_at`, `heartbeat_at` |

Timestamps are timezone-aware. Project `status` is currently always `created`. Video `status` is `uploaded` → `processing_metadata` → `ready` | `failed`; the metadata columns stay empty until probing fills them. A project may own several videos at the database level; the UI surfaces the latest. Transcription `status` is a separate state machine — `queued` → `extracting_audio` → `transcribing` → `completed` | `failed` — answering "what is happening to the speech-to-text job", while video status answers "is this media usable". Segment times are absolute seconds from the start of the video (floats, like the video's `duration_seconds`). Clip detection `status` is a third state machine — `queued` → `preparing_transcript` → `analyzing` → `validating` → `ranking` → `completed` | `failed` — and candidate times are absolute seconds on transcript-line boundaries; scores are integers on one 0–100 editorial scale. Clip `status` is a fourth — `queued` → `rendering` → `validating` → `ready` | `failed` — describing the health of the rendered artifact; each clip edit has the same lifecycle for its own short.

### Testing and CI

- Backend: pytest against a dedicated PostgreSQL test database; migrations are applied at the start of the session and every test is rolled back. Media tests use a throwaway `MEDIA_ROOT`; fixtures are generated at test time with `ffmpeg` (none are committed). Celery runs in eager mode; speech models are mocked (an opt-in real `tiny`-model check exists for macOS); clip-analysis providers are tested with a mocked transport / fake SDK client plus an in-process fake Ollama HTTP server (an opt-in real check runs against a local Ollama with `PEAKSIFT_REAL_OLLAMA=1`). Integration tests skip locally without FFmpeg/Redis and are required in CI (`REQUIRE_FFMPEG=1`, `REQUIRE_REDIS=1`, `HF_HUB_OFFLINE=1`, `OLLAMA_BASE_URL` on a closed port).
- Frontend: ESLint and a production build.
- GitHub Actions runs both on every push to `main` and every pull request; the backend job installs FFmpeg, runs PostgreSQL and Redis service containers, installs the Noto fonts, checks that FFmpeg provides `libx264`, `aac`, libass and the layout filters, that fontconfig resolves the caption fonts and that a probe caption draws text, runs real clip renders end-to-end through the API and real captioned 9:16 renders verified on frame pixels (`REQUIRE_LIBASS=1`), and finishes with a real worker smoke (`ping` round-trip and registration of the transcription, clip detection, clip rendering and short-form edit tasks).

## Planned (later milestones)

```
Backend ──▶ Object storage (source videos, generated clips, edited shorts)
```

No milestone after V0.6 has been defined. Possible later work — creator intelligence and metadata, publishing, asset libraries, object storage replacing `MEDIA_ROOT` when deployment requires it — is not committed scope, and none of it exists yet.

## Localization

The Global experience is the base. Morocco Mode, when built, extends it (additional analysis context and asset libraries) rather than forking it. No localization code exists yet.

## Principles

- Configuration and secrets via environment variables; only `.env.example` files are committed.
- Keep the system simple; add components only when a milestone requires them.
- The API is the security boundary; frontend route guards are a convenience.
- User-supplied names never become paths or command arguments.
