# PeakSift AI — Backend

FastAPI service with a PostgreSQL database (SQLAlchemy 2 + Alembic) and a Celery worker on Redis. It provides a health check, email/password authentication, a per-user project API, source-video upload with ffprobe metadata extraction and owner-only streaming (local filesystem storage for development), background transcription with timestamped segments (faster-whisper locally or OpenAI), and AI clip detection — ranked, validated clip candidates derived from the transcript by a local Ollama model or OpenAI (see [docs/clip-detection.md](../docs/clip-detection.md)), clip generation — a candidate rendered by FFmpeg into a validated private MP4 with Range-streamed preview and download (see [docs/clip-generation.md](../docs/clip-generation.md)), and short-form editing — a generated clip composed as a 9:16 short with transcript captions burned in by libass (see [docs/short-form-editing.md](../docs/short-form-editing.md)).

## Prerequisites

- Python 3.11+ (check with `python3 --version`)
- PostgreSQL 14+ with the pgvector extension installed on the server (the migrations run `CREATE EXTENSION IF NOT EXISTS vector`) — either Docker (`docker compose up -d` from the repository root, `pgvector/pgvector:pg16`) or a local installation plus pgvector
- FFmpeg with libass (`ffprobe` reads uploaded metadata; `ffmpeg` extracts audio and renders clips and shorts): `apt install ffmpeg` on Ubuntu; on macOS `brew install ffmpeg-full` and set `FFMPEG_PATH=/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`, `FFPROBE_PATH=/opt/homebrew/opt/ffmpeg-full/bin/ffprobe` in `.env` (Homebrew's default `ffmpeg` has no libass, so captioned shorts are refused). Without FFmpeg uploads still succeed but end in status `failed`.
- Caption fonts: Noto Sans + Noto Sans Arabic (`apt install fonts-noto-core` / `brew install --cask font-noto-sans font-noto-sans-arabic`). No font files are committed.
- Redis 7+ — either Docker Compose (included) or `brew install redis && brew services start redis`. It is the broker for background jobs; the API starts without it, but queuing a job fails with `503` until it is reachable.
- Ollama (optional, local AI clip detection) — `brew install ollama`, `ollama serve`, `ollama pull llama3.2:3b`. Without it the local provider is reported unavailable; the hosted provider needs `OPENAI_API_KEY`.

All commands below are run from the `backend/` directory.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env               # then set DATABASE_URL and SECRET_KEY
```

`SECRET_KEY` has no default — the app refuses to start without one. Generate it with `openssl rand -hex 32`.

Create the databases if you are not using Docker Compose (which creates both):

```bash
createdb peaksift                  # development
createdb peaksift_test             # used by the test suite
```

Apply the migrations:

```bash
alembic upgrade head
```

## Run

```bash
uvicorn app.main:app --reload
```

- API: http://localhost:8000/health returns `{"status": "ok"}`
- Interactive docs: http://localhost:8000/docs

Background jobs need a worker in a second terminal (same virtualenv, same `backend/` directory):

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

The worker takes one job at a time (`worker_prefetch_multiplier=1`, `task_acks_late=True`), so a crashed worker's job is re-queued rather than lost; the database — not Celery's result backend — is the source of truth for job status. Redis's visibility timeout is kept above the hard task time limit so long jobs are not handed to a second worker mid-run. On macOS, run the worker with `--pool=solo` if you see fork-related problems. `python scripts/celery_smoke.py` verifies a real broker + worker round-trip and that the `peaksift.transcribe_video`, `peaksift.detect_clips` and `peaksift.render_clip` tasks are registered. The same worker runs transcription, clip detection and clip rendering; rendering needs an FFmpeg with the `libx264` and `aac` encoders (Homebrew and Ubuntu builds include both) and runs on the CPU.

## Test

```bash
pytest
```

Tests run against a **separate** database (`TEST_DATABASE_URL`, default `postgresql+psycopg://localhost:5432/peaksift_test`), never against `DATABASE_URL`. The suite applies the Alembic migrations once at the start, rolls every test back, and downgrades the schema at the end.

**Live S3:** the storage contract, HTTP contract and S3 media regression suites also run against a real S3-compatible service when `TEST_S3_ENDPOINT_URL`, `TEST_S3_ACCESS_KEY_ID` and `TEST_S3_SECRET_ACCESS_KEY` point at one (each test creates and removes its own bucket); otherwise those cases skip. CI builds MinIO from source (`deploy/minio.Dockerfile`), starts it with generated credentials and sets `REQUIRE_LIVE_S3=1`, which turns a missing service into a failure instead of a skip.

**CI jobs:** *Frontend* (lint, unit tests, type check, build); *Backend* (ruff, migrations, media probes, the full suite with live S3, a real broker smoke); *Production containers* (build every image, start the HTTPS stack, smoke test through the proxy, backup + verify + disposable restore inside the stack, non-root users, no secret fragment in any log); *Security* (no credentials or secret files tracked, `pip-audit`, `npm audit` on production dependencies). The YouTube suites run on mocked transports only — CI has no Google credentials and makes no Google calls.

## Lint and format (Ruff)

```bash
ruff check .            # lint
ruff format .           # format
```

## Migrations (Alembic)

```bash
alembic upgrade head                                   # apply all migrations
alembic downgrade -1                                   # roll back one
alembic revision --autogenerate -m "describe change"   # after editing models
```

Alembic reads `DATABASE_URL` from the application settings, so it always targets the same database as the app. Review autogenerated files before committing them.

## API

| Method | Path             | Auth | Description                                              |
| ------ | ---------------- | ---- | -------------------------------------------------------- |
| GET    | `/health`, `/health/live` | no | Liveness: `{"status": "ok"}`; touches no dependency |
| GET    | `/health/ready`  | no   | Readiness: PostgreSQL, Redis and media storage within one 5 s deadline → `200 {"status": "ready", "checks": {…: "ok"}}` or `503 not_ready` naming only the unavailable component (no hosts or errors). External providers are not checked |
| POST   | `/auth/register` | no   | Create an account; `201` + sets the auth cookie. `409` if the email is taken. |
| POST   | `/auth/login`    | no   | `200` + sets the auth cookie. `401` with a generic message on bad credentials. |
| POST   | `/auth/logout`   | no   | `204`; clears the auth cookie.                           |
| GET    | `/auth/me`       | yes  | The current user: `id`, `email`, `created_at`.           |
| GET    | `/auth/session`  | no   | `{"user": …}` or `{"user": null}`, always `200` (the app's start-up check). |
| GET    | `/projects`      | yes  | The current user's projects, newest first.               |
| POST   | `/projects`      | yes  | Create a project from `{"name": "..."}`; `201`. Status starts as `created`. |
| GET    | `/projects/{id}` | yes  | One of the current user's projects; `404` if it does not exist or belongs to someone else. |
| DELETE | `/projects/{id}` | yes  | Body `{"confirm_name": "<exact project name>"}` (`422` otherwise). Deletes the project and everything in it in one commit, then its media files: `{media_files_removed, media_files_pending_cleanup}` — files that could not be removed now are left for `cleanup`. |
| POST   | `/projects/{id}/videos` | yes | Upload a source video as `multipart/form-data` (field `file`); `201`. `.mp4`, `.mov`, `.webm` only (`415` otherwise), up to `MAX_VIDEO_UPLOAD_BYTES` (`413`), non-empty (`400`). `404` for projects that are not yours. The file is probed with ffprobe before the response, so `status` is already `ready` or `failed`. |
| GET    | `/projects/{id}/videos` | yes | The project's videos, newest first.                  |
| GET    | `/projects/{id}/videos/{video_id}` | yes | One video; `404` unless it belongs to that project and the project is yours. |
| GET    | `/videos/{video_id}/content` | yes | The source bytes, owner-only (`404` otherwise). Streams in 1 MiB chunks with the stored content type, `Accept-Ranges: bytes`, and single-range `Range` support (`206` / `416`); multi-range or malformed `Range` headers serve the whole file. `Cache-Control: private, no-store`. |
| POST   | `/projects/{id}/videos/{video_id}/transcription` | yes | Queue a transcription for a `ready` video and return its status. Idempotent: a queued/running/completed job is returned as-is (never duplicated); a `failed` one answers `409` (use retry); a video that is not ready answers `409`; `503` if the job queue is unreachable (no row is left behind). |
| GET    | `/projects/{id}/videos/{video_id}/transcription` | yes | Job status: `status`, `progress_percent`, `segment_count`, `is_stale`, `language`, `error_code`/`error_message`, timestamps. `404` before the first start (`?optional=true` answers `200` with `null` instead). No transcript text, task ids or paths. |
| POST   | `/projects/{id}/videos/{video_id}/transcription/retry` | yes | Re-queue a `failed` or stale transcription (`409` otherwise). |
| GET    | `/projects/{id}/videos/{video_id}/transcript` | yes | Timestamped segments in `sequence_index` order, paginated with `offset` (≥ 0) and `limit` (1–500, default 200): `{transcription_id, total, offset, limit, segments[{sequence_index, start, end, text, speaker}], full_text}`. `full_text` is only filled with `?include_text=true`. `409` until the transcription is `completed` (partial transcripts are never exposed); `404` before the first start. |
| GET    | `/clip-detection/providers` | yes | AI providers the user may choose: `[{name, label, models, default_model, configured, available, detail}]`. `models` are the server allow-lists; with `?diagnose=true` configured providers are probed and `available`/`detail` are filled. Never endpoints or keys. |
| POST   | `/projects/{id}/videos/{video_id}/clip-detection` | yes | Start a detection run: `{"provider": "ollama" \| "openai", "model": optional}` → `201` run. `409` without a completed transcript, if the video is not ready, or if a run is already active; `400` for a provider/model outside the allow-lists; `503` if the queue is unreachable (no row is left). |
| GET    | `/projects/{id}/videos/{video_id}/clip-detection` | yes | Runs for the video, newest first: `{total, offset, limit, runs}` (`offset` ≥ 0, `limit` 1–100). |
| GET    | `/projects/{id}/videos/{video_id}/clip-detection/{run_id}` | yes | Run status: `status`, `progress_percent`, `windows_total`, `windows_done`, `attempt`, `candidate_count`, `is_stale`, `transcript_current` (null while active), `config`, `error_code`/`error_message`, timestamps. No task ids, fingerprints or paths. |
| POST   | `/projects/{id}/videos/{video_id}/clip-detection/{run_id}/retry` | yes | Re-queue a `failed` or stale run (`409` otherwise, if the transcript changed, if another run is active, or after `CLIP_DETECTION_MAX_ATTEMPTS`). |
| GET    | `/projects/{id}/videos/{video_id}/clip-detection/{run_id}/candidates` | yes | Ranked candidates of a `completed` run (`409` before), paginated (`offset`, `limit` 1–100) and filterable with `decision=undecided\|saved\|dismissed`. |
| GET    | `…/clip-detection/{run_id}/candidates/{candidate_id}` | yes | One candidate. |
| POST   | `…/clip-detection/{run_id}/candidates/{candidate_id}/save` · `/dismiss` · `/reset` | yes | Record the user's decision; returns the candidate. |

A candidate is `{id, run_id, video_id, rank, start, end, duration, title, hook, rationale, category, transcript_excerpt, overall_score, scores{hook, entertainment, clarity, payoff, completeness}, decision, decided_at, created_at}` — times in absolute seconds on transcript-line boundaries, scores integers 0–100.

Generated clips:

| Method | Path | Auth | Description |
| ------ | ---- | ---- | ----------- |
| POST   | `…/clip-detection/{run_id}/candidates/{candidate_id}/clip` | yes | Render the candidate. Boundaries come from the persisted candidate (any body is ignored) and are re-validated against the source. `201` new clip; `200` with the existing clip if one is queued/rendering/validating/ready (repeat clicks never duplicate); `409` if the last render failed (use retry), the candidate is dismissed (restore first), the video is not ready, or the boundaries fall outside the source; `503` if the queue is unreachable (no row is left). |
| GET    | `…/candidates/{candidate_id}/clip` | yes | Clip state: `status` (`queued`/`rendering`/`validating`/`ready`/`failed`), stage `progress_percent`, `attempt`, `is_stale`, boundary snapshot, `render_profile`, output metadata once ready, safe `error_code`/`error_message`, timestamps. `404` before generation (`?optional=true` answers `200` with `null` instead). A `ready` clip whose file is missing is reported as `failed`/`artifact_missing`. |
| POST   | `…/candidates/{candidate_id}/clip/retry` | yes | Re-queue a failed or stale clip on the same row (`409` otherwise or after `CLIP_RENDER_MAX_ATTEMPTS`). |
| GET    | `/projects/{id}/videos/{video_id}/clips` | yes | The video's clips, newest first (`offset`, `limit` 1–100). |
| GET    | `/clips/{clip_id}/content` | yes | The rendered MP4 inline for `<video>`: `Accept-Ranges: bytes`, `206` + `Content-Range` for a single range (suffix ranges included), `416` when unsatisfiable, `Cache-Control: private, no-store`. `404` unless the clip is yours and ready. |
| GET    | `/clips/{clip_id}/download` | yes | The same bytes as an attachment named after a sanitised title slug plus a short id (e.g. `that-was-crazy-3f2c9a1e.mp4`). |

A clip is `{id, candidate_id, run_id, video_id, title, status, progress_percent, attempt, is_stale, start_time, end_time, duration_seconds, render_profile, content_type, file_size, width, height, fps, video_codec, audio_codec, error_code, error_message, created_at, started_at, completed_at}`. Storage keys, paths and task ids are never returned.

Short-form edits (9:16 variants of a ready clip):

| Method | Path | Auth | Description |
| ------ | ---- | ---- | ----------- |
| POST   | `/projects/{id}/videos/{video_id}/clips/{clip_id}/edits` | yes | Body `{"aspect_ratio": "9:16", "layout": "center_crop" \| "blur_background" \| "fit" \| "smart_reframe" \| "manual_crop", "reframe_analysis_id": uuid (smart_reframe only), "focus_x"/"focus_y": 0–1 (manual_crop only), "captions_enabled": bool, "caption_style": "bold" \| "clean" \| "creator" \| "focus" \| "punch" \| "minimal" \| "boxed", "caption_position": "top" \| "center" \| "bottom", "caption_timing": "aligned_word" \| "phrase_fallback" (dynamic styles only; default aligned_word), "caption_track_id": uuid (aligned_word only; a completed track of this clip), "hook_enabled": bool, "hook_text": 1–60 characters, "hook_style": "headline" \| "boxed" \| "minimal", "hook_position": "top" \| "center", "hook_duration_seconds": 0.5–5, "audio": {"source_gain_db": −24…6, "normalize": bool, "music": {"asset_id", "gain_db": −40…0, "source_start_seconds", "loop", "fade_in_seconds"/"fade_out_seconds": 0–10, "ducking": "off" \| "light" \| "medium" \| "strong"} \| null, "sfx": [≤ 12 × {"asset_id", "at_seconds", "gain_db": −30…6}]}}` (audio assets must be this project's, of the right kind; unknown fields `422`; style/position default to bold/bottom and are dropped when captions are off). `201` new edit; `200` with the existing edit for the same normalized settings; `409` if that variant failed (use retry), the clip is not ready, captions are requested without a completed transcript or without libass; `503` if the queue is unreachable. |
| GET    | `…/clips/{clip_id}/edits` | yes | The clip's variants, newest first (`offset`, `limit` 1–50). |
| GET    | `…/clips/{clip_id}/edits/{edit_id}` | yes | Edit state: `status`, stage `progress_percent`, `attempt`, `is_stale`, the configuration, output metadata and `caption_cue_count` once ready, safe `error_code`/`error_message`. A `ready` edit whose file is missing is reported as `failed`/`artifact_missing`. |
| DELETE | `…/edits/{edit_id}` | yes | Delete an edit and its short (never the source clip); a render still running discards its own output. |
| POST   | `…/edits/{edit_id}/retry` | yes | Re-queue a failed or stale edit on the same row (row-locked; `409` otherwise or after `CLIP_RENDER_MAX_ATTEMPTS`). |
| GET    | `/edits/{edit_id}/content` | yes | The short inline for `<video>`, Range-capable (`206`/`416`), `private, no-store`; `404` unless yours and ready. |
| GET    | `/edits/{edit_id}/download` | yes | Attachment named `<title-slug>-vertical-<short-id>.mp4`. |

An edit is `{id, clip_id, video_id, status, progress_percent, attempt, is_stale, configuration, aspect_ratio, layout, captions_enabled, caption_style, caption_position, reframe_analysis_id, focus_x, focus_y, output_width, output_height, render_profile, caption_cue_count, duration_seconds, width, height, fps, file_size, video_codec, audio_codec, error_code, error_message, created_at, started_at, completed_at}` — never storage keys, paths, task ids, caption files or FFmpeg commands.

Smart reframing (face-tracking crop paths for a ready clip; see [docs/smart-reframing.md](../docs/smart-reframing.md)):

| Method | Path | Auth | Description |
| ------ | ---- | ---- | ----------- |
| POST   | `…/clips/{clip_id}/reframe` | yes | Analyse the clip with the server's configuration. `201` new analysis; `200` with the existing one for the same configuration; `409` if the clip is not ready or its file is missing, smart framing is not installed on the server, or the last analysis failed (use retry); `503` if the queue is unreachable (no row is left). |
| GET    | `…/clips/{clip_id}/reframe` | yes | The clip's analyses, newest first. |
| GET    | `…/clips/{clip_id}/reframe/current` | yes | The analysis for the current configuration; `404` before the first one (`?optional=true` answers `200` with `null` instead). |
| GET    | `…/clips/{clip_id}/reframe/{analysis_id}` | yes | Status (`queued`/`sampling`/`detecting`/`tracking`/`planning`/`completed`/`failed`), `progress_percent`, `is_stale`, `confidence_level` (`high`/`mixed`/`fallback`), statistics, safe `error_code`/`error_message`. |
| GET    | `…/clips/{clip_id}/reframe/{analysis_id}/path` | yes | Ordered keyframes `{timestamp, center_x, center_y, crop_width, crop_height, confidence, mode}` (fractions of the display-oriented source) and the source size; `409` until completed. |
| POST   | `…/clips/{clip_id}/reframe/{analysis_id}/retry` | yes | Re-queue a failed or stale analysis (row-locked; `409` otherwise or after `REFRAME_MAX_ATTEMPTS`). |
| POST   | `…/clips/{clip_id}/caption-tracks` | yes | Time every word of the clip's audio with the server's configuration. `201` new track; `200` with the existing one for the same configuration; `409` if the clip is not ready, word timing is not installed, or the last track failed (use retry); `503` if the queue is unreachable. |
| GET    | `…/clips/{clip_id}/caption-tracks` / `…/current` / `…/{track_id}` | yes | Tracks newest first / the current configuration's track / status (`queued`/`preparing_audio`/`aligning`/`validating`/`completed`/`failed`), `progress_percent`, `is_stale`, `word_count`, `rejected_word_count`, `average_confidence`, safe `error_code`/`error_message`. A configured model directory is shown as `custom`. |
| GET    | `…/clips/{clip_id}/caption-tracks/{track_id}/words` | yes | Words of a completed track in order: `{i, start, end, text, confidence}` (clip-local seconds); `409` until completed. |
| POST   | `…/clips/{clip_id}/caption-tracks/{track_id}/retry` | yes | Re-queue a failed or stale track (row-locked; `409` otherwise or after `CAPTION_TIMING_MAX_ATTEMPTS`). |
| GET    | `…/clips/{clip_id}/caption-timing` | yes | `{word_timing: none\|running\|completed\|failed, track, phrase_timing_available}` for the editor. |
| GET    | `…/clips/{clip_id}/caption-preview?style=&position=&timing=&track_id=` | yes | The renderer's own cues `{start, end, timed, lines: [[{text, start, end, attached}]]}` for the live preview; `409` when they cannot be built yet. |
| POST   | `/projects/{id}/audio-assets` | yes | Upload music or a sound effect (`multipart/form-data`: `file`, `kind` = `music` \| `sfx`). Validated by content with ffprobe; `201` new, `200` the project's existing asset for the same file and kind; `413` too large or too long; `415`/`422` not usable audio. Nothing is kept on refusal. |
| GET    | `/projects/{id}/audio-assets[?kind=]` / `…/{asset_id}` | yes | The project's audio (newest first) / one asset: kind, display name, size, duration, sample rate, channels, codec, container — no keys, paths or hashes. |
| GET    | `/projects/{id}/audio-assets/{asset_id}/waveform` | yes | `{buckets, peaks}`: 200–1000 peak amplitudes (0–100 % of full scale). |
| DELETE | `/projects/{id}/audio-assets/{asset_id}` | yes | Delete an audio file; `409` while any edit's audio section uses it. |
| GET    | `/projects/{id}/audio-assets/{asset_id}/content` | yes | Owner-only preview stream with HTTP Range (`private, no-store`). |
| GET    | `/audio-upload-limits` | yes | `{max_bytes, music_max_duration_seconds, sfx_max_duration_seconds, accepted_extensions}`. |
| GET    | `/caption-styles` | yes | The dynamic renderer's presets, placements, safe area, hook limits, font ratio and emoji policy (`monochrome`/`omitted`). |

No task ids, model paths, storage keys or FFmpeg details are returned.

A video is `{id, project_id, original_filename, content_type, file_size, duration_seconds, width, height, fps, video_codec, audio_codec, status, error_message, created_at, updated_at}`. The metadata fields are `null` until probing succeeds; `error_message` is set only when `status` is `failed`. Storage keys and filesystem paths are never returned.

Auth request bodies are JSON: `{"email": "...", "password": "..."}`. Emails are trimmed and lower-cased; passwords must be 8–128 characters. Project names are trimmed and must be 1–200 characters. A project is `{id, name, status, created_at, updated_at}`.

Validation failures return `422` with `{"detail": [{"type", "loc", "msg"}, ...]}`. Submitted values are deliberately not echoed back (FastAPI's default would include them).

## Authentication design

- **Passwords** are hashed with Argon2id (`pwdlib`, recommended parameters). Plaintext passwords are never stored, logged, or returned, and `password_hash` never appears in a response schema.
- **Sessions** are a signed JWT (HS256, `PyJWT`) whose `sub` is the user's UUID, with `iat`/`exp`. The token carries no other user data. Expiry is `ACCESS_TOKEN_EXPIRE_MINUTES` (default 7 days).
- **Transport** is an `HttpOnly` cookie (`peaksift_access_token`, `SameSite=Lax`, `Path=/`), so JavaScript cannot read the token. `Secure` is set when `APP_ENV=production`. The frontend must send requests with `credentials: "include"`.
- **Logout** clears the cookie in the browser. Tokens are not revoked server-side (no blocklist) — a copied token stays valid until it expires. Acceptable for Milestone 1; revisit with refresh tokens/sessions later.
- **Unknown email vs wrong password** return the identical `401` response, and the unknown-email path still performs an Argon2 verification so response time does not reveal which case occurred.
- **CSRF**: `SameSite=Lax` stops the cookie being sent on cross-site `POST`s from other origins, all state-changing endpoints take JSON bodies (not form posts), and CORS only allows `FRONTEND_URL`. That is the Milestone 1 position; a CSRF token scheme should be added before any cookie-authenticated endpoint accepts form submissions or `SameSite=None` is needed.

## Transcription providers

Speech-to-text sits behind one contract (`app/services/transcription/contract.py`). A provider receives a `TranscriptionRequest` (audio path, optional language hint and short prompt) and returns a `ProviderTranscriptionResult` — text, detected language (+ probability), provider/model names and ordered `ProviderSegment`s with start/end seconds. Each provider declares `ProviderCapabilities` (segment timestamps, word timestamps, language detection, diarization).

**Timestamp contract:** the pipeline cuts clips from segment times, so `get_transcription_provider()` refuses any provider that does not return segment timestamps, and `validate_segments` rejects negative, inverted, out-of-order or NaN times instead of "fixing" them. Timestamps are never fabricated. `TRANSCRIPTION_PROVIDER` selects `faster_whisper` or `openai`; anything else is a configuration error.

### faster-whisper (local, default)

`app/services/transcription/faster_whisper.py` wraps [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2). The model is loaded **lazily on first transcription and cached per process**: importing the module, starting FastAPI, or starting the Celery app never downloads or loads a model. On first use the model is downloaded from Hugging Face into its cache (`~/.cache/huggingface`), so the first job after a fresh install takes longer. CPU + `int8` is the supported development mode (this project is developed on macOS; there is no Apple GPU path in this stack). CUDA GPUs work with `FASTER_WHISPER_DEVICE=cuda` and `FASTER_WHISPER_COMPUTE_TYPE=float16` when the CUDA libraries are installed — that is an optional deployment choice, not a requirement.

Audio is decoded to 16 kHz mono float32 PCM with `ffmpeg` (argument list, timeout) and passed to the model as an array rather than letting faster-whisper decode the file itself: its bundled PyAV decoder is incompatible with the PyAV release installable in this environment (`av.open(..., metadata_errors=…)` was removed), and this keeps every media subprocess under the same rules as the rest of the backend. Chunks are bounded (10 minutes ≈ 38 MB of samples), so memory stays flat for multi-hour streams.

Manual check with the real model (downloads `tiny`, ~75 MB, macOS only because it uses `say` to synthesise speech): `PEAKSIFT_REAL_WHISPER=1 pytest tests/test_faster_whisper_provider.py -k real`. Normal tests mock the model and download nothing.

### Long audio: chunking and absolute timestamps

`app/services/transcription/chunking.py` splits the attempt's scratch `transcription/<id>/<attempt>/normalized.mp3` into deterministic, contiguous, non-overlapping chunks of `TRANSCRIPTION_CHUNK_SECONDS` (default 10 minutes ≈ 4.8 MB) under `…/chunks/NNNN.mp3` (all under `WORK_ROOT`, never media storage); a final remainder under one second is folded into the previous chunk. Cuts use ffmpeg input seeking on the constant-bitrate MP3, which lands within one MP3 frame (~26 ms) of the requested time. Each chunk carries its absolute start, and `shift_segments` adds it to the provider's chunk-relative times before anything is stored — a provider segment `12.4 → 18.9` in the chunk starting at `600` becomes `612.4 → 618.9`. Any failure while splitting removes every chunk file; when a job ends its whole scratch directory (fetched source, normalized audio, chunks) is deleted.

**Boundary limitation (V0.3):** boundaries are plain time cuts, not silence-aware, so a word spoken exactly across a boundary can be split between two segments. There is no overlap and therefore no duplicated text; a short piece of the previous chunk's text may be passed to the provider as a prompt for continuity only. Semantic/silence-aware chunking is future work.

### The background pipeline

`app/services/transcription/pipeline.py` runs inside the Celery worker (`peaksift.transcribe_video`, which receives only the transcription id):

```
queued → extracting_audio (normalized.mp3, progress 5)
       → chunks
       → transcribing (per chunk: provider → validate → shift to absolute time → persist, progress 5 + 95·done/total, heartbeat)
       → completed (full_text, progress 100)   |   failed (error_code + safe error_message, no partial segments)
```

- **Idempotent on database state:** a `completed` row ignores duplicate deliveries; a row that is `extracting_audio`/`transcribing` with a fresh heartbeat is not started twice; one whose heartbeat is older than `TRANSCRIPTION_STALE_AFTER_SECONDS` (default 30 min — keep it above the worst-case time for one chunk on your slowest worker) is treated as dead and restarted cleanly; a `failed` row is only re-run after the retry endpoint resets it to `queued`. Every (re)start deletes segments from earlier attempts first.
- **Fencing:** the Celery task id stored on the row is a fencing token. A worker only claims a row whose token matches its own task, and re-reads the token before every commit; if a retry or stale restart has handed the row to a newer task, the older run stops at that checkpoint without writing or cleaning up. Two workers therefore never both complete the same transcription.
- **Stale jobs in the API/UI:** the status response carries `is_stale`; the retry endpoint accepts `failed` *or* stale jobs, and the project page shows a "stalled" notice with a retry button.
- **Retries:** transient provider errors (rate limits, timeouts, connection problems, 5xx) are retried inside the task with exponential backoff (`TRANSCRIPTION_PROVIDER_MAX_ATTEMPTS`, `TRANSCRIPTION_RETRY_BACKOFF_SECONDS`: 2 s, 4 s, …). Configuration, capability, invalid-audio, missing-file and malformed-output errors fail immediately. There is no Celery-level autoretry, so a broken file can never loop.
- **Timestamps:** provider times are chunk-relative; the pipeline rejects a segment that ends beyond its chunk (plus `TRANSCRIPTION_TIMESTAMP_TOLERANCE_SECONDS`) and shifts the rest by the chunk's absolute start before inserting. Segments are committed per chunk with a continuous `sequence_index`.
- **Prompting:** the last `TRANSCRIPTION_PROMPT_TAIL_CHARS` of the previous chunk's text are passed to the provider as a prompt for continuity only; nothing from it is stored.
- **Sessions and cleanup:** the worker opens its own SQLAlchemy session per task and disposes the inherited connection pool on process start. The attempt's scratch directory is deleted after success or failure; nothing derived is kept in media storage.

### OpenAI (hosted)

`app/services/transcription/openai_provider.py` uses the official SDK. Set `TRANSCRIPTION_PROVIDER=openai` and `OPENAI_API_KEY`; the key is only required when this provider is selected, is never validated at startup, and is never logged, returned by the API or sent to the frontend.

**Why `whisper-1`:** PeakSift needs segment timestamps to cut clips. In the installed SDK, `gpt-4o-transcribe` and `gpt-4o-mini-transcribe` support only the `json` text format, while `verbose_json` with `timestamp_granularities=["segment"]` — the structured timestamps — is available on `whisper-1`. The pipeline therefore calls `OPENAI_TIMESTAMP_MODEL` (default `whisper-1`); configuring a text-only model there is a capability error, never a silent fallback to invented timestamps. `OPENAI_TRANSCRIPTION_MODEL` and `OPENAI_HIGH_ACCURACY_MODEL` are recorded for future text-quality workflows; V0.3 performs one paid transcription per chunk, not two.

Each chunk is checked against `OPENAI_MAX_UPLOAD_BYTES` (default 20 MB, a margin under the API's 25 MB limit) before upload. Rate limits, timeouts, connection problems and 5xx responses are reported as *retryable* errors for the pipeline's bounded retries; authentication, permission and 4xx problems are not retried.

## AI clip detection

`app/services/clip_detection/` turns a completed transcript into ranked candidates: `windowing.py` (normalise, validate, fingerprint, bounded overlapping windows), `contract.py` (provider protocol, shared strict JSON schema, typed errors), `prompt.py` (one prompt for every provider), `factory.py` (allow-lists → provider), `ollama_provider.py` / `openai_provider.py`, `validation.py` (snap to transcript lines, bounds, scores, texts — reject rather than clamp), `ranking.py` (weighted score, IoU deduplication, deterministic order), `pipeline.py` (the Celery job: claim, stages, fencing, retries, one-transaction completion). Users choose a provider and model only from `OLLAMA_CLIP_MODELS` / `OPENAI_CLIP_MODELS`; `OLLAMA_BASE_URL` and `OPENAI_API_KEY` are server configuration and never appear in responses. The full design, scoring methodology, configuration and limitations are in [docs/clip-detection.md](../docs/clip-detection.md).

## Clip generation

`app/services/clip_render/` turns a candidate into a validated MP4: `storage.py` (keys `clips/<uuid>/clip-tmp-<attempt>.mp4` → `clips/<uuid>/clip.mp4`, atomic finalize, discard, download-name sanitiser), `renderer.py` (FFmpeg argument list — `-ss` before `-i` and re-encoding, never stream copy; libx264/yuv420p + aac, `+faststart`, source geometry and orientation; stderr to a temp file with a bounded, path-redacted tail in logs; heartbeat callback; timeout kill; ffprobe validation of codec, size, duration and audio), `pipeline.py` (the Celery job: claim on database state, fencing on every commit, honest stage progress 10/80/90/100, file-first-then-row finalization, safe failure codes). The full design, configuration and limitations are in [docs/clip-generation.md](../docs/clip-generation.md).

## Short-form editing

`app/services/clip_edit/` turns a ready clip into a 9:16 short: `config.py` (allow-listed enums, normalized versioned snapshot, fingerprint), `composition.py` (constant filtergraphs for center crop / blur background / fit at 1080 × 1920, the FFmpeg command run inside the attempt workspace with `subtitles=captions.ass`, ffprobe validation, libass detection and the caption font probe), `captions.py` (transcript segments → clip-local cues: proportional word timing, segmentation, long-token splitting, emoji removal, ASS escaping), `caption_styles.py` (Bold/Clean/Creator presets, top/center/bottom positions, the ASS document), `storage.py` (`edits/<uuid>/work-<attempt>/` → `edits/<uuid>/edited.mp4`, atomic finalize) and `pipeline.py` (the Celery job `peaksift.render_clip_edit`: claim, attempt-token ownership on every commit, stage progress 5/15/85/90/100, file-first-then-row finalization, safe failure codes). The full design, configuration and limitations are in [docs/short-form-editing.md](../docs/short-form-editing.md).

## Smart reframing

`app/services/reframe/` turns a ready clip into a 9:16 crop path: `config.py` (server-controlled versioned snapshot + fingerprint), `sampling.py` (ffprobe display geometry; one FFmpeg pipe `fps=N:round=up` → scale → rgb24, watchdog timeout, no temp files), `detection.py` (detector contract, normalization, lazy factory; "no face" ≠ "detector broken"), `yunet.py` (OpenCV Zoo YuNet on onnxruntime, sha256-pinned model), `tracking.py` (association, gaps, subject selection with hysteresis, hand-offs), `path.py` (crop geometry, dead zone, margins, groups, look-ahead, smoothing, pan limit, cuts, simplification, confidence) and `pipeline.py` (the Celery job `peaksift.analyze_reframe`: claim, attempt-token ownership, progress 5/10–80/85/92/100, one-transaction finalize). `app/services/clip_edit/smart_crop.py` compiles a validated path into FFmpeg crop expressions for the `smart_reframe` edit layout.

Install the face detector model once per server (it is never committed or downloaded automatically):

```bash
python scripts/fetch_reframe_model.py      # pinned URL + sha256 → ./models/face_detection_yunet_2023mar.onnx
python scripts/fetch_caption_fonts.py      # caption style fonts: pinned google/fonts files + sha256 → ./fonts
python scripts/fetch_library.py            # starter library (sounds, music, stickers): pinned release + sha256 → ./library
python scripts/smart_crop_probe.py         # optional: this FFmpeg renders the deepest allowed crop path
PEAKSIFT_REAL_DETECTOR=1 REFRAME_TEST_FACE_IMAGE=/path/to/face.png pytest tests/test_reframe_detection.py -k real
```

The full design, configuration and limitations are in [docs/smart-reframing.md](../docs/smart-reframing.md).

## Dynamic captions

`app/services/caption_timing/` times the words of a ready clip: `config.py` (versioned `caption_alignment_v1` snapshot + fingerprint), `contract.py` (provider contract, `validate_words`), `faster_whisper.py` (word timestamps from the shared, lazily loaded faster-whisper model) and `pipeline.py` (the Celery job `peaksift.generate_caption_track`: claim, attempt-token ownership, progress 5/10/20/85/100, one-transaction finalize). `app/services/clip_edit/` renders them: `dynamic_cues.py` (cue grouping, line layout, active word), `caption_v2.py` (presets and the ASS document), `caption_metrics.py` (libass-measured Noto Sans widths), `safe_area.py`, `hook.py`, `emoji.py` and `dynamic_text.py` (cues shared by the render and the preview).

```bash
python scripts/caption_font_probe.py      # caption, Arabic and emoji fonts resolve and draw through libass
python scripts/dynamic_caption_probe.py   # end-to-end word-synced render with a hook, checked on frames
PEAKSIFT_REAL_WHISPER=1 pytest tests/test_caption_timing_provider.py -k real   # macOS, tiny model
```

The full design and limitations are in [docs/dynamic-captions.md](../docs/dynamic-captions.md).

## Audio & sound design

`app/services/audio_assets.py` validates and indexes uploads (ffprobe checks, sha256 while storing, waveform peaks from an FFmpeg pipe). `app/services/audio_mix/` finishes a short's audio: `config.py` (the edit's `audio` section, `audio_mix_v1`), `plan.py` (one FFmpeg run from validated numbers onto a bed of the clip's length: source gain, music trim/loop/fades/gain, delayed effects), `ducking.py` (Light / Medium / Strong → `sidechaincompress` constants), `loudness.py` (−1 dBFS limiter, two-pass `loudnorm` to −14 LUFS) and `mixer.py` (`render_mix`, `prepare_track`). The edit pipeline mixes into the attempt's workspace, muxes AAC, validates the track and records `audio_loudness_lufs` / `audio_true_peak_dbtp`.

```bash
python scripts/audio_mix_probe.py   # mix matrix, measured ducking and loudness, full short (CI)
```

The full design and limitations are in [docs/audio-sound-design.md](../docs/audio-sound-design.md).

## B-roll & visual enrichment

`app/services/visual_assets.py` validates uploads by content (Pillow for JPEG/PNG/WebP — pixel limits before decoding, EXIF orientation, sRGB conversion, CMYK/16-bit/alpha/MPO handling, re-encoding; ffprobe for MP4/MOV/WebM with a codec allow-list), makes thumbnails, de-duplicates by sha256 and stores through the `StorageProvider`. `app/services/broll/` suggests B-roll for a clip: `ollama.py` (JSON schema, temperature 0) or `keyword.py` (proper names, deterministic), `validation.py`, `grounding.py`, `suggest.py` (provider choice, honest fallback, review), `pipeline.py` (Celery `peaksift.suggest_broll`, fenced, stage progress) and `matching.py` (tags, name, description). `app/services/visuals/` holds the edit's `visuals` section (`config.py`, `visuals_v1`), asset checks (`assets.py`), inset geometry inside the safe area (`layout.py`), fades (`transitions.py`) and the FFmpeg layers (`compositor.py`) drawn by `compose_short` between framing and captions.

```bash
python scripts/visual_render_probe.py   # ten generated visual cases through the real compositor (CI)
```

The full design and limitations are in [docs/broll-visual-enrichment.md](../docs/broll-visual-enrichment.md).

## Auto Edit

`app/services/auto_edit/` plans an edit for a generated clip: `sources.py` gathers the completed inputs (never starts jobs), `contract.py` defines the planner boundary (symbolic handles, strict `AutoEditProposal`), `ollama.py` asks the local model (JSON schema, per-clip constraints, one corrective attempt, `AUTO_EDIT_TIMEOUT_SECONDS`), `fallback.py` is the deterministic planner, `validation.py` turns any proposal into a normal `EditConfig`, and `pipeline.py` / `state.py` run the fenced Celery job `peaksift.plan_auto_edit`. Recipes live in `recipes.py` (versioned).

```bash
python scripts/auto_edit_benchmark.py                   # six cases x four recipes, rules (CI)
python scripts/auto_edit_benchmark.py --planner ollama  # the same with the local model
```

Settings: `AUTO_EDIT_PLANNER_PROVIDER` (`ollama` or `fallback`), `AUTO_EDIT_OLLAMA_MODEL`, `AUTO_EDIT_FALLBACK_ENABLED`, `AUTO_EDIT_TIMEOUT_SECONDS`, `AUTO_EDIT_STALE_AFTER_SECONDS`, `AUTO_EDIT_MAX_ATTEMPTS`. Details: [docs/auto-edit.md](../docs/auto-edit.md).

## Semantic visual search

`app/services/semantic/` indexes what each visual asset shows with a local image–text model (OpenAI CLIP ViT-B/32 on onnxruntime; nothing leaves the server): `contract.py` (provider contract), `clip_onnx.py` (pinned ONNX model, lazy per-process sessions), `fake.py` (deterministic stand-in for tests, refused in production), `images.py` (canonical pixels), `sampling.py` (bounded video frames), `indexing.py` (the fenced Celery job `peaksift.index_visual_asset`) `lifecycle.py` (uploads start indexing in the background; the API reports each asset's `visual_search` state; bounded lazy reindex after a model change), `search.py` (hybrid search: bounded query cache, an exact project-scoped pgvector scan keeping each asset's best frame, strong / possible tiers with per-model versioned thresholds), `matching.py` (B-roll matches and safe scene offsets) and `benchmark.py`. Vectors are stored in PostgreSQL with pgvector. Endpoints: `GET /projects/{id}/visual-assets/search?q=` and `POST /projects/{id}/visual-assets/{asset_id}/visual-search/retry`; B-roll suggestions carry `match_details`. Full design: [docs/semantic-assets.md](../docs/semantic-assets.md).

```bash
python scripts/fetch_semantic_model.py         # once per server: pinned files, verified sha256
python -m app.cli.semantic status              # assets per state for the current model
python -m app.cli.semantic reindex [--stale] [--missing] [--failed] [--project ID] [--limit N] [--dry-run]
python scripts/semantic_benchmark.py          # fake provider (CI); add --model-dir DIR --media DIR [--calibrate]
python scripts/semantic_search_probe.py --database-url postgresql+psycopg://…/empty_scratch_db \
    [--model-dir ./models/clip-vit-b-32]       # text-embedding and vector-scan timings on this machine
```

Where the model runs: workers load the image encoder (and the text encoder) on their first indexing job; the API loads only the text encoder, on the first search that needs it, and reuses it for the life of the process — a search never downloads media, it compares the query with stored vectors. Measured on an Apple-silicon laptop (CPU, 2 threads): text encoder load about 0.4 s and about 0.5 GB per process, then about 32 ms per new query (cached repeats are free); a scoped scan of one project's 1,600 vectors among 81,600 stored took a median 7.7 ms; a worker holding both encoders peaked at about 1 GB.

Settings: `SEMANTIC_PROVIDER` (`clip_onnx`, `disabled`, or `fake` outside production), `SEMANTIC_MODEL_DIR`, `SEMANTIC_THREADS`, `SEMANTIC_BATCH_SIZE`, `SEMANTIC_VIDEO_MAX_FRAMES`, `SEMANTIC_FRAME_TIMEOUT_SECONDS`, `SEMANTIC_QUEUE`, `SEMANTIC_STALE_AFTER_SECONDS`, `SEMANTIC_MAX_ATTEMPTS`. A worker process holds one copy of the model (about 600 MB) once it indexes; keep one job per worker process. To keep inference off the default queue, set `SEMANTIC_QUEUE=semantic` and run `celery -A app.workers.celery_app worker -Q semantic --concurrency 1` next to the regular worker.

## Performance analytics

`app/services/performance/` (V1.4): `content.py` links each upload to the PeakSift output that made it (with `provenance.py`'s immutable snapshot); `provider.py` / `youtube.py` / `fake.py` / `factory.py` read counters (YouTube Data API) and processed daily rows (YouTube Analytics API, columns by name, everything validated); `sync.py` + `lifecycle.py` run the fenced Celery jobs `peaksift.sync_performance` and `peaksift.schedule_performance_syncs` (Celery beat); `summary.py` and `normalization.py` compute totals, early windows and the creator's own baseline; `insights.py` is the deterministic insights engine (Mann–Whitney + Holm–Bonferroni); `profile.py` feeds Auto Edit; `retention.py` deletes collected metrics. The read-only permission upgrade is in `app/services/publishing/youtube_oauth.py` (`POST /publishing/youtube/analytics/connect`). Endpoints: `GET /performance`, `GET /performance/videos/{id}`, `POST /performance/videos/{id}/refresh`, `GET /performance/insights`, `POST /performance/insights/{id}/dismiss|restore`, `DELETE /performance/data`, `GET /auto-edit/performance-context`. Full design: [docs/performance-analytics.md](../docs/performance-analytics.md).

```bash
celery -A app.workers.celery_app beat --loglevel=info   # one per deployment: the sync scheduler
python -m app.cli.performance status                     # published videos and syncs by status
python -m app.cli.performance sync-due                   # start due syncs (cron alternative to beat)
python -m app.cli.performance backfill --user USER_ID    # link and sync a granted creator's uploads
python scripts/insights_benchmark.py                     # false-pattern and detection rates (CI gate)
```

Settings: `YOUTUBE_ANALYTICS_ENABLED`, `PERFORMANCE_PROVIDER` (`youtube`, or `fake` outside production), `PERFORMANCE_SYNC_STALE_AFTER_SECONDS`, `PERFORMANCE_MANUAL_COOLDOWN_SECONDS`, `PERFORMANCE_SCHEDULE_BATCH`, `PERFORMANCE_SCHEDULE_INTERVAL_SECONDS`.

## Creator Copilot

`app/services/copilot/` (V1.6): `context.py` builds the owner-scoped view with handles,
`history.py` keeps one locked conversation per project, `prompt.py` / `provider.py` ask the local
model (Ollama, strict JSON schema) or the deterministic fake, `contract.py` parses and cleans the
answer, `safety.py` screens it, `answers.py` answers what PeakSift knows exactly, `ideas.py` checks
idea cards, `actions.py` offers and re-checks actions, `service.py` ties them together;
`app/services/next_action.py` (shared with Home) and `app/services/strategy.py`. Endpoints:
`GET /copilot/status`, `GET /copilot/context`, `GET` / `DELETE /copilot/thread`,
`POST /copilot/messages`, `POST /copilot/messages/{id}/actions/{index}`. Full design:
[docs/creator-copilot.md](../docs/creator-copilot.md).

```bash
COPILOT_ACCEPTANCE_EMAIL=… COPILOT_ACCEPTANCE_PASSWORD=… \
  python scripts/copilot_acceptance.py --api http://localhost:8000 --project ID   # real-model gate
```

Settings: `COPILOT_ENABLED`, `COPILOT_PROVIDER` (`ollama`, or `fake` outside production),
`COPILOT_OLLAMA_MODEL`, `COPILOT_TIMEOUT_SECONDS`, `COPILOT_MESSAGE_MAX_CHARS`.

## Editor timeline gate

`scripts/timeline_acceptance.py` checks that a rendered version matches the timing its editor
timeline showed: cutaway frames before / inside / after, sound-effect onsets (cross-correlated
above 10 kHz) and caption lines read back with Tesseract. See
[docs/editor-timeline.md](../docs/editor-timeline.md).

```bash
TIMELINE_ACCEPTANCE_EMAIL=… TIMELINE_ACCEPTANCE_PASSWORD=… \
  python scripts/timeline_acceptance.py --api http://localhost:8000 \
  --project ID --video ID --clip ID --edit ID
```

## Brand Studio

`app/services/branding/` (V1.7): `colors.py` (hex normalization, WCAG contrast),
`profiles.py` (brands, one default, logo ownership), `template_config.py` (the allow-listed
`TemplateConfig`), `templates.py` (versioned templates, starters, `plan_snapshot`,
`brand_for_edit`); `app/services/auto_edit/template.py` (`apply_template`, the precedence);
`app/services/clip_edit/brand.py` (the snapshot section and the logo placement policy) and
`brand_render.py` (logo overlay and end card); `app/services/copilot/branding.py`. Endpoints:
`/brand/profiles`, `/brand/templates` (+ `/duplicate`), `/brand/template-starters`,
`/brand/logo-candidates`, `/brand/layout`, `/brand/edit-section`. Full design:
[docs/brand-studio.md](../docs/brand-studio.md).

```bash
BRAND_ACCEPTANCE_EMAIL=… BRAND_ACCEPTANCE_PASSWORD=… \
  python scripts/brand_acceptance.py --api http://localhost:8000 \
  --project ID --video ID --clip ID --template ID [--music ID]   # real-render release gate
```

## Media serving

Nothing under `MEDIA_ROOT` is exposed as static files. The only ways to fetch media bytes are `GET /videos/{video_id}/content` (source videos) `GET /clips/{clip_id}/content` / `/download` (rendered clips) and `GET /edits/{edit_id}/content` / `/download` (edited shorts); each resolves the item through its project's owner and streams the stored key through the storage contract and the shared Range implementation in `app/api/media_streaming.py` (identical on the local and S3 backends; an unreachable storage backend is a `503`). The browser's `<video>` element sends the session cookie because the frontend and API are same-site (`localhost` in development); deploy them under one registrable domain so that stays true.

## Moving media to object storage

Media can move between backends without downtime for reads; the database is the list of what must exist (source videos, audio assets, ready clips, ready edits).

```bash
# 1. Fill in S3_* (STORAGE_BACKEND stays local) and create a PRIVATE bucket.
python -m app.cli.media migrate --from local --to s3 --dry-run   # what would be copied
python -m app.cli.media migrate --from local --to s3             # copy (resumable: rerun freely)
python -m app.cli.media verify  --from local --to s3 --checksum  # every object, SHA-256
# 2. Only when verify exits 0: set STORAGE_BACKEND=s3 and restart the API and workers.
# 3. Keep MEDIA_ROOT until you have checked the application on S3; nothing is deleted for you.
```

- **Copy-first, never destructive:** the source is only read. An object already at the destination with the same size is skipped, so an interrupted run resumes; one with a different size is a *conflict*, reported and never overwritten.
- **Honest report:** each object is `copied`, `present`, `missing` (the database references it but the source lacks it), `conflict` or `failed`; verify adds `absent` and `size differs` / `content differs`. The exit status is non-zero while anything is unaccounted for. Output names storage keys and counts, never credentials.
- Run the API and workers stopped (or read-only) between the final `migrate` and the switch, so no new upload lands only in the old backend; a second `migrate` right before switching copies anything new.
- The reverse direction (`--from s3 --to local`) works the same way.

## Publishing connections (YouTube)

A user can connect one YouTube channel (`app/models/publishing_connection.py`, `app/services/publishing/`). Only the OAuth **refresh token** is kept, sealed with **AES-256-GCM** (`cryptography`) under `PUBLISHING_TOKEN_ENCRYPTION_KEY`; the associated data binds each ciphertext to its user, provider and key version, so a token copied to another row cannot be opened. Access tokens are never stored. Keys come only from the environment or a secret manager.

- **Rotation:** set a new key with a higher `PUBLISHING_TOKEN_KEY_VERSION` and list the old one in `PUBLISHING_TOKEN_PREVIOUS_KEYS` (`1:<key>`); old tokens keep working and are re-encrypted with the current key the next time they are used.
- **Disconnect** revokes the token with the provider on a best-effort basis and always deletes it locally.
- `YOUTUBE_PUBLISHING_ENABLED=true` refuses to start without a valid key (validated by setting name, never value).

**Connecting** (`app/api/publishing.py`, `app/services/publishing/youtube_oauth.py`, Google's official `google-auth-oauthlib`):

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/publishing/youtube` | yes | `{enabled, connection: {provider, status, account_title, connected_at} \| null}` — never tokens |
| POST | `/publishing/youtube/connect` | yes | `{authorization_url}`: Google's consent page (rate limited `oauth_start`, 10/hour); `409` when publishing is disabled |
| GET | `/publishing/youtube/callback` | cookie | Google's redirect target. Always answers `303` to the frontend's fixed `/settings?youtube=connected` or `/settings?youtube=error&reason=<code>` (`denied`, `invalid_state`, `expired`, `signin_required`, `missing_refresh_token`, `insufficient_scope`, `exchange_failed`, `disabled`) |
| DELETE | `/publishing/youtube` | yes | Revoke with Google (best effort) and delete: `{revoked_with_provider}` |

- **Least privilege:** the only scope is `https://www.googleapis.com/auth/youtube.upload` (upload; it cannot read, change or delete videos). No OpenID scope is requested, so the channel name appears once the first upload reports it.
- **Authorization code + PKCE (S256)**, `access_type=offline` and `prompt=consent` so a refresh token is issued. The `state` is 32 random bytes, stored only as a SHA-256 hash with the encrypted PKCE verifier, bound to the user who started, valid for 10 minutes and deleted atomically on first use (`oauth_states`); a replayed, forged, expired or another user's state is refused before any exchange.
- The code is exchanged server-side; the refresh token is stored encrypted, the access token discarded. Neither ever reaches the browser, a URL or a log; redirects carry `Referrer-Policy: no-referrer` and go only to the configured frontend.

**Publish jobs** (`app/models/publish_job.py`, `app/services/publishing/metadata.py`, `jobs.py`): a job is the user's explicit request to upload one **READY** edit through a `connected` account with the metadata they reviewed. Metadata follows YouTube's documented rules and is **refused with the field named, never truncated**: title 1–100 characters, description ≤ 5000 bytes, tags ≤ 500 characters as YouTube counts them (quotes around tags with spaces, commas between), at most 50 tags, no `<`/`>` or control characters; privacy `private` (default), `unlisted` or `public`; an explicit "made for kids" declaration (default no). The dialog's prefill is the clip candidate's own title and hook — no AI. A SHA-256 fingerprint over the connection, edit and metadata makes the request idempotent: asking again (even concurrently) returns the same job instead of uploading twice.

**Provider contract** (`app/services/publishing/provider.py`): the pipeline sees only `authorize` (refresh token → a short-lived opaque credential, never stored), `start_upload` (a resumable session URI — a secret, stored encrypted), `upload_chunk` / `query_upload` (bytes the provider has *confirmed*, so an interrupted upload resumes exactly where the provider stopped and the video is created once) and `video_status`. Every failure is one of `authentication_required`, `permission_denied`, `quota_exceeded`, `rate_limited`, `invalid_metadata`, `upload_session_expired`, `network_error`, `provider_error`, `processing_failed`, with a user-safe message and a retry decision (only rate limiting, network and provider errors and an expired session are retryable). `PUBLISHING_PROVIDER=fake` selects an in-memory simulation (`fake.py`; video ids `fake-…`, labelled simulated) for tests and non-production stacks; production refuses it.

**YouTube upload** (`app/services/publishing/youtube.py`, `uploader.py`): Google's documented resumable `videos.insert`. `POST …/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status` with the metadata (title, description, tags, category, `privacyStatus`, `selfDeclaredMadeForKids`) returns the session URI (stored encrypted); `PUT` with `Content-Range: bytes a-b/total` sends `YOUTUBE_UPLOAD_CHUNK_BYTES` (default 8 MiB, a multiple of 256 KiB as Google requires) and `308 Range: bytes=0-N` says what YouTube stored; `PUT` with `bytes */total` asks where an interrupted upload stands. The loop always resumes from YouTube's confirmed offset, reports only confirmed bytes (monotonic), checks attempt ownership before every chunk and retries only retryable failures, at most five times in a row with exponential backoff. Access tokens come from the refresh token through `google-auth` per job (`invalid_grant` becomes `authentication_required`). Google's HTTP status and `reason` map to the normalized codes; Google's messages, the session URI and tokens never leave the module or reach a log (HTTP client loggers stay at WARNING as well). Processing status needs a read scope this integration does not request, so it is reported as unknown and the job ends honestly at **uploaded**.

**The pipeline** (`app/services/publishing/pipeline.py`, Celery `peaksift.publish_short` and `peaksift.check_publish_status`, ids only):

```
queued → preparing   claim (fencing token); the edit must still be READY with its file present;
                      the connection must exist and be connected; refresh token decrypted
       → uploading   authorize; open the resumable session and STORE IT (encrypted, bound to the
                      job) BEFORE sending a byte; stream the short from storage in ranged chunks
       → uploaded    video id recorded, session secret deleted, channel name learned (100 %)
       → processing → published      countdown status checks (PUBLISH_STATUS_POLL_SECONDS,
                      at most PUBLISH_STATUS_MAX_POLLS); YouTube's upload-only scope cannot read
                      processing, so YouTube jobs end honestly at "uploaded"
failed               PeakSift could not finish (network, quota, metadata, account...): retryable;
                      the session is kept so the retry resumes it
provider_failed      YouTube rejected or could not process the video
```

- **No duplicates:** a killed worker, a crash after the last byte, a retry or a redelivered message all resume the stored session (YouTube reports the video if it already exists); a job with a video id is never uploaded again. An expired session (no video yet) is replaced once per attempt.
- **Accounts:** `authentication_required` (revoked or expired consent, or a token no configured key can open) marks the connection `needs_reconnect`; a disconnected account fails the job (`not_connected`).
- Every commit checks the attempt token; a superseded attempt stops without writing. Settings: `PUBLISH_STALE_AFTER_SECONDS` (15 min), `PUBLISH_MAX_ATTEMPTS` (5), `PUBLISH_STATUS_POLL_SECONDS` (30), `PUBLISH_STATUS_MAX_POLLS` (20).

**Publishing API** (`app/api/publish_jobs.py`; owner-scoped — `404` for anyone else, `401` signed out; never tokens, session URIs, task ids or storage keys):

| Method | Path | Description |
| --- | --- | --- |
| GET | `/edits/{edit_id}/publish` | `{enabled, connection, edit_ready, defaults, jobs}`: the dialog's prefill (candidate title and hook, private, no tags) and this edit's publish history |
| POST | `/edits/{edit_id}/publish` | Body `{title, description, tags, privacy, made_for_kids}` → `201` new queued job, or `200` with the existing job for the same request (never a second upload). `422` names the field breaking YouTube's rules; `409` when the edit is not ready, no account is connected or it needs reconnecting, or publishing is disabled; `503` when the queue is down (no job is left behind). Rate limited (`publish_start`, 30/hour) |
| GET | `/publish-jobs/{job_id}` | Status, real progress (`bytes_uploaded`/`bytes_total`), `video_url` (`https://youtu.be/…`) and `studio_url` once YouTube created the video (`simulated` and no link for the fake provider), `error_code`/`error_message`, `retryable`, `is_stale`, `awaiting_processing` (a processing check is still due; false once processing is known — or unknowable with the upload-only scope) |
| POST | `/publish-jobs/{job_id}/retry` | Only a job that `failed` before YouTube created a video, or a stalled one, up to `PUBLISH_MAX_ATTEMPTS`; resumes the stored session. A job with a video is never uploaded again (`409`) |

## Security headers

Every API response (`app/core/security_headers.py`, pure ASGI so streaming is untouched) carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; sandbox` (the API serves data and media, never pages), `Cross-Origin-Resource-Policy: same-site`, a restrictive `Permissions-Policy`, `Cache-Control: no-store` unless an endpoint sets its own (media keeps `private, no-store`), and HSTS in production. The frontend sends its own CSP (see `frontend/lib/security-headers.ts`); the reverse proxy adds HSTS for every page.

## Rate limits

Redis fixed-window budgets, answered with `429 Too Many Requests` and `Retry-After` (seconds) once spent:

| Name | Default | Subject | Endpoints |
| --- | --- | --- | --- |
| `login_ip` / `login_account` | 20 per minute / 10 per 15 minutes | client address / account (email, case-insensitive) | `POST /auth/login` |
| `register_ip` | 10 per hour | client address | `POST /auth/register` |
| `video_upload` / `audio_upload` / `visual_upload` | 30 / 100 / 200 per hour | user | video, audio and visual uploads |
| `broll_suggest` | 60 per hour | user | B-roll suggestions: start and retry |
| `visual_search` | 600 per hour | user | searching a project's visuals (each new query embeds its text once) |
| `visual_analysis` | 100 per hour | user | retrying a visual's analysis for visual search |
| `auto_edit` | 60 per hour | user | Auto Edit plans: create, retry, regenerate (apply counts as `edit_render`) |
| `transcription`, `clip_detection` | 30 per hour each | user | start and retry |
| `clip_render`, `edit_render` | 200 per hour each | user | start and retry (an edit request counts even when it returns an existing edit) |
| `reframe`, `caption_timing` | 100 per hour each | user | start and retry |
| `oauth_start` / `publish_start` | 10 / 30 per hour | user | YouTube connect / publish and retry |

- The client address is the one `ProxyHeadersMiddleware` derives from `TRUSTED_PROXIES` only; an untrusted peer cannot rotate identities with forged `X-Forwarded-For`.
- Subjects are hashed before they reach Redis (no emails or addresses in clear). Authentication runs first, so anonymous requests to user-limited endpoints are `401`, not counted.
- `RATE_LIMITS="login_ip=20/60,edit_render=200/3600"` overrides budgets (unknown names or bad values refuse to start). `RATE_LIMIT_ENABLED` exists only so tests can switch limits off; production refuses to start without them.
- **Fail closed:** if Redis cannot be reached, a limited endpoint answers `503` instead of running unlimited; readiness reports the same outage.

## Logs and request ids

- Every response carries **`X-Request-ID`** (a well-formed incoming id from the proxy is kept; anything else is replaced). Every log line written while handling the request carries it, and a job enqueued by that request carries it to the worker, whose lines add `task` and `job_id` — one id follows a creator's click from the proxy to the render.
- **`LOG_FORMAT=json`** (the production default) writes one JSON object per line (`ts`, `level`, `logger`, `message`, `request_id`, `task`, `job_id`, `exception`); `text` is the development default. `LOG_LEVEL` defaults to `INFO`.
- **Redaction** runs on every record from every logger (ours, uvicorn, gunicorn, Celery, libraries) and on tracebacks: OpenAI keys, Google OAuth codes, access and refresh tokens and client secrets, AWS key ids, JWTs and Bearer tokens, `Authorization`/cookie/password/secret/token/key values, credentials in URLs, OAuth `code`/`state` and `X-Amz-*`/`upload_id` query parameters, and local media and scratch paths (FFmpeg stderr names them).
- The access line (`app.access`: method, **path without the query string**, status, duration) replaces uvicorn's and gunicorn's access logs, which are muted because query strings can carry OAuth codes. Health-probe requests are logged at `DEBUG`.

## Backups and restore tests

```bash
python -m app.cli.backup create /backups/2026-10-17 --copy-media   # dump + manifest + media copy
python -m app.cli.backup create /backups/2026-10-17 --upload       # …and copy it to BACKUP_S3_*
python -m app.cli.backup verify /backups/2026-10-17                # checksums + pg_restore --list
python -m app.cli.backup restore-test /backups/2026-10-17          # prove it restores, then clean up
```

- **`create`** writes a new directory (owner-only): `database.dump` (`pg_dump` custom format, no owners or privileges, `--lock-wait-timeout` so a locked table fails the backup quickly instead of hanging it) and `manifest.json` — format, application version, Alembic revision, dump size and SHA-256, every table's row count, and the database-referenced media inventory. `--copy-media` copies each object into `media/<key>` with its SHA-256; `--upload` copies the whole backup to the secondary bucket configured by `BACKUP_S3_*` (another account or region), under `backups/<name>/`.
- **`verify`** recomputes the dump's size and checksum, asks `pg_restore` to read the archive, reports objects that were already missing when the backup was made, and re-checks every media copy.
- **`restore-test`** restores into a **temporary database** on the same server (`peaksift_restore_<random>`), checks the schema revision, every table's row count and that the restored rows reference exactly the backed-up media, restores the media into a **temporary bucket** (or a temporary directory when the key cannot create buckets, or for local storage) and re-checks each SHA-256, then drops the database and removes the bucket or directory. Exit status is non-zero if anything does not match.
- Passwords reach `pg_dump`/`pg_restore` only through the environment, never their arguments; output and manifests contain no credentials. `pg_dump`'s major version must be at least the server's (the production image ships the PostgreSQL 16 client).
- **Real restore** (disaster recovery): create an empty database, `pg_restore --no-owner --no-privileges --dbname <db> database.dump`, copy `media/` back with `python -m app.cli.media migrate --from local --to s3` (pointing `MEDIA_ROOT` at the backup's `media/`), then start the stack; `alembic upgrade head` brings an older backup to the current schema.

## Health checks

- **API:** point the load balancer or orchestrator's *liveness* probe at `/health/live` (restart if it fails) and its *readiness* probe at `/health/ready` (stop routing traffic while a dependency is down). Readiness checks run concurrently under a single deadline, so a hung dependency fails the probe quickly instead of hanging it.
- **Workers:** `python -m app.cli.health` checks PostgreSQL, Redis, media storage, the scratch directory and the media tools (FFmpeg and ffprobe with libass) and exits non-zero on any failure — use it as the worker container's healthcheck. `--ping` additionally requires at least one running worker to answer over the broker.
- Output is `name: ok|unavailable` only; the logs carry the exception type, never connection strings or credentials. The database connection itself times out after 5 seconds.

## Deleting media and cleaning up

Deletion is **rows first, files second**: the storage keys are captured, the rows are deleted in one commit, then the files are removed. A storage failure after the commit leaves *orphans* (files no row refers to); they are counted in the response, never returned to anyone, and removed by the cleanup command. A render still running for a deleted clip or edit notices its row is gone and stores nothing.

```bash
python -m app.cli.media cleanup                    # report only
python -m app.cli.media cleanup --apply            # remove
python -m app.cli.media cleanup --grace-hours 48   # default 24
```

`cleanup` considers, all **older than the grace period** (which must exceed the job time limit, so nothing in use is touched):
- **orphaned objects** in the configured media storage (including pre-V1.0 normalized transcription audio, now scratch-only; their `audio_storage_key` is cleared);
- **interrupted local writes** (`.*.part`) under `MEDIA_ROOT`;
- **stale scratch** under this host's `WORK_ROOT` (run it on every worker host, e.g. daily from cron).

On S3, also add a bucket lifecycle rule that aborts incomplete multipart uploads after a day.

## Structure

```
app/
  main.py            # FastAPI app, CORS, routers
  api/               # Routers: health, auth, projects, videos, video_content, transcriptions, clip_detection,
                     # clips, clip_media, clip_edits (+ edit media), reframe; media_streaming.py = shared Range streaming
  core/config.py     # Settings from environment variables
  core/database.py   # Engine, session factory, `get_db` dependency, declarative Base
  core/security.py   # Password hashing and access-token encode/decode
  models/            # SQLAlchemy models: User, Project, Video, Transcription(+Segment), ClipDetectionRun, ClipCandidate, Clip, ClipEdit, ReframeAnalysis(+Keyframe)
  schemas/           # Pydantic request/response schemas
  services/storage.py # Storage contract: local directory or private S3 bucket; safe keys, ranged reads
  services/workspace.py # Per-attempt local scratch (WORK_ROOT) for jobs and uploads
  services/media_migration.py # Copy/verify media between backends (database-referenced keys)
  services/media_deletion.py # Project/edit/audio deletion: rows first, then files, failures counted
  services/media_cleanup.py  # Orphan, partial-write and stale-scratch cleanup
  cli/media.py       # `python -m app.cli.media migrate|verify|cleanup`
  cli/health.py      # `python -m app.cli.health [--ping]`: worker/host diagnostics
  services/health.py # Readiness checks (database, Redis, storage, scratch, media tools)
  services/video_upload.py     # Upload validation (filename, extension, MIME, size) and storage
  services/ffprobe.py          # ffprobe invocation (argument list, JSON, timeout) and parsing
  services/video_processing.py # uploaded -> processing_metadata -> ready | failed
  services/audio_extraction.py # ffmpeg -> mono 16 kHz 64 kbps MP3 under transcription/<id>/
  services/transcription/      # Contract, factory, chunking, pipeline, faster_whisper + openai providers
  services/clip_render/        # Artifact storage, FFmpeg renderer, Celery render pipeline
  services/clip_edit/          # Edit config, 9:16 composition, smart/manual crops, captions + styles, edit artifacts, pipeline
  services/reframe/            # Smart reframing: config, sampling, detector contract + YuNet, tracking, crop path, pipeline
  services/audio_assets.py     # Audio uploads: validation by content, probing, sha256, waveform peaks
  services/audio_mix/          # Audio section config, FFmpeg mix plan, ducking presets, loudness, mixer
  services/caption_timing/     # Word timing: config, provider contract + validation, faster-whisper words, pipeline
  services/clip_detection/     # Contract + schema, prompt, factory, ollama + openai providers, windowing,
                               # validation, ranking, detection_config, pipeline
  workers/celery_app.py        # Celery app (Redis broker) and long-job semantics
  workers/transcription_tasks.py # Background tasks (ids only cross the broker)
  workers/clip_detection_tasks.py # peaksift.detect_clips
  workers/clip_render_tasks.py # peaksift.render_clip
  workers/clip_edit_tasks.py   # peaksift.render_clip_edit
  workers/reframe_tasks.py     # peaksift.analyze_reframe
  workers/caption_tasks.py     # peaksift.generate_caption_track
  workers/dispatch.py          # enqueue helpers (pre-chosen task ids); broker outage -> JobQueueUnavailable
alembic/             # Migration environment and versions/
scripts/             # celery_smoke.py, fetch_reframe_model.py, smart_crop_probe.py, caption_font_probe.py, dynamic_caption_probe.py, audio_mix_probe.py
tests/               # pytest suite (conftest.py holds the DB fixtures)
```

## Configuration

Settings are read from environment variables, or from `backend/.env` if present (see [.env.example](.env.example)):

| Variable            | Default                                        | Purpose                                      |
| ------------------- | ---------------------------------------------- | -------------------------------------------- |
| `APP_ENV`           | `development`                                  | Environment name                             |
| `FRONTEND_URL`      | `http://localhost:3000`                        | Origin allowed by CORS                       |
| `DATABASE_URL`      | *(required)*                                   | SQLAlchemy URL, `postgresql+psycopg://...`   |
| `TEST_DATABASE_URL` | `postgresql+psycopg://localhost:5432/peaksift_test` | Database used by `pytest` only          |
| `SECRET_KEY`        | *(required, ≥ 32 chars)*                       | Signs auth tokens. Generate: `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` (7 days)                     | Login lifetime                               |
| `MEDIA_ROOT`        | `./media`                                      | Directory for uploaded media (local development storage; git-ignored) |
| `STORAGE_BACKEND`   | `local`                                        | `local` (`MEDIA_ROOT`) or `s3` (private bucket; `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_PATH_STYLE`, `S3_SECURE`) |
| `LOG_FORMAT` / `LOG_LEVEL` | `json` in production, else `text` / `INFO` | Log format and level; secrets are always redacted |
| `WORK_ROOT`         | system temp `peaksift-work`                    | Local scratch for jobs and uploads being validated; per-attempt directories, removed when they end. Absolute in production |
| `MAX_VIDEO_UPLOAD_BYTES` | `2147483648` (2 GiB)                      | Largest accepted source video                |
| `AUDIO_UPLOAD_MAX_BYTES` | `104857600` (100 MiB)                   | Largest accepted music or sound-effect file  |
| `AUDIO_UPLOAD_MAX_DURATION_SECONDS` / `AUDIO_SFX_MAX_DURATION_SECONDS` | `1200` / `30` | Longest music track / sound effect |
| `VISUAL_ASSET_MAX_BYTES` | `524288000` (500 MiB) | Largest accepted image or B-roll video |
| `VISUAL_ASSET_MAX_VIDEO_DURATION_SECONDS` | `600` | Longest B-roll video |
| `VISUAL_ASSET_MAX_PIXEL_COUNT` / `VISUAL_ASSET_MAX_VIDEO_PIXEL_COUNT` | `40000000` / `9437184` | Largest image (checked before decoding) / B-roll video resolution (4096 × 2304) |
| `BROLL_SUGGESTION_PROVIDER` / `BROLL_OLLAMA_MODEL` / `BROLL_FALLBACK_ENABLED` | `ollama` / first `OLLAMA_CLIP_MODELS` entry / `true` | Who suggests B-roll moments: a local model, or the deterministic name-based provider; the fallback answers (labelled) when the model cannot |
| `BROLL_STALE_AFTER_SECONDS` / `BROLL_MAX_ATTEMPTS` | `900` / `5` | When a running B-roll analysis counts as stalled / how many attempts a retry may reach |
| `FFPROBE_PATH`      | `ffprobe`                                      | ffprobe binary (name on `PATH` or absolute path) |
| `FFPROBE_TIMEOUT_SECONDS` | `30`                                     | Time limit for probing one file; exceeding it marks the video `failed` |
| `FFMPEG_PATH`       | `ffmpeg`                                       | ffmpeg binary for audio extraction, clip rendering and shorts (needs libass for captions) |
| `AUDIO_EXTRACTION_TIMEOUT_SECONDS` | `3600`                          | Time limit for extracting one video's audio  |
| `TRANSCRIPTION_CHUNK_SECONDS` | `600`                                | Fixed chunk length for long audio (min 30)   |
| `TRANSCRIPTION_PROVIDER_MAX_ATTEMPTS` | `3`                           | Attempts per chunk for *transient* provider errors |
| `TRANSCRIPTION_RETRY_BACKOFF_SECONDS` | `2`                           | Base backoff (doubles per attempt)           |
| `TRANSCRIPTION_STALE_AFTER_SECONDS` | `1800`                          | Heartbeat age after which a running job is considered dead |
| `TRANSCRIPTION_PROMPT_TAIL_CHARS` | `200`                             | Previous-chunk text passed as prompt (0 disables) |
| `TRANSCRIPTION_TIMESTAMP_TOLERANCE_SECONDS` | `1.5`                   | Allowed segment overrun past a chunk's end   |
| `TRANSCRIPTION_PROVIDER` | `faster_whisper`                          | Speech-to-text provider: `faster_whisper` or `openai` (server choice, never client input) |
| `FASTER_WHISPER_MODEL` | `small`                                     | Whisper model size/path (`tiny`, `base`, `small`, `medium`, `large-v3`, …) |
| `FASTER_WHISPER_DEVICE` | `cpu`                                      | `cpu` or `cuda` (no Apple-GPU path; CPU is the macOS mode) |
| `FASTER_WHISPER_COMPUTE_TYPE` | `int8`                               | CTranslate2 compute type (`int8` on CPU, `float16` on CUDA) |
| `FASTER_WHISPER_BEAM_SIZE` | `5`                                     | Decoding beam size                           |
| `OPENAI_API_KEY`    | empty                                          | Required only when `TRANSCRIPTION_PROVIDER=openai`; never committed |
| `OPENAI_TIMESTAMP_MODEL` | `whisper-1`                                | Timestamp-capable model used by the pipeline |
| `OPENAI_TRANSCRIPTION_MODEL` / `OPENAI_HIGH_ACCURACY_MODEL` | `gpt-4o-mini-transcribe` / `gpt-4o-transcribe` | Hosted text-only options (recorded, not used for timing) |
| `OPENAI_TIMEOUT_SECONDS` | `600`                                      | Per-request timeout                          |
| `OPENAI_MAX_UPLOAD_BYTES` | `20971520` (20 MB)                        | Per-chunk upload guard below the 25 MB API limit |
| `CLIP_DETECTION_OLLAMA_ENABLED` | `true`                            | Offer the local clip-analysis provider        |
| `OLLAMA_BASE_URL`   | `http://localhost:11434`                       | Ollama-compatible endpoint (server configuration only) |
| `OLLAMA_CLIP_MODELS` | `llama3.2:3b`                                 | Allowed local models (comma-separated; first = default) |
| `OLLAMA_CONNECT_TIMEOUT_SECONDS` / `OLLAMA_TIMEOUT_SECONDS` / `OLLAMA_NUM_CTX` | `5` / `300` / `8192` | Per-request timeouts and context window |
| `OPENAI_CLIP_MODELS` | `gpt-5-mini,gpt-5`                            | Allowed hosted clip-analysis models (needs `OPENAI_API_KEY`) |
| `OPENAI_CLIP_TIMEOUT_SECONDS` / `OPENAI_CLIP_MAX_OUTPUT_TOKENS` | `120` / `4000` | Per-request limits for hosted analysis |
| `CLIP_DETECTION_WINDOW_SECONDS` / `_OVERLAP_SECONDS` / `_MAX_CHARS` / `_MAX_WINDOWS` | `300` / `20` / `8000` / `500` | Analysis windows |
| `CLIP_DETECTION_MIN_CLIP_SECONDS` / `_MAX_CLIP_SECONDS` | `15` / `90`              | Accepted candidate length                    |
| `CLIP_DETECTION_TARGET_CANDIDATES` / `_CANDIDATES_PER_WINDOW` | `10` / `3`         | Results kept per run / asked per window      |
| `CLIP_DETECTION_OVERLAP_THRESHOLD` | `0.5`                           | IoU above which candidates are duplicates    |
| `CLIP_DETECTION_TIMESTAMP_TOLERANCE_SECONDS` | `1`                   | Allowed overrun past the video end           |
| `CLIP_DETECTION_PROVIDER_MAX_ATTEMPTS` / `_RETRY_BACKOFF_SECONDS` | `3` / `2`      | In-task retries for transient provider errors |
| `CLIP_DETECTION_STALE_AFTER_SECONDS` | `900`                         | Heartbeat age after which a running detection counts as dead |
| `CLIP_DETECTION_MAX_ATTEMPTS` | `5`                                  | User retries per run before a new detection is required |
| `CLIP_RENDER_PRESET` / `CLIP_RENDER_CRF` / `CLIP_AUDIO_BITRATE` | `veryfast` / `20` / `128k` | libx264 preset and quality, AAC bitrate for generated clips |
| `CLIP_RENDER_TIMEOUT_SECONDS` | `1800`                              | Kill FFmpeg after this long                  |
| `CLIP_RENDER_DURATION_TOLERANCE_SECONDS` / `CLIP_RENDER_SOURCE_TOLERANCE_SECONDS` | `1` / `1` | Accepted rendered-duration difference / overrun past the source end |
| `CLIP_RENDER_HEARTBEAT_SECONDS` / `CLIP_RENDER_STALE_AFTER_SECONDS` | `15` / `900` | Render heartbeat interval / age after which a render counts as dead |
| `CLIP_RENDER_MAX_ATTEMPTS` | `5`                                     | Retries per clip and per edit (the other `CLIP_RENDER_*` values apply to shorts too) |
| `CAPTION_FONT_FAMILY` | `Noto Sans`                                  | Caption font family for shorts (plain name; resolved by fontconfig, with fallbacks) |
| `CAPTION_MAX_WORDS` / `CAPTION_MAX_CHARS` | `7` / `32`               | Caption cue limits                           |
| `CAPTION_TIMING_PROVIDER` | `faster_whisper`                         | Word-timing provider (allow-listed; reuses the `FASTER_WHISPER_*` model settings) |
| `CAPTION_TIMING_TOLERANCE_SECONDS` | `0.25`                          | How far past the clip audio a word may end before the result is refused |
| `CAPTION_TIMING_STALE_AFTER_SECONDS` / `CAPTION_TIMING_MAX_ATTEMPTS` | `900` / `5` | Stale threshold and retries for word timing |
| `REFRAME_DETECTOR` / `REFRAME_MODEL_PATH` | `yunet_face` / `./models/face_detection_yunet_2023mar.onnx` | Face detector and its pinned model file (install with `scripts/fetch_reframe_model.py`) |
| `REFRAME_SAMPLE_FPS` / `REFRAME_ANALYSIS_WIDTH` / `REFRAME_MIN_DETECTION_CONFIDENCE` | `2` / `640` / `0.5` | Frames analysed per second, detection width, score threshold |
| `REFRAME_FACE_MARGIN` / `REFRAME_DEAD_ZONE` | `0.12` / `0.10`          | Face-to-edge margin and tolerated drift, in crop widths |
| `REFRAME_SMOOTHING_SECONDS` / `REFRAME_MAX_PAN_PER_SECOND` / `REFRAME_MAX_GAP_SECONDS` | `0.5` / `0.35` / `1.5` | Camera smoothing, pan-speed limit, how long a lost face keeps steering |
| `REFRAME_SAMPLING_TIMEOUT_SECONDS` / `REFRAME_HEARTBEAT_SECONDS` / `REFRAME_STALE_AFTER_SECONDS` / `REFRAME_MAX_ATTEMPTS` | `600` / `15` / `900` / `5` | Sampling deadline, liveness, stale threshold, retries |
| `REDIS_URL`         | `redis://localhost:6379/0`                     | Celery broker                                |
| `CELERY_TASK_SOFT_TIME_LIMIT_SECONDS` | `21600` (6 h)                | Soft limit for one background job            |
| `CELERY_TASK_TIME_LIMIT_SECONDS` | `22200`                           | Hard limit for one background job            |
| `CELERY_TASK_ALWAYS_EAGER` | `false`                                 | Run tasks inline (tests only)                |
