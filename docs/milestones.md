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

## Milestone 9 — Audio & Sound Design V0.9 *(complete)*

Creators finish a short's audio in PeakSift: their own music and sound effects, automatic ducking under speech, and final loudness normalization.

Delivered:

- `audio_assets` table: private, project-scoped music and sound effects (allow-listed kind), sanitized display names, generated storage keys, probed metadata, sha256 duplicate reuse within a project, bounded waveform peaks
- Secure uploads (MP3, WAV, M4A, AAC, OGG, Opus): content validated with ffprobe (container matches extension, supported codec, real audio, no video, positive duration), size and per-kind duration limits, nothing kept on refusal; waveform peaks streamed from an FFmpeg pipe; owner-only Range preview stream
- An edit's `audio` section (`audio_mix_v1`): source gain, music (start point, loop, fades, gain, ducking preset), up to 12 sound-effect cues, normalization — validated, rounded, fingerprinted, with exact asset ids; edits without it unchanged
- Mixing engine: one FFmpeg plan from validated numbers onto a bed of the clip's exact length (video duration authoritative); music trim/loop/fades; `sidechaincompress` ducking (Light / Medium / Strong, tuned by measurement); delayed, trimmed effects
- Loudness: −1 dBFS safety limiter always; two-pass `loudnorm` to PeakSift's `social_v1` target (−14 LUFS, ≤ −1.5 dBTP, linear gain where possible); silence handled
- Render integration: assets re-checked, track prepared in the attempt workspace, AAC muxed into the short; output validated (stereo 48 kHz, video length), loudness and true peak recorded, clipped results refused
- Editor: Audio section (levels, music picker with waveform/listen/upload, music controls, ducking with text state, effect cues, lightweight timeline with keyboard-movable markers, normalization) and a video-clocked browser preview (hardened: pause, seeks, restart, loops, live changes, one sound at a time, nothing left playing); reviewed at 1440, 1024, 768 and 375 px
- Hardening (output validation, symlink containment, degenerate uploads, unusual formats, log redaction), CI (audio-mix matrix with measured ducking and loudness, audio files refused from the repository) and documentation ([audio-sound-design.md](audio-sound-design.md))

Definition of done — a user can open a generated clip → upload music and sound effects → set the music's volume, start, loop and fades → keep ducking on → place effects on the timeline → preview them with the video → render a short (with any layout, Smart Reframe, captions and hook) whose speech stays clear, music dips under it, effects land on time and loudness is consistent → download it.

## Milestone 10 — Production & Publishing V1.0 *(complete; release awaits live YouTube verification)*

PeakSift runs as a production service — object storage, health, observability, rate limits, containers, backups — and publishes finished shorts to YouTube.

Delivered:

- Media timing: one rule keeps transcript and candidate timing inside the media's real duration (normalizing small overshoots, refusing anything worse)
- Strict production configuration: `APP_ENV` allow-list; startup refuses unsafe secrets, non-HTTPS origins, missing hosts or infrastructure settings, eager jobs or disabled rate limits — naming the setting, never its value; trusted-proxy handling, Secure cookies, docs off in production
- Storage contract with local and private S3-compatible providers (MinIO, AWS S3, R2): ranged reads, identical HTTP Range behaviour on both, "missing" vs "unavailable" kept apart; every pipeline reads inputs into per-attempt scratch and stores only validated results; copy-first, resumable migration with checksum verification
- Deletion and cleanup: projects (confirmed by exact name), edits and unused audio with their files; counted failures; orphan, partial-write and stale-scratch cleanup
- Health (`/health/live`, `/health/ready`, worker diagnostic), request ids carried into jobs, redacted JSON logs, Redis rate limits (`429` + `Retry-After`, fail closed)
- YouTube: encrypted (AES-256-GCM) one-per-user connections; OAuth with the upload scope only, PKCE and single-use user-bound state; publish jobs with YouTube's metadata rules (refused, never truncated), private by default, idempotent fingerprints; a provider contract with normalized errors; resumable uploads that resume from YouTube's confirmed offset and never create a second video; a fenced pipeline with bounded processing checks and an honest "uploaded" end state; the publishing API; Settings and the publish dialog
- Production containers (non-root API with gunicorn + uvicorn workers, worker, standalone frontend, MinIO built from source), an HTTPS nginx proxy and a single-host Compose stack; security headers and a CSP compatible with Next.js and media; verifiable backups with disposable restore tests
- CI: live S3 suites against MinIO (required), production containers built, started and smoke-tested with in-stack backup and restore, YouTube on mocks, a repository security scan and dependency audits; documentation ([production.md](production.md), [publishing.md](publishing.md), [youtube-setup.md](youtube-setup.md), [user-guide.md](user-guide.md), [deploy/README.md](../deploy/README.md))

