# Clip generation (Milestone 5)

How PeakSift turns an AI clip candidate into a real, downloadable MP4. This page is the reference for operators and contributors; the end-user walkthrough is at the end.

## What it does — and does not — do

**Generate clip** on a candidate renders exactly that candidate's validated time range from the original upload into a private MP4, in a background worker, validates the result with ffprobe, and lets the owner preview and download it.

V0.5 keeps the source's **aspect ratio, resolution and orientation**. It does **not** reframe to 9:16, crop, track faces, burn in captions, add music or sound effects, apply templates or watermarks, trim interactively, or publish anywhere. Vertical 9:16 shorts with captions are built on top of these clips in V0.6 — see [short-form-editing.md](short-form-editing.md); the clip itself stays unchanged.

## Pipeline

```
POST …/candidates/{candidate_id}/clip            (no body; boundaries come from the candidate row)
  → re-validate the candidate's [start, end] against the source duration
  → Clip row (queued, boundary snapshot, render_profile source_mp4_v1, pre-chosen Celery task id)
  → enqueue peaksift.render_clip(clip_id)  →  201 at once  (200 + existing clip on a repeat click)

Worker (app/services/clip_render/pipeline.py):
  claim (DB state + fencing token); discard any stale temp or orphaned final file
  → rendering   ffmpeg → clips/<clip-id>/clip-tmp-<attempt>.mp4, heartbeat every 15 s   (progress 10)
  →             ffprobe validation of the temp file                                        (80)
  → validating  ownership re-checked                                                       (90)
  → atomic rename to clips/<clip-id>/clip.mp4, then ONE commit: storage_key + metadata + ready (100)
  | failed      error_code + safe error_message; every temp and final file removed
```

`ready` therefore always means *a validated file exists at the final location*. If the row ever says `ready` but the file is gone, the API reconciles it to `failed` / `artifact_missing`, which can be retried.

## Data model

`clips` (one row per rendered candidate):

| Column | Meaning |
| --- | --- |
| `candidate_id` | FK → `clip_candidates`, cascade, **unique** — at most one clip per candidate |
| `video_id` | FK → `videos`, cascade |
| `status` | `queued` → `rendering` → `validating` → `ready` \| `failed` (separate from video and detection-run status) |
| `progress_percent`, `attempt` | honest stage progress (0/10/80/90/100); attempts start at 1 and grow with each retry |
| `start_time`, `end_time`, `duration_seconds` | snapshot of the candidate's boundaries at creation (checked: start ≥ 0, end > start, duration = end − start) |
| `render_profile` | `source_mp4_v1` — the only profile in V0.5; later layouts get new names |
| `storage_key`, `celery_task_id` | internal only, never returned |
| `content_type`, `file_size`, `width`, `height`, `fps`, `video_codec`, `audio_codec` | validated output metadata, filled when ready |
| `error_code`, `error_message` | safe failure details (no paths, commands or stack traces) |
| timestamps | created/updated/started/completed/heartbeat, timezone-aware |

Deleting a candidate or a video removes its clips. A render failure never modifies the source video, transcript, candidate or detection run.

## Rendering (`renderer.py`)

Canonical output, profile `source_mp4_v1`:

- MP4 container with `-movflags +faststart` (playable while downloading)
- H.264 via **libx264**, `yuv420p`, `CLIP_RENDER_PRESET` / `CLIP_RENDER_CRF` (default `veryfast` / 20)
- AAC at `CLIP_AUDIO_BITRATE` (128k) **when the source has audio**; video-only sources render video-only
- the source's resolution and aspect ratio; rotation metadata is applied while decoding, so phone footage comes out upright with no leftover rotation tag; odd dimensions are rounded down by one pixel because `yuv420p` requires even sizes — no other scaling, no crop, no padding
- subtitle/data streams and container metadata are dropped

**Accuracy.** The clip is re-encoded, never stream-copied. `-ss` is placed before `-i`, so FFmpeg seeks to the preceding keyframe and decodes forward to the exact time: the first frame is the first one at or after the candidate start (within one frame interval, e.g. ≤ 40 ms at 25 fps). Stream copy (`-c copy`) would snap to keyframes and could start seconds early. After rendering, ffprobe must confirm H.264 video, a real picture size, AAC iff the source had audio, and a duration within `CLIP_RENDER_DURATION_TOLERANCE_SECONDS` (1 s) of the request; otherwise the output is rejected and deleted.

