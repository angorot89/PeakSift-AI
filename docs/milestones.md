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

## Milestone 6 — Short-form Editing V0.6 *(complete)*

Delivered:

- Stale-worker ownership fix for transcription and clip detection: the attempt token is committed before enqueueing, every pipeline commit and the failure path re-check it, and each transcription attempt works in its own directory
- `clip_edits` table: edit variants of a generated clip (versioned, normalized config snapshot; unique per clip + config fingerprint), render status `queued → rendering → validating → ready | failed`, render profile `vertical_1080x1920_v1`, validated output metadata and caption cue count
- 9:16 composition at 1080 × 1920 with FFmpeg: **Center crop**, **Blur background**, **Fit** — aspect preserved, rotation applied, audio kept when present; filtergraphs from constants only
- Captions from the persisted transcript: clip-local timing, readable cue segmentation (proportional word timing within segments, phrase-level), long-token splitting, ASS escaping of untrusted text, three presets (Bold, Clean, Creator) and three positions (top, center, bottom), burned in with libass using Noto Sans; caption font probe
- Background edit pipeline on the existing worker (`peaksift.render_clip_edit`): attempt ownership, per-attempt workspaces, ffprobe validation, atomic finalize, stale detection, bounded retry, safe failure codes
- API: create (allow-listed options, deduplicated), list, status, retry; private Range-streamed preview and attachment download (`…-vertical-<id>.mp4`) — all owner-scoped
- Frontend: a dedicated short-form editor page — 9:16 stage with a labelled approximate preview (real transcript caption) or the rendered MP4, visual layout / caption-style / position selectors, render action with real states, rendered result with Download short, and versions named by their settings
- Product design: shared design tokens and components, app shell and dashboard polish, a project page organised as a workflow stepper plus numbered sections, ranked candidate cards, a compact generated-clip block, context-specific empty / working / error states; visually reviewed at 1440, 1024, 768 and 375 px
- Hardening (deleted rows, missing FFmpeg vs missing libass, font probe, unbreakable caption lines, emoji, disk errors, retry locking), CI (libass, layout filters and fonts gate; `REQUIRE_LIBASS=1`) and documentation ([short-form-editing.md](short-form-editing.md))

Definition of done — a user can open a generated clip → choose a layout → configure captions → Render short → watch queued/rendering/validating → preview the 9:16 MP4 → download it → render a second variant with other settings → log out and back in with every variant still there → recover from a render failure with retry, with the original clip unchanged.

## Milestone 7 — Smart Reframing V0.7 *(complete)*

PeakSift detects and tracks visible faces to generate a smooth vertical crop path, with centre and manual fallbacks.

Delivered:

- `reframe_analyses` / `reframe_keyframes` tables: one analysis per clip and server configuration (versioned snapshot + fingerprint), status `queued → sampling → detecting → tracking → planning → completed | failed`, statistics and confidence level, ordered keyframes in normalized display-oriented coordinates with crop-inside-frame constraints
- Frame sampling through one FFmpeg pipe (`fps=N:round=up`, scaled, rotation applied; no temporary files; watchdog timeout)
- Detector contract (faces found / no face / detector broken are distinct) and a local face detector: OpenCV Zoo YuNet (MIT weights) on onnxruntime (already a dependency), lazy, sha256-pinned model installed by an operator script — never downloaded automatically or committed. MediaPipe was evaluated first and not chosen (no bundled model, heavy dependencies, 128 × 128 short-range model); see [smart-reframing.md](smart-reframing.md)
- Deterministic tracking: association with gap interpolation and decaying holds, subject selection by size/persistence/confidence/centrality with switch hysteresis, hand-offs at shot changes
- Crop path planning: fixed 9:16 crop, dead zone, face margins, two-face group framing, look-ahead, exponential smoothing, pan-speed limit, centre fallback, camera cuts at hand-offs, keyframe simplification, documented confidence levels
- Background analysis on the existing worker (`peaksift.analyze_reframe`): attempt-token fencing, heartbeats and stale detection, one-transaction finalize, safe failure codes, bounded retry
- API: start (idempotent), list, current, status, crop path, retry — owner-scoped
- Rendering: `smart_reframe` edit layout — a time-varying FFmpeg crop compiled into a balanced expression tree (≤ 1000 segments), then 1080 × 1920 and captions fixed on screen; analysis reused across caption changes. `manual_crop` layout with a validated focal point
- Editor: Smart reframe layout with the analysis panel (real stages and progress, plain-language confidence, retry), path-driven live preview, keyboard-accessible focal-point picker; reviewed at 1440, 1024, 768 and 375 px
- Hardening (shot-change cuts, failure vs no-face copy, path-free messages, symlink containment, 4K/60 fps sampling), CI (smart-crop render probe, weights guard, Alembic cycle, type check) and documentation ([smart-reframing.md](smart-reframing.md))