Definition of done — an operator can deploy PeakSift over HTTPS with private object storage, health checks, logs and backups; a creator can take a recording through transcription, clip detection, editing and rendering, connect YouTube, and publish a short privately with real progress, without duplicate uploads or exposed tokens.

## V1.1 — B-roll & Visual Enrichment

Status: **implementation complete, pending CI/merge/release** — stacked pull requests wait for
GitHub Actions (unavailable because of account billing); nothing is merged or tagged.

Creators add their own pictures and footage to a short: B-roll cutaways, picture-in-picture
and image overlays, with local-AI suggestions of where a visual helps and matches from their own
library. See [broll-visual-enrichment.md](broll-visual-enrichment.md).

Delivered:

- Visual asset library per project: JPEG/PNG/WebP and MP4/MOV/WebM validated from their contents
  (Pillow, ffprobe), images normalized (EXIF orientation, sRGB, CMYK/16-bit/alpha, MPO, metadata
  stripped), thumbnails, sha256 de-duplication, description and tags, search, owner-only Range
  streaming, deletion refused while an edit uses an asset; local and S3 storage
- B-roll suggestions: a fenced Celery job over the clip's words; a local Ollama model (JSON
  schema, temperature 0) with an honest deterministic keyword fallback; validation, grounding
  (anchored, no invented names, concrete) and density rules; an honest method on every analysis, noted in the editor
- Matching suggestions to the creator's assets by tags, name and description — offered, never
  placed automatically
- Edit `visuals` section (`visuals_v1`): cutaway (fill/fit), picture-in-picture and overlay,
  timing, position, size, opacity, video offset, loop, cut/fade; at most one cutaway and one
  inset at a time; checked at the API and again at render; old fingerprints unchanged
- FFmpeg compositor between framing and captions: per-element trimmed inputs, never stretched,
  insets inside the social safe area, captions and hook on top, B-roll always muted, the clip's
  duration and frame rate kept
- Editor: Visuals section with suggestions, asset chooser, element cards and timeline, live
  preview; project-page visual library
- Hardening and quality: colour profiles, MPO, frame-exact offsets, fades, looping and frame-rate
  tests; a render probe; CI steps for the V1.1 suites and the container smoke test
- Acceptance: a real-stack run (HTTPS proxy, gunicorn, worker, PostgreSQL, Redis, MinIO, FFmpeg,
  Ollama) from upload to downloaded short, and visual/UX review at 1440, 1024, 768 and 375 px

## V1.2 — Auto Edit & Creator Intelligence

Status: **implementation complete locally — pending CI/merge/release.** Stacked pull requests on
top of the unmerged V1.1 stack wait for GitHub Actions (unavailable because of account
billing); nothing is merged or tagged. V1.1 must be merged and released first.

A generated clip becomes a reviewable first draft: PeakSift reads what it already knows, a
planner chooses options inside a creator recipe, the server validates every choice, the creator
reviews and applies — and the plan becomes a normal edit rendered by the existing renderer. See
[auto-edit.md](auto-edit.md).

Delivered:

- `AutoEditPlan` with a source fingerprint (equal inputs reuse a plan), attempt ownership,
  stage-based progress and an immutable applied state
- Four versioned recipes (Clean, Punchy, Story, Minimal): preferences and bounds within the
  renderer's allow-lists
- A planner contract with symbolic handles (no ids reach a model), a local Ollama planner
  (JSON schema, one corrective attempt, per-clip constraints in the prompt, time-bounded) and
  a deterministic fallback planner
