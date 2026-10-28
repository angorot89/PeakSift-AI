# Architecture

Two sections: what is **built** (Milestones 1–7) and what is **planned**. Planned parts are decided milestone by milestone and may change.

## Built (Milestones 1–7)

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
                                                      │ media storage     │ ◀────▶ │  → faster-whisper│
                                                      │ (local or S3)     │        │    | OpenAI      │
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
                                                                                   │ smart reframe:   │
                                                                                   │  frames → faces  │
                                                                                   │  → tracks → path │
                                                                                   └──────────────────┘
```

### Frontend (`frontend/`)

- Next.js App Router, TypeScript, Tailwind CSS, `lucide-react` icons. A small design system lives in `app/globals.css` (surface/status/motion tokens) and `components/ui/` (Button, Panel, StatusPill, InlineAlert, EmptyState, Skeleton, ProgressBar/WorkingState, MediaFrame).
- Pages: landing (`/`), `/login`, `/register`, and a signed-in area (`/dashboard`, `/projects`, `/projects/new`, `/projects/[id]`) under one route group that wraps pages in a client-side guard and an app shell.
- Auth state lives in a small React context (`AuthProvider`). On load it calls `GET /auth/session` (the user or `null`, always 200, so a signed-out visit logs no failed request); the backend is the authority. Tokens are never stored in JavaScript-accessible storage.
- A single fetch wrapper (`lib/api.ts`) adds the API base URL (`NEXT_PUBLIC_API_URL`), sends cookies, and turns error bodies into messages. Uploads use a small `XMLHttpRequest` helper (`lib/videos.ts`) because `fetch` cannot report upload progress.
- The project page's **Source video** section uploads a file, shows the metadata the API returns (only fields that exist), and renders a native `<video controls>` for ready videos. For ready videos a **Transcription** panel starts the job, polls `GET …/transcription` every 4 s only while it is active, shows real progress, failure/stalled states with retry, and a paginated timestamped transcript viewer. Once the transcript is complete, an **AI clip detection** panel offers the server's provider/model allow-lists, starts a run, polls `GET …/clip-detection/{run_id}` every 4 s while active with staged progress, handles failed/stalled runs with bounded retry, lists previous runs, and renders the **candidate review** (ranked cards, score breakdown, transcript excerpt, in-page preview of the candidate range from the owner-only stream, save/dismiss with filters). The page is a workflow: a stepper (Upload, Transcribe, Find clips, Generate, Edit) fed by each section's real state, then numbered panels — Source video, Transcript, Clip moments (ranked candidate cards with a compact generated-clip block), Generated clips (thumbnails, short counts, links to the editor). The short-form editor is a separate page, `/projects/[id]/clips/[clipId]` (`components/app/short-editor-view.tsx`, `components/app/editor/*`): a 9:16 stage with a labelled approximate preview or the rendered MP4, visual settings, the render action with real states, and the versions list. Smart reframe (`editor/smart-reframe.tsx`, `lib/reframe.ts`) adds the framing-analysis panel (start, real progress, confidence summary, retry), a keyboard-accessible focal-point picker, and a preview that follows the completed crop path frame by frame.

### Backend (`backend/`)

- FastAPI with routers for `health`, `auth`, `projects`, `videos` (upload + metadata), `video_content` (streaming), `transcriptions` (start/status/retry/transcript), `clip_detection` (providers, runs, candidates, decisions), `clips` (generate/status/retry/list), `clip_media` (private clip preview and download, sharing `media_streaming.py` with source preview), `clip_edits` (create/list/status/retry of short-form edits), `edit_media` (private short preview and download), `reframe` (start/list/current/status/crop path/retry of smart-reframing analyses), `caption_tracks` (start/list/current/status/words/retry of word timing, timing options, caption preview) `caption_styles` (the dynamic renderer's presets, placements, safe area and hook limits for the editor preview) and `audio_assets` (upload, list, metadata, waveform and owner-only Range preview of a project's music and sound effects, plus `/audio-upload-limits`); request/response schemas (Pydantic) are separate from ORM models.
- Settings from environment variables via pydantic-settings; `DATABASE_URL` and `SECRET_KEY` are required.
- SQLAlchemy 2 with a **synchronous** engine and one session per request (`get_db`). Async was deliberately not introduced.
- Alembic migrations are the only way the schema changes; `alembic check` runs in CI to catch model/migration drift.
- Services: `storage.py` (local media files), `video_upload.py` (validation + storage), `ffprobe.py` (metadata), `video_processing.py` (status transitions), `audio_extraction.py` (normalized audio), the `transcription/` package (provider contract, factory, chunking, pipeline, providers) and the `clip_detection/` package (provider contract + shared schema and prompt, factory with allow-lists, Ollama and OpenAI providers, windowing, validation, ranking, config snapshot, pipeline), `clip_render/` (clip artifacts, FFmpeg renderer, pipeline) `clip_edit/` (edit config, 9:16 composition, smart and manual crops, captions, caption styles, edit artifacts, pipeline) `reframe/` (config snapshot, frame sampling, detector contract, YuNet face detector, tracking, crop path planning, pipeline) and `caption_timing/` (config snapshot, word-timing provider contract, faster-whisper word timestamps, validation, pipeline). Audio: `audio_assets.py` (upload validation by content, probing, hashing, waveform peaks) and `audio_mix/` (the edit's audio section, the FFmpeg mix plan, ducking presets, loudness, mixer). Dynamic captions live in `clip_edit/` (`dynamic_cues.py`, `caption_v2.py`, `caption_metrics.py`, `safe_area.py`, `hook.py`, `emoji.py`, `dynamic_text.py`).
- Workers: `app/workers/celery_app.py` (Celery on Redis), `transcription_tasks.py`, `clip_detection_tasks.py`, `clip_render_tasks.py`, `clip_edit_tasks.py`, `reframe_tasks.py`, `caption_tasks.py` and `dispatch.py` (enqueue helpers; every job's task id is chosen and committed on its row before enqueueing and serves as the attempt token); only database ids cross the broker.

### Video pipeline (Milestone 2)

```
POST /projects/{id}/videos
  → validate (filename sanitised, .mp4/.mov/.webm, plausible MIME, non-empty)
  → spool to a private temp file under WORK_ROOT in 1 MiB chunks, enforcing MAX_VIDEO_UPLOAD_BYTES
  → store as videos/<uuid>.<ext> through the storage contract (local directory or private bucket)
  → insert `videos` row (status uploaded)            — object deleted if this fails
  → ffprobe the spooled copy (argument list, JSON output, FFPROBE_TIMEOUT_SECONDS); spool removed
  → status ready + duration/width/height/fps/codecs, or status failed + safe error_message
  → response (same shape as GET /projects/{id}/videos/{video_id})
```

Probing is synchronous in Milestone 2; no queue or worker exists. The browser then fetches `GET /videos/{video_id}/content` (owner-only, HTTP `Range` support) for preview.

### Transcription pipeline (Milestone 3)

```
POST …/transcription  →  Transcription row (queued)  →  Celery task id stored  →  202-style quick return
Worker:
  claim (DB state + fencing token)
  → fetch the source into the attempt's scratch directory (read in place on local storage)
  → extract normalized audio   scratch: transcription/<id>/<attempt>/normalized.mp3   (progress 5)
  → split into 10-minute chunks  scratch: transcription/<id>/<attempt>/chunks/NNNN.mp3
  → per chunk: provider.transcribe → validate → shift to absolute time → commit segments, progress, heartbeat
  → completed (full_text, progress 100)   |   failed (error_code, safe error_message, no partial segments)
  → the attempt's scratch directory is removed (nothing derived is kept in media storage)
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
GET /clips/{id}/content | /download  →  owner check → storage contract (storage_key) → Range stream
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
GET /edits/{id}/content | /download  →  owner check → storage contract (storage_key) → Range stream
```

- **Derived, never destructive:** the V0.5 clip file is the read-only input; every edit is its own row and file.
- **Untrusted text:** transcript text only reaches the ASS file through escaping (word joiner after backslashes, escaped braces); filtergraphs come from constants; the caption file is a fixed relative name, so no path enters a filtergraph.
- **Ownership:** the same attempt-token fencing as clip rendering, plus per-attempt workspaces; a row deleted mid-render makes the worker stop without writing. Retry locks the row.
- **Renderer checks:** libass presence (`subtitles` filter) and a probe caption that must draw text pixels (fonts) before a captioned render.

Full reference: [short-form-editing.md](short-form-editing.md).

### Smart reframing pipeline (Milestone 7)

```
POST …/clips/{id}/reframe  →  server config snapshot + fingerprint (unique per clip)
                           →  existing? 200 (failed: 409, use retry) | detector not installed? 409
                           →  ReframeAnalysis row (queued, pre-chosen task id) → enqueue peaksift.analyze_reframe → 201
Worker (app/services/reframe/):
  claim (DB state + attempt token), clear any old keyframes                              (5)
  → sampling   ffprobe display geometry; one ffmpeg pipe: fps=N:round=up → scale → rgb24
  → detecting  YuNet face detector (onnxruntime, lazy, pinned model) per frame      (10 → 80)
  → tracking   association → tracks → subject with hysteresis, hand-offs           (85)
  → planning   dead zone, margins, groups, look-ahead, smoothing, pan limit, cuts   (92)
  → validate keyframes, then ONE commit: keyframes + statistics + completed          (100)
  | failed      safe error_code/message (detector failure ≠ no face), no partial path
POST …/edits {layout: smart_reframe, reframe_analysis_id}
  → edit worker re-validates the keyframes → ffmpeg crop=x(t),y(t) (balanced if-tree)
  → scale 1080×1920 → captions → the usual validation and atomic finalize
```

- **No temporary files:** frames stream through a pipe; a watchdog kills FFmpeg at the deadline.
- **Server-controlled:** the detector, model file and every tuning value are configuration; a request can only ask "analyse this clip". The model is installed by an operator script (pinned sha256) and never downloaded automatically.
- **Same ownership rules** as rendering: attempt-token fencing on every commit, stale detection, bounded retry under a row lock.
- **Manual crop** (`manual_crop` layout) needs no analysis: a fixed 9:16 crop around a validated focal point.

Full reference: [smart-reframing.md](smart-reframing.md).

### Dynamic captions pipeline (Milestone 8)

```
POST …/clips/{id}/caption-tracks  →  server config snapshot (caption_alignment_v1) + fingerprint (unique per clip)
                                  →  CaptionTrack row (queued, pre-chosen task id) → enqueue peaksift.generate_caption_track → 201
Worker (app/services/caption_timing/):
  preparing_audio  decode the clip's audio to 16 kHz mono PCM (pipe, no temp file)
  aligning         faster-whisper transcribe(word_timestamps=True), lazily loaded model
  validating       validate_words: refuse / drop / clamp; clip-local words
  completed        caption_words + track status in one transaction (fencing token checked)
POST …/edits {caption_style: focus|punch|minimal|boxed, caption_timing, caption_track_id, hook_*}
  → caption_v2: dynamic_text.dynamic_cues (track words re-validated) → build_word_cues
    → build_dynamic_ass (+ hook events, emoji policy) → compose_short (layout / smart crop → libass)
```

GET …/caption-preview returns the same cues to the editor, which draws them over the playing video. Full reference: [dynamic-captions.md](dynamic-captions.md).

### Audio mixing (Milestone 9)

```
POST …/projects/{id}/audio-assets  →  validate by content (ffprobe) → store (generated key, sha256) → waveform peaks → AudioAsset
POST …/edits {..., audio: {source_gain_db, normalize, music: {...}, sfx: [...]}}
  → AudioMix (audio_mix_v1) in the snapshot/fingerprint; assets checked (project, kind)
Worker (run_clip_edit), after captions:
  probe clip → re-check assets → mix plan (bed of the clip's length; source; music trim/loop/fades/gain;
  sidechaincompress ducking; delayed effects) → audio-mix.wav → limiter + two-pass loudnorm → audio-final.wav
  → compose_short muxes it as AAC → validate (stereo 48 kHz, video length) → measure loudness/true peak → ready
```

Full reference: [audio-sound-design.md](audio-sound-design.md).

### Storage

- **Media storage** (`STORAGE_BACKEND`) holds only persistent media: `videos/<uuid4>.<ext>`, `audio/<uuid4>.<ext>`, `clips/<clip-uuid>/clip.mp4`, `edits/<edit-uuid>/edited.mp4`. Keys are application-generated; the original filename is metadata only. Locally it is `MEDIA_ROOT` (default `backend/media`, git-ignored), where `path_for` is the single chokepoint that proves a key resolves inside the root; in production it can be a private S3-compatible bucket. Nothing in it is served statically.
- **Scratch** (`WORK_ROOT`, default a `peaksift-work` directory in the system temp dir) holds everything a job only needs while it runs: uploads being validated, fetched inputs, normalized audio and chunks, `clips/<clip-uuid>/clip-tmp-<attempt>.mp4`, `edits/<edit-uuid>/work-<attempt>/{inputs/,captions.ass,short.mp4}`, frame-sampling and word-timing inputs. Each attempt owns its directory (fencing) and removes it when it ends; scratch is never served and never backed up.
- **Jobs read local files:** inputs come from `fetch(key, directory)` — the stored file itself on local storage (no copy), a download into the attempt's directory on S3 — and finished renders are validated in scratch, then stored with `put_file` (never overwrites, all-or-nothing; a hard link on the same local filesystem). `ready` therefore always means a validated row *and* an object in media storage; the API re-checks the object and reconciles a vanished one to a retryable failure.
- **Storage contract** (`app/services/storage.py`): `StorageProvider` — `exists`, `size`, `save` (stream, never overwrites, size limit), `put_file`, `download_file` and `fetch` (to a local workspace), `iter_range` (a byte range in 1 MiB chunks), `delete` (idempotent), `check` (health). Two providers implement it: `LocalStorageProvider` (`MEDIA_ROOT`; `path_for` stays its chokepoint) and `S3StorageProvider` (a private bucket on any S3-compatible service through boto3: objects are written without ACLs, no public or presigned URLs, path-style addressing for MinIO, TLS required unless `S3_SECURE=false`). `STORAGE_BACKEND=local|s3` selects one. *Missing* (`ObjectNotFound`) and *broken* (`StorageUnavailable`) stay distinct — a HEAD on a missing bucket is a bare 404, so the S3 provider confirms the bucket before calling an object missing — and an outage is a `503`, never a reconciled "artifact missing".
- **Publishing pipeline:** `publish_short` stores the encrypted resumable session before sending any byte, streams the short from storage by ranges, resumes the stored session after any crash or retry (one video per job, ever), marks connections `needs_reconnect` on `authentication_required`, and follows processing with bounded countdown checks — ending honestly at `uploaded` when YouTube cannot report processing for the upload-only scope.
- **Rate limits:** `app/core/rate_limit.py` — Redis fixed windows per client address (login, register; login also per account) and per user (uploads, transcription, detection, renders, framing, word timing, retries), `429` + `Retry-After`, `503` when Redis is down, budgets overridable with `RATE_LIMITS`.
- **Observability:** `app/core/observability.py` — a pure-ASGI middleware assigns `X-Request-ID` and writes the access line (no query string); Celery signals carry the request id to workers and tag lines with `task`/`job_id`; one redacting handler (JSON in production) serves the API and workers.
- **Health:** `/health/live` touches nothing; `/health/ready` checks PostgreSQL, Redis and media storage concurrently within 5 s and answers `ok`/`unavailable` per component only; `python -m app.cli.health` is the worker-side equivalent (plus scratch and FFmpeg/libass, optional broker ping).
- **Deletion and cleanup:** deleting a project (confirmed by its exact name), an edit or an unused audio file deletes the rows in one commit and then the files (`app/services/media_deletion.py`); failures leave counted orphans. `python -m app.cli.media cleanup [--apply]` (`app/services/media_cleanup.py`) removes orphans, interrupted local writes and stale scratch older than a grace period that always exceeds the job time limit.
- **Migration:** `python -m app.cli.media migrate|verify --from local --to s3` (`app/services/media_migration.py`) copies every database-referenced object copy-first and resumably, never overwrites a differing object, never deletes the source, and verifies sizes or SHA-256 before the switch (see the backend README).
- Every media endpoint streams through `stream_object` in `app/api/media_streaming.py` on that contract (a ranged GET on S3), so the HTTP behaviour — `200`/`206`/`416`, suffix ranges, headers, owner checks — is identical on both backends; the contract and HTTP suites run against a local directory, an in-process S3 (moto) and, when `TEST_S3_*` is set, a live S3-compatible service.

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
| `clip_edits` | `id` (uuid), `clip_id` (FK → clips, cascade), `video_id` (FK → videos, cascade), `status`, `progress_percent` (0–100), `attempt` (≥ 1), `config` (JSONB, versioned snapshot), `config_fingerprint` (sha256; **unique with `clip_id`**), `aspect_ratio` (`9:16`), `layout` (`center_crop`/`blur_background`/`fit`/`smart_reframe`/`manual_crop`), `reframe_analysis_id` (FK → reframe_analyses, cascade; set iff `smart_reframe` — checked), `focus_x`/`focus_y` (0–1; set iff `manual_crop` — checked), `captions_enabled`, `caption_style`, `caption_position` (both set iff captions are enabled — checked), `caption_renderer` (`caption_v1`/`caption_v2`; set iff captions are enabled — checked), `caption_timing` (`aligned_word`/`phrase_fallback`; v2 only) and `caption_track_id` (FK → caption_tracks, cascade; set iff `aligned_word` — checked), `hook_enabled`, `hook_text`, `hook_style`, `hook_position`, `hook_duration_seconds` (all set iff the hook is on — checked), `audio_loudness_lufs` / `audio_true_peak_dbtp` (measured on the finished short when it has an audio section), `output_width`/`output_height` (1080 × 1920), `render_profile`, `storage_key` (unique, internal), `content_type`, `file_size`, `duration_seconds`, `width`, `height`, `fps`, `video_codec`, `audio_codec`, `caption_cue_count`, `error_code`, `error_message`, `celery_task_id` (internal), `created_at`, `updated_at`, `started_at`, `completed_at`, `heartbeat_at` |
| `reframe_analyses` | `id` (uuid), `clip_id` (FK → clips, cascade), `video_id` (FK → videos, cascade), `status` (`queued`/`sampling`/`detecting`/`tracking`/`planning`/`completed`/`failed`), `progress_percent` (0–100), `attempt` (≥ 1), `provider`, `provider_version`, `algorithm_version`, `config` (JSONB snapshot), `config_fingerprint` (sha256; **unique with `clip_id`**), `sample_fps`, `target_aspect_ratio`, `source_width`/`source_height` (both or neither — checked), `overall_confidence`, `confidence_level` (`high`/`mixed`/`fallback`), `frames_sampled`, `detections_count`, `tracks_count`, `subject_switches`, `fallback_fraction`, `error_code`, `error_message`, `celery_task_id` (internal), `created_at`, `updated_at`, `started_at`, `completed_at`, `heartbeat_at` |
| `caption_tracks` | `id` (uuid), `clip_id` (FK → clips, cascade), `video_id` (FK → videos, cascade), `status` (`queued`/`preparing_audio`/`aligning`/`validating`/`completed`/`failed`), `progress_percent` (0–100), `attempt` (≥ 1), `provider`, `model`, `alignment_version`, `config` (JSONB snapshot), `config_fingerprint` (sha256; **unique with `clip_id`**), `language_hint`, `language`, `language_probability`, `audio_duration_seconds`, `word_count`, `rejected_word_count`, `average_confidence`, `error_code`, `error_message`, `celery_task_id` (internal), `created_at`, `updated_at`, `started_at`, `completed_at`, `heartbeat_at` |
| `caption_words` | `id` (uuid), `caption_track_id` (FK → caption_tracks, cascade), `sequence_index` (unique per track), `start_time` / `end_time` (clip-local seconds, end > start — checked), `text` (as recognized), `confidence` |
| `publishing_connections` | `id` (uuid), `user_id` (FK → users, cascade, **unique** — one connection per user), `provider` (`youtube` — checked), `status` (`connected`/`needs_reconnect` — checked), `account_id`, `account_title` (display only), `scopes` (granted), `refresh_token_ciphertext` (AES-256-GCM: nonce ‖ ciphertext ‖ tag, associated data binds user, provider and key version; never returned or logged), `token_key_version` (≥ 1), `connected_at`, `last_used_at`, `created_at`, `updated_at` |
| `publish_jobs` | `id`, `user_id` (FK → users, cascade), `edit_id` (FK → clip_edits, cascade), `connection_id` (FK → publishing_connections, set null), `provider` (`youtube`), `title` (1–100 chars), `description` (≤ 5000 bytes), `tags` (JSON array), `privacy` (`private`/`unlisted`/`public`, default private), `made_for_kids`, `category_id`, `fingerprint` (sha256; **unique with `user_id`**), `status` (`queued`/`preparing`/`uploading`/`uploaded`/`processing`/`published`/`failed`/`provider_failed` — checked; uploaded and later require `provider_video_id`), `progress_percent`, `attempt`, `bytes_total`, `bytes_uploaded` (≤ total), `upload_session_ciphertext` + `upload_session_key_version` (the resumable session URI, AES-GCM; internal), `upload_session_started_at`, `provider_video_id` (unique), `provider_upload_status`, `provider_processing_status`, `error_code`, `error_message`, `celery_task_id` (internal), timestamps, `published_at` |
| `oauth_states` | `id`, `user_id` (FK → users, cascade), `provider` (`youtube`), `state_hash` (SHA-256 hex, unique), `code_verifier_ciphertext` (AES-GCM), `key_version`, `expires_at` (10 minutes), `created_at` — deleted atomically on first use |
| `audio_assets` | `id` (uuid), `project_id` (FK → projects, cascade), `kind` (`music`/`sfx` — checked), `display_name` (sanitized; metadata only), `storage_key` (unique, internal), `content_type`, `file_size` (> 0), `sha256` (64 hex; **unique with `project_id` and `kind`**), `container`, `codec`, `duration_seconds` (> 0), `sample_rate` (> 0), `channels` (≥ 1), `waveform_peaks` (JSON array of 0–100 integers), `created_at`, `updated_at` |
| `reframe_keyframes` | `id` (uuid), `reframe_analysis_id` (FK → reframe_analyses, cascade), `sequence_index` (unique per analysis), `timestamp` (≥ 0, clip-local seconds), `center_x`, `center_y`, `crop_width`, `crop_height` (fractions of the display-oriented source; checked so the crop stays inside the frame), `confidence` (0–1), `mode` (`tracked`/`group`/`fallback`) |

Timestamps are timezone-aware. Project `status` is currently always `created`. Video `status` is `uploaded` → `processing_metadata` → `ready` | `failed`; the metadata columns stay empty until probing fills them. A project may own several videos at the database level; the UI surfaces the latest. Transcription `status` is a separate state machine — `queued` → `extracting_audio` → `transcribing` → `completed` | `failed` — answering "what is happening to the speech-to-text job", while video status answers "is this media usable". Segment times are absolute seconds from the start of the video (floats, like the video's `duration_seconds`). Clip detection `status` is a third state machine — `queued` → `preparing_transcript` → `analyzing` → `validating` → `ranking` → `completed` | `failed` — and candidate times are absolute seconds on transcript-line boundaries; scores are integers on one 0–100 editorial scale. Clip `status` is a fourth — `queued` → `rendering` → `validating` → `ready` | `failed` — describing the health of the rendered artifact; each clip edit has the same lifecycle for its own short.

### Testing and CI

- Backend: pytest against a dedicated PostgreSQL test database; migrations are applied at the start of the session and every test is rolled back. Media tests use a throwaway `MEDIA_ROOT`; fixtures are generated at test time with `ffmpeg` (none are committed). Celery runs in eager mode; speech models are mocked (an opt-in real `tiny`-model check exists for macOS); clip-analysis providers are tested with a mocked transport / fake SDK client plus an in-process fake Ollama HTTP server (an opt-in real check runs against a local Ollama with `PEAKSIFT_REAL_OLLAMA=1`). Integration tests skip locally without FFmpeg/Redis and are required in CI (`REQUIRE_FFMPEG=1`, `REQUIRE_REDIS=1`, `HF_HUB_OFFLINE=1`, `OLLAMA_BASE_URL` on a closed port).
- Frontend: ESLint, a type check (`next typegen` + `tsc --noEmit`) and a production build.
- GitHub Actions runs both on every push to `main` and every pull request; the backend job installs FFmpeg, runs PostgreSQL and Redis service containers, installs the Noto fonts, checks that FFmpeg provides `libx264`, `aac`, libass and the layout filters, that fontconfig resolves the caption fonts and that a probe caption draws text, runs real clip renders end-to-end through the API and real captioned 9:16 renders verified on frame pixels (`REQUIRE_LIBASS=1`), checks that the caption, Arabic and emoji font families resolve and really draw (`scripts/caption_font_probe.py`), renders word-synced captions with a hook end to end and checks the frames (`scripts/dynamic_caption_probe.py`), renders an audio-mix matrix and measures ducking, loudness and the short's audio (`scripts/audio_mix_probe.py`), renders the deepest allowed smart-crop path on the runner's FFmpeg (`scripts/smart_crop_probe.py`), refuses tracked model weights or media, runs a full Alembic up/down cycle, and finishes with a real worker smoke (`ping` round-trip and registration of the transcription, clip detection, clip rendering, short-form edit, smart-reframe and caption-timing tasks). Face detection is tested against a fake ONNX session; real YuNet inference is an opt-in local test (`PEAKSIFT_REAL_DETECTOR=1`), so CI never downloads a model.

## Planned (later milestones)

```
Backend ──▶ Object storage (source videos, generated clips, edited shorts)
```

No milestone after V1.0 has been defined. Possible later work — creator intelligence and metadata, more publishing destinations and scheduling, asset libraries, Morocco Mode — is not committed scope (see [milestones.md](milestones.md)). Production operation and YouTube publishing are described in [production.md](production.md) and [publishing.md](publishing.md).

## Localization

The Global experience is the base. Morocco Mode, when built, extends it (additional analysis context and asset libraries) rather than forking it. No localization code exists yet.

## Principles

- Configuration and secrets via environment variables; only `.env.example` files are committed.
- Keep the system simple; add components only when a milestone requires them.
- The API is the security boundary; frontend route guards are a convenience.
- User-supplied names never become paths or command arguments.

## B-roll & visual enrichment (V1.1)

Visual assets (`app/models/visual_asset.py`, `app/services/visual_assets.py`,
`app/api/visual_assets.py`) are validated, normalized and stored through the
`StorageProvider`. B-roll suggestions run as a Celery job (`app/services/broll/`) over the
clip's words; matching is computed by the API. An edit's optional `visuals` section
(`app/services/visuals/`) is drawn by `compose_short` between framing and captions:
`[framed]` → visual layers → `[visual]` → captions + hook. Details:
[broll-visual-enrichment.md](broll-visual-enrichment.md).

## Auto Edit (V1.2)

`app/services/auto_edit/` gathers a clip's completed inputs (`sources.py`), asks a planner
(`ollama.py` or the deterministic `fallback.py`, behind the `contract.py` boundary with symbolic
handles), validates the proposal into a normal `EditConfig` (`validation.py`) and stores it on an
`AutoEditPlan` (`app/models/auto_edit.py`) in the fenced Celery job `peaksift.plan_auto_edit`
(`pipeline.py`, `state.py`). Applying a plan goes through the edit API's own
`create_or_reuse_edit`, so the renderer is unchanged. Details: [auto-edit.md](auto-edit.md).

## Semantic asset intelligence (V1.3)

`app/services/semantic/` indexes what each visual asset shows with a local image–text model
(CLIP ViT-B/32 on onnxruntime, `clip_onnx.py`, behind the `contract.py` provider boundary). Uploads
request an index (`lifecycle.py`, `indexing.py`) that the fenced Celery job
`peaksift.index_visual_asset` fills: StorageProvider → attempt workspace → canonical pixels
(`images.py`) or bounded video frames (`sampling.py`) → validated unit vectors in PostgreSQL
(`visual_semantic_indexes`, `visual_asset_embeddings`, pgvector). `search.py` ranks a project's
assets for a query (exact scoped scan of the current model's vectors + the V1.1 word matcher, in
strong / possible tiers); `matching.py` does the same for B-roll suggestions and turns a video's
best scene into a safe offset. Auto Edit's `sources.py` uses those matches, and only strong ones
may be placed. Details: [semantic-assets.md](semantic-assets.md).

## Performance analytics (V1.4)

Published shorts are linked to the PeakSift output that made them (publish job → edit, plan,
candidate) with an immutable provenance snapshot. After a creator's explicit read-only grant,
a fenced Celery job reads live counters (YouTube Data API) and processed daily analytics
(YouTube Analytics API) through a provider contract (a deterministic fake in tests), upserting
one row per reporting day and view definition; Celery beat schedules syncs by age. Comparisons
use fixed early windows and the creator's own median; a deterministic insights engine
(Mann–Whitney + Holm–Bonferroni) reports associations among the creator's own shorts, which
Auto Edit may consider as weak hints. See [performance-analytics.md](performance-analytics.md).

## Creator Copilot (V1.6)

*Ask PeakSift* answers questions about the creator's own data. Details:
[creator-copilot.md](creator-copilot.md).

```
panel / command menu ──POST /copilot/messages──▶ api/copilot.py (rate limits, input cleanup)
                                                   │
             services/copilot/context.py ◀─────────┤ build_context: owner-scoped view + handles
             services/next_action.py      (shared with Home and the Overview)
             services/strategy.py         (notes, moments already used, fallback ideas)
                                                   │
             services/copilot/answers.py ──────────┤ PeakSift's own answers (no model)
             services/copilot/prompt.py            │ rules + quoted question + fenced DATA
             services/copilot/provider.py ─────────┤ Ollama (format = JSON schema, temp 0) / fake
             services/copilot/contract.py          │ parse_reply: handles → targets, clean text
             services/copilot/safety.py            │ no claimed actions, no instructions, no unknown times
             services/copilot/ideas.py             │ idea cards anchored to real moments / times
             services/copilot/actions.py ──────────┤ offer (labels) · resolve on click (409 if gone)
             services/copilot/history.py           │ one locked conversation per project
                                                   ▼
                                     copilot_threads / copilot_messages
```

The model proposes text and handles; the server decides what is shown and offered. No database
connection is held while the model thinks; the question is saved first and the conversation is
locked only to write messages.