FFmpeg runs as an argument list (never a shell) with stdin closed and stderr written to a temp file; only a bounded tail is logged for operators, with source and output paths replaced by `<source>` / `<output>`. The process is killed on timeout (`CLIP_RENDER_TIMEOUT_SECONDS`, 1800) and on any abnormal exit from the wait loop. CPU encoding is the default and the only tested path; no GPU or Apple hardware encoder is required.

## Reliability

- **Idempotent on database state:** a ready clip is never re-rendered; a live render (fresh heartbeat) is never started twice; a failed clip only re-runs after the retry endpoint resets it; duplicate Celery deliveries are no-ops.
- **One clip per candidate:** enforced by the unique constraint *and* the API; a double click or a concurrent request receives the existing clip.
- **Fencing:** the task id is generated and committed on the row before enqueueing. Every pipeline commit re-reads it; a worker that a retry has taken over stops at its next heartbeat (FFmpeg is killed), never writes the row and only removes its own temp file. Each attempt renders into its own temp file.
- **Stale jobs:** a `rendering`/`validating` clip whose heartbeat is older than `CLIP_RENDER_STALE_AFTER_SECONDS` (900) is reported `is_stale` and can be retried; a redelivered task reclaims it.
- **Retry:** failed or stale clips only, same clip id, up to `CLIP_RENDER_MAX_ATTEMPTS` (5).
- **Failure codes:** `source_missing`, `source_unreadable`, `video_not_ready`, `invalid_range`, `ffmpeg_missing`, `ffmpeg_failed`, `render_timeout`, `invalid_output`, `storage_failure`, `time_limit`, `artifact_missing`, `queue_unavailable`, `internal_error`.

## Storage

Rendered clips are private derived files under `MEDIA_ROOT`:

```
clips/<clip-uuid>/clip-tmp-<attempt>.mp4   while rendering/validating
clips/<clip-uuid>/clip.mp4                 the validated artifact
```

Only a real UUID can name a clip directory, every path is resolved through `LocalStorageProvider.path_for` (which refuses traversal and symlink escapes), and nothing under `MEDIA_ROOT` is served statically. Candidate titles, filenames, project or user names never become paths.

## API

All routes need the session cookie and are owner-scoped; anything else is `404` (`401` without a session). Responses never include storage keys, filesystem paths, task ids or FFmpeg commands.

| Method | Path | Description |
| --- | --- | --- |
| POST | `/projects/{id}/videos/{video_id}/clip-detection/{run_id}/candidates/{candidate_id}/clip` | Generate. `201` new clip; `200` existing queued/rendering/validating/ready clip; `409` failed clip (use retry), dismissed candidate (restore first), video not ready, or boundaries outside the source; `503` queue down (no row left). Any request body is ignored. |
| GET | `…/candidates/{candidate_id}/clip` | Clip state (`404` before generation). |
| POST | `…/candidates/{candidate_id}/clip/retry` | Re-queue a failed or stale clip (`409` otherwise or after the attempt limit). |
| GET | `/projects/{id}/videos/{video_id}/clips?offset&limit(1–100)` | The video's clips, newest first. |
| GET | `/clips/{clip_id}/content` | Inline `video/mp4` for `<video>`; `Accept-Ranges: bytes`; `206` with `Content-Range` for a byte range (including suffix ranges); `416` for an unsatisfiable range; `404` unless ready. |
| GET | `/clips/{clip_id}/download` | The same bytes as `Content-Disposition: attachment; filename="that-was-crazy-3f2c9a1e.mp4"` — an ASCII slug of the candidate title plus a short id. |

A clip is `{id, candidate_id, run_id, video_id, title, status, progress_percent, attempt, is_stale, start_time, end_time, duration_seconds, render_profile, content_type, file_size, width, height, fps, video_codec, audio_codec, error_code, error_message, created_at, started_at, completed_at}`.

Candidate decisions: `undecided` and `saved` candidates may be rendered; a `dismissed` candidate must be restored first. A clip that already exists is kept if its candidate is dismissed later.