- An authoritative server validator: handles → ids, recipe bounds, grounded hooks, matching
  assets only, safe degradation with creator-facing notes
- A Celery planning job that consumes completed analyses (never starts them) and the Auto
  Edit API (create, status, retry, regenerate, apply as a normal edit)
- The Auto Edit page (recipes, honest stages, review with explanations, apply, edit choices,
  try another plan, history) and entry points on the clip card and in the editor
- Editor hydration from a version, a plan or the newest version, race-safe, with Reset to
  defaults
- B-roll suggestions "used" only while a visual fulfils them; the asset chooser opens fresh
- Hardening, a deterministic quality benchmark (no scores), CI steps and a render matrix,
  real-stack and visual/UX acceptance

## V1.3 — Semantic Asset Intelligence

Status: **implementation complete locally — pending CI/merge/release.** Stacked pull requests on
top of the unmerged V1.2 stack (itself on V1.1) wait for GitHub Actions (unavailable because of
account billing); nothing is merged or tagged. V1.1 and then V1.2 must be merged and released
first.

PeakSift understands what a creator's own images and videos show, locally: untagged visuals are
found by content, matched to B-roll suggestions and placed by Auto Edit when the match is
strong. See [semantic-assets.md](semantic-assets.md).

Delivered:

- A semantic index per asset and model identity (provider, model, revision, representation
  version, dimension) with pgvector storage (`vector(512)`), stale detection on model change,
  attempt ownership and honest progress
- A provider contract and a local OpenAI CLIP ViT-B/32 provider on onnxruntime (pinned,
  sha256-verified ONNX exports; lazy, one per process; no new ML framework); a deterministic
  fake for tests (refused in production)
- Image indexing (safe decode, EXIF, transparency on neutral grey, reuse within one owner) and
  bounded video frame sampling (black, flat and duplicate frames skipped; per-frame vectors with
  times)
- A background pipeline from the upload lifecycle (never blocking an upload), an optional
  dedicated queue, an operator `status` / `reindex` command, lazy bounded reindexing after a
  model change, and creator retries
- Hybrid search (what visuals show + names, descriptions, tags) with strong / possible tiers and
  versioned, benchmark-calibrated thresholds; "Search your visuals" in the library
- Semantic B-roll matching with match details and scene offsets; Auto Edit places strong
  matches only (planner contract v2, server-computed offsets, honest explanations and
  abstention)
- Match previews and a pre-filled chooser in the editor; subtle indexing states
- Performance and memory measurements, hardening, a semantic benchmark with safety gates, CI
  steps (fake provider, no weights), real-model acceptance (22/22) and visual/UX acceptance at
  1440, 1024, 768 and 375 px (153/153)

## V1.4 — Performance Analytics & Learning

Status: **implementation complete locally — pending CI/merge/release.** Stacked pull requests on
top of the unmerged V1.3 stack wait for GitHub Actions (unavailable because of account billing);
nothing is merged or tagged. V1.1, V1.2 and V1.3 must be merged and released first.

Creators see how the shorts they published from PeakSift are doing, and which of their own
editing choices have tended to go with stronger first weeks — observed, never predicted. See
[performance-analytics.md](performance-analytics.md).

Delivered:

- Published content linked from the publish job with an immutable provenance snapshot;
  snapshots and daily metrics with NULL ≠ 0, per-day view definitions and labelled sources
- An explicit, read-only analytics permission upgrade (purpose-bound OAuth state, checked
  grants, partial grants change nothing, per-use token scopes); publishing stays upload-only
- A provider contract with YouTube Data + Analytics (validated, columns by name) and a
  deterministic fake refused in production
- A fenced sync pipeline with an age-based schedule (Celery beat), creator refresh with a
  cooldown, backfill of PeakSift's own uploads, missing videos confirmed on a second check,
  and creator deletion of collected metrics
- The Analytics page and per-short page; early windows, completeness and the creator's own
  median baseline with a minimum sample
- A deterministic insights engine with a corrected significance test (measured false-pattern
  rate 2.7%), evidence and caveats; Auto Edit can consider insights as weak, in-recipe hints