Definition of done — a user can open a generated clip → select Smart reframe → analyze framing → watch real progress → see a confidence summary → preview the moving crop → render a 9:16 short with captions that follows the visible face → download it → fall back to a manual focal point when tracking is weak → recover from a failed analysis with retry.

## Milestone 8 — Dynamic Captions & Creator Polish V0.8 *(complete)*

PeakSift renders word-synced creator captions — the spoken word emphasised as it is said — from local speech timing, with creator presets, social safe areas and an opening hook.

Delivered:

- Polling robustness: a shared status-sync module (newer attempt > later stage > more progress) so render, edit and analysis status never moves backwards; first poll after 1 s, then every 4 s; frontend unit tests in CI (`npm test`)
- `caption_tracks` / `caption_words` tables: one track per clip and timing configuration (versioned `caption_alignment_v1` snapshot + fingerprint), status `queued → preparing_audio → aligning → validating → completed | failed`, clip-local words as recognized, rejected-word count and confidence; tracks are always real word timing (never proportional or generated)
- Word-timing provider contract and faster-whisper word timestamps (shared, lazily loaded model; never at import or startup); strict validation (refuse impossible timing, drop empty/tiny words, trim overlaps), repeated before every render
- Background word timing (`peaksift.generate_caption_track`): ids only, attempt-token fencing, heartbeats and stale detection, one-transaction finalize, safe failure codes, bounded retry; zero-word clips complete honestly
- API: start (idempotent), list, current, status, words, retry, timing options and caption preview — owner-scoped
- Word-aware cue builder (no LLM, no paraphrase): punctuation, pause, width, word and duration limits, readable minimum duration, no orphan words, balanced two-line layout from libass-measured glyph widths, grapheme-safe token splitting, active-word timing
- Renderer `caption_v2`: back-to-back word events with the active word recoloured and a continuous entrance; presets Focus, Punch, Minimal, Boxed; `caption_v1` kept for V0.6 styles and existing edits (fingerprints unchanged)
- General Social Safe Area v1 and Top / Center / Bottom placement inside it; opening hook (1–60 characters, 1–3 balanced lines, 0.5–5 s, Headline / Boxed / Minimal, Top / Center)
- Multilingual and emoji: bidi-correct Arabic and mixed RTL/LTR (`Encoding -1`), French and accents, monochrome emoji through a probed emoji font or left out — never tofu
- Editor: word-timing panel with text status, Generate / Retry and phrase fallback; preset cards; hook panel; safe-area guide; live preview of the renderer's own cues following the video clock, matching rendered frames in line breaks, size and position; reviewed at 1440, 1024, 768 and 375 px; reduced-motion aware
- Hardening (entrance continuity, cue churn in fast speech, model-path masking, injection fuzzing), CI (caption font probes for Latin / Arabic / emoji, end-to-end dynamic caption render probe) and documentation ([dynamic-captions.md](dynamic-captions.md))

Definition of done — a user can open a generated clip → generate word sync and watch its real progress → pick a caption preset, position and opening hook → preview the active word over the playing clip → render a 9:16 short with word-synced captions (with any layout or Smart reframe) → download it → fall back to phrase timing or retry when word timing fails.

## Roadmap status

- V0.1 Foundation — COMPLETE
- V0.2 Video Upload — COMPLETE
- V0.3 Transcription — COMPLETE
- V0.4 AI Clip Detection — COMPLETE
- V0.5 Clip Generation — COMPLETE
- V0.6 Short-form Editing — COMPLETE
- V0.7 Smart Reframing — COMPLETE
- V0.8 Dynamic Captions & Creator Polish — COMPLETE

No later milestone has been defined or started.

## Later (opportunities, not committed scope)

- Creator intelligence & metadata (titles, hooks, descriptions)
- Publishing integrations
- Sound effects and music
- Brand kits, custom fonts and a caption timing editor
- Global asset libraries
- Morocco Mode (localization layer extending Global). Before any Moroccan accuracy claim, benchmark Darija, Arabic/French code-switching, Moroccan names, local slang and noisy streamer audio — none of that has been tested yet.
- Additional localization