Source preview and clip delivery share one Range implementation (`app/api/media_streaming.py`): 1 MiB chunked reads, `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `FFMPEG_PATH` / `FFPROBE_PATH` | `ffmpeg` / `ffprobe` | Binaries (shared with upload and transcription) |
| `CLIP_RENDER_PRESET` | `veryfast` | libx264 preset |
| `CLIP_RENDER_CRF` | `20` | libx264 quality (0–51, lower is better) |
| `CLIP_AUDIO_BITRATE` | `128k` | AAC bitrate |
| `CLIP_RENDER_TIMEOUT_SECONDS` | `1800` | Kill FFmpeg after this long |
| `CLIP_RENDER_DURATION_TOLERANCE_SECONDS` | `1` | Accepted difference between requested and rendered duration |
| `CLIP_RENDER_SOURCE_TOLERANCE_SECONDS` | `1` | A clip may end this far past the probed source duration |
| `CLIP_RENDER_HEARTBEAT_SECONDS` | `15` | Heartbeat interval while FFmpeg runs |
| `CLIP_RENDER_STALE_AFTER_SECONDS` | `900` | Heartbeat age after which a render counts as dead |
| `CLIP_RENDER_MAX_ATTEMPTS` | `5` | Retries per clip |

The FFmpeg build must provide the `libx264` and `aac` encoders (`ffmpeg -hide_banner -encoders`). Homebrew's and Ubuntu's `ffmpeg` packages do; CI fails if they are missing.

## Frontend

- Each candidate card has a **Generated clip** box: **Generate clip** → *Queued*, *Rendering…*, *Validating…* (with the backend's stage percentage, never animated) → the rendered clip, or *Render failed* with the safe message and **Retry render** (also offered for stalled renders). Dismissed candidates must be restored first.
- The page polls a clip every 4 s only while it is active and stops when it is ready or failed; state is re-read from the API on every load, so refresh and logout/login show the truth.
- A ready clip shows **Rendered clip** (native `<video>` on `/clips/{id}/content`, duration, resolution, size) and **Download MP4** (a plain link to `/download`; nothing is buffered in the browser). **Preview source** on the same card still plays the original range from the upload.
- **Generated clips** lists every clip of the video with its state and a download link.

## Testing

- Unit and integration tests with real FFmpeg and tiny generated sources (nothing committed): command shape, boundary validation, a black→white marker video proving the cut starts at the requested time, head/middle/tail cuts, video-only, WebM and MOV sources, a display-rotated recording rendered upright, odd dimensions, missing/corrupt sources, timeouts, FFmpeg failures, rejected outputs, the full pipeline (stages, idempotency, fencing, zombie isolation, stale reclaim, DB failure after finalize), the API, Range delivery and download names.
- End-to-end in CI: upload through the API → generate → eager Celery runs the real render → 200/206/416 delivery → download → ffprobe of the served bytes → no temp files left; and a failure → retry → ready.
- CI checks that FFmpeg provides libx264 and aac, and the worker smoke requires `peaksift.render_clip` to be registered. No API key, Ollama or model download is needed for any clip test.

## Known limitations (V0.5)

- Original aspect ratio only — no 9:16 reframing, vertical crop, blur background or face tracking.
- No captions, editor, trim adjustment, retitling, sound effects, music or templates.
- Fixed output: MP4 / H.264 / AAC, CPU encoding (`libx264`); no hardware encoders, no distributed render workers.
- Local filesystem storage only; no clip deletion, retention policy or render cancellation.
- Progress is stage-based (no FFmpeg frame progress); very short renders can finish between two polls.
- Cut accuracy is one frame at the start and ≤ 1 s on the validated duration, not sample-exact.
- No publishing integrations.

## Using it

1. Upload a video and wait for **Ready**.
2. **Transcribe video**.
3. **Find clip moments** in *AI clip detection*.
4. Review the candidates (**Preview source** plays the range in the original).
5. Click **Generate clip** on the one you want.
6. Wait for *Queued → Rendering → Validating*; the clip appears as **Rendered clip**.
7. Play it in the page to check it.
8. **Download MP4**.