- CI steps (fake provider, no Google credentials, insights benchmark gate), synthetic acceptance
  (170/170 browser checks at four widths) and real-account checks with upload-only grants

## V1.5 — Creator Experience & Modern Workspace

Status: **implementation complete locally — pending CI/merge/release.** Stacked pull requests on
top of the unmerged V1.4 stack wait for GitHub Actions (unavailable because of account billing);
nothing is merged or tagged. V1.1–V1.4 must be merged and released first.

PeakSift's features become one coherent creator workspace: every screen answers *where am I,
what is happening, what should I do next*, in the creator's words. No pipeline, model or render
changed. See [creator-experience.md](creator-experience.md) and
[design-system.md](design-system.md).

Delivered:

- One workspace navigation: a collapsible sidebar (a sheet on phones), Home, Projects, Analytics,
  Settings; projects with Overview · Source · Clips · Assets · Analytics tabs
- A refined design system: type scale, cards, section headers, dialogs and sheets, menus,
  segmented controls, tool tabs, tooltips, toasts, and one status language (Waiting · a specific
  step · Ready · Needs attention)
- Home and project overviews driven by owner-scoped summaries (`/workspace/home`,
  `/projects/{id}/summary`) and tested next-best-action rules; a dismissible first-run checklist
- Guided Short creation: Start → Style → Review → Render, Auto Edit recommended, recipe cards
  with traits, real preparing stages, review sections with reasons and Edit links
- The editor: dominant preview with play, seek, mute and full screen; five tool groups; the render
  action always in reach; accurate wording about versions
- Moments best first with grounded labels (Top pick, Strong moment, Worth reviewing), one
  primary Create Short, filters with counts; visuals search-first with Best matches / More
  results and batch uploads; analytics that answer "How are my Shorts doing?"
- Polish and hardening: terminology audit, skeletons, toasts and confirmations by rule; 112/112
  browser checks (16 screens × 1440/1280/1024/768/430/390/375: no overflow, no axe WCAG 2.1 AA
  violation, 44 px touch targets, no console errors)
- Acceptance: the first-time journey (account → upload → transcript → moments → Auto Edit
  Punchy → editor → render → play → download → simulated publish) and the returning journey in a
  real browser on a production build, with the defects it found fixed

## Roadmap status

- V0.1 Foundation — COMPLETE
- V0.2 Video Upload — COMPLETE
- V0.3 Transcription — COMPLETE
- V0.4 AI Clip Detection — COMPLETE
- V0.5 Clip Generation — COMPLETE
- V0.6 Short-form Editing — COMPLETE
- V0.6.1 Design Upgrade — COMPLETE
- V0.7 Smart Reframing — COMPLETE
- V0.8 Dynamic Captions & Creator Polish — COMPLETE
- V0.9 Audio & Sound Design — COMPLETE
- V1.0 Production & Publishing — COMPLETE (released as v1.0.0 after a live private YouTube upload)
- V1.1 B-roll & Visual Enrichment — IMPLEMENTATION COMPLETE, pending CI/merge/release
- V1.2 Auto Edit & Creator Intelligence — IMPLEMENTATION COMPLETE LOCALLY, pending CI/merge/release
- V1.3 Semantic Asset Intelligence — IMPLEMENTATION COMPLETE LOCALLY, pending CI/merge/release
- V1.4 Performance Analytics & Learning — IMPLEMENTATION COMPLETE LOCALLY, pending CI/merge/release
- V1.5 Creator Experience & Modern Workspace — IMPLEMENTATION COMPLETE LOCALLY, pending CI/merge/release

No later milestone has been defined or started.

## Later (opportunities, not committed scope)

- Creator intelligence & metadata (titles, hooks, descriptions)
- More publishing destinations (TikTok, Instagram, others), scheduling
- Licensed music and sound-effect libraries, beat-synced editing
- Brand kits, custom fonts and a caption timing editor
- Global asset libraries
- Morocco Mode (localization layer extending Global). Before any Moroccan accuracy claim, benchmark Darija, Arabic/French code-switching, Moroccan names, local slang and noisy streamer audio — none of that has been tested yet.
- Additional localization
