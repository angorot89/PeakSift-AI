# PeakSift AI

**Find the moments worth clipping.**

PeakSift AI is a short-form clipping and creation platform. Creators bring long-form content — videos, streams, podcasts, interviews, recordings — and PeakSift helps them find the strongest moments and turn them into short-form clips for TikTok, YouTube Shorts, and Instagram Reels.

> **Production:** `deploy/` holds the container images, an HTTPS reverse proxy and a single-host Compose stack (PostgreSQL, Redis, private MinIO storage) — see [deploy/README.md](deploy/README.md) and [docs/production.md](docs/production.md). **Using PeakSift:** [docs/user-guide.md](docs/user-guide.md).

## Current status

**Milestones 1–10 are complete** (Foundation V0.1, Video Upload V0.2, Transcription V0.3, AI Clip Detection V0.4, Clip Generation V0.5, Short-form Editing V0.6, Smart Reframing V0.7, Dynamic Captions & Creator Polish V0.8, Audio & Sound Design V0.9, Production & Publishing V1.0 — released as v1.0.0). **V1.1 B-roll & Visual Enrichment: implementation complete, pending CI/merge/release** (stacked pull requests waiting for GitHub Actions; not merged or tagged). **V1.2 Auto Edit & Creator Intelligence: implementation complete locally, pending CI/merge/release** (stacked on V1.1). **V1.3 Semantic Asset Intelligence: implementation complete locally, pending CI/merge/release** (stacked on V1.2). **V1.4 Performance Analytics & Learning: implementation complete locally, pending CI/merge/release** (stacked on V1.3). **V1.5 Creator Experience & Modern Workspace: implementation complete locally, pending CI/merge/release** (stacked on V1.4). **V1.6 Creator Copilot & Content Strategy: implementation complete locally, pending CI/merge/release** (stacked on V1.5). **V1.7 Brand Studio & Reusable Templates: implementation complete locally, pending CI/merge/release** (stacked on V1.6). **Visual UI/UX overhaul: implementation complete locally, pending CI/merge/release** (stacked on V1.7; warm, preview-first screens on the same data, and a feature-gated Morocco Mode preview with no Moroccan data yet). What exists today:

- A landing page.
- Email/password accounts: register, log in, log out, with an HttpOnly session cookie.
- Projects: create a project, list your projects, open a project.
- **Source video upload** on a project: MP4, MOV or WebM, with real upload progress.
- **Metadata extraction** with ffprobe: duration, resolution, frame rate, video/audio codecs — shown on the project page, or a clear failure state for unreadable files.
- **Owner-only preview** of the uploaded video with a native player (HTTP Range streaming).
- **Background transcription**: one click turns a ready video into a timestamped transcript. Audio is normalized with FFmpeg, split into 10-minute chunks and transcribed by a Celery worker with faster-whisper (local, default) or OpenAI (`whisper-1`); the project page polls real progress, shows failures and stalled jobs with retry, and renders the transcript with `HH:MM:SS` timestamps, paging and copy.
- **AI clip detection**: on a transcribed video, pick an AI provider and model (local Ollama or hosted OpenAI, from server allow-lists) and start a background run. The transcript is analysed in bounded windows, every proposal is validated against the transcript, deduplicated and ranked, and the project page shows candidate cards — title, time range, duration, a 0–100 editorial score with its breakdown, hook, rationale, transcript excerpt — with an in-page preview of that range of the original video and save/dismiss decisions. Details: [docs/clip-detection.md](docs/clip-detection.md).
- **Clip generation**: **Generate clip** on a candidate renders exactly its validated time range from the original upload into a private MP4 (H.264 + AAC, fast-start, original aspect ratio and orientation) in the background worker with FFmpeg, validates it with ffprobe, then shows the rendered clip in the page with **Download MP4**. Real render states, failure messages and retry; clips persist across sessions. Details: [docs/clip-generation.md](docs/clip-generation.md).
- **Short-form editing**: from a ready clip, the **short-form editor** renders it as a 9:16 short (1080 × 1920) in the background worker — **Center crop**, **Blur background** or **Fit** — with optional captions burned in from the transcript (Bold / Clean / Creator presets; top, center or bottom). Each settings combination is a separate version with its own status, 9:16 player and **Download short**; the V0.5 clip is never modified.
- **Smart reframing**: PeakSift detects and tracks visible faces to generate a smooth vertical crop path, with centre and manual fallbacks. In the editor, **Smart reframe** → **Analyze framing** runs a background analysis (frames sampled with FFmpeg → a local face detector → tracking → a crop path with a dead zone, smoothing and a pan-speed limit), shows real progress and a plain-language confidence summary, previews the moving crop in the 9:16 stage, and renders it with captions fixed on screen. When no face is clear the crop stays centred, and **Focal point** pins a fixed crop where you choose. Details: [docs/smart-reframing.md](docs/smart-reframing.md).
- **Dynamic captions**: word-synced captions generated from local speech timing. **Generate word sync** times every word of the clip's audio with faster-whisper word timestamps in the background; captions group words into short, readable cues and emphasise the spoken word in one of four creator presets (**Focus**, **Punch**, **Minimal**, **Boxed**), placed inside a general social-platform safe area, with an optional **opening hook** (1–60 characters, 0.5–5 s). The editor previews the renderer's own cues over the playing video; **Phrase timed** captions remain as a fallback and are never labelled word-synced. French, Arabic (right to left) and mixed scripts are supported; emoji are drawn in monochrome when a font for them is installed. Details: [docs/dynamic-captions.md](docs/dynamic-captions.md).
- **Audio & sound design**: creators upload their own music and sound effects to a project (MP3, WAV, M4A, AAC, OGG, Opus — validated by content, private, with a compact waveform) and finish a short's audio in the editor's **Audio** section: original level, background music with a start point, loop to fit, fades and volume, **automatic ducking** (Light / Medium / Strong — the music dips while the clip's own audio plays), up to 12 timed **sound effects** on a lightweight timeline, and **final loudness normalization** to PeakSift's −14 LUFS target with a peak safety limiter. A browser preview plays the music and effects with the video; the render (FFmpeg) is authoritative and works with every layout, Smart Reframe, captions and hook. Creators upload audio they own or may use — PeakSift has no music library. Details: [docs/audio-sound-design.md](docs/audio-sound-design.md).
- **B-roll & visual enrichment** (V1.1, pending merge): each project has a **visual library** of the creator's own images (JPEG, PNG, WebP) and B-roll videos (MP4, MOV, WebM) — validated by content, normalized (orientation, sRGB, metadata removed), thumbnailed, described and tagged. In the editor's **Visuals** section, **Suggest B-roll** asks a local model (with an honest keyword fallback) for short, grounded moments where a visual would help, each with the creator's matching assets; visuals are placed as **cutaways**, **picture-in-picture** or image **overlays** with timing, position, size, opacity, video start, looping and fades, previewed live and rendered by FFmpeg under the captions and hook. B-roll is always muted; PeakSift never searches or downloads media. Details: [docs/broll-visual-enrichment.md](docs/broll-visual-enrichment.md).
- **Auto Edit** (V1.2, pending merge): from a generated clip, choose a recipe (**Clean**, **Punchy**, **Story**, **Minimal**) and optionally one of your music tracks; PeakSift reads what it already knows (framing, word timing, B-roll suggestions, your assets), a local model (or deterministic rules when it is unavailable) proposes framing, captions, a grounded hook, matching visuals and the audio finish, and the server checks every choice. Review each section with its reason and what was left out, then **Use this edit** (a normal version, rendered as usual), **Edit choices** in the editor, or **Try another plan**. No virality scores, no auto-publishing. The editor now opens with your newest version's settings. Details: [docs/auto-edit.md](docs/auto-edit.md).
- **Semantic asset intelligence** (V1.3, pending merge): PeakSift understands what your own images and videos **show**, with a local image–text model (OpenAI CLIP ViT-B/32 on the server's CPU — nothing is sent anywhere). **Search your visuals** by content ("rocket launch" finds an untagged `VID_1429.mp4` at its launch scene) combined with names, descriptions and tags; B-roll suggestions list their **best matches** as **Strong** or **Possible** with how each matched and a video's best scene; the asset chooser opens already searching for the suggestion; and Auto Edit places only **strong** matches (a video starts at its matched scene) and abstains when nothing fits. Indexing runs in the background (uploads never wait) with honest states and a retry. Details: [docs/semantic-assets.md](docs/semantic-assets.md).
- **Performance analytics & learning** (V1.4, pending merge): after an explicit, separate, **read-only** permission upgrade (Settings → YouTube → **Connect analytics**; publishing stays upload-only), the **Analytics** page shows how the shorts you published from PeakSift are doing: live views, likes and comments, processed engaged views and average % viewed, daily charts with a table, and the same early windows for every short (day of publication, first 3 days, first 7 days) compared with **your own** median — "—" when YouTube reported nothing, never 0. **Patterns in your shorts** reports only associations that pass a corrected significance test among your own uploads ("shorts with an opening hook have tended to …"), with the evidence; otherwise "No reliable pattern yet". Auto Edit can optionally consider those patterns as weak hints inside the recipe. No predictions, no virality scores, no other creators' data; you can delete what was collected. Details: [docs/performance-analytics.md](docs/performance-analytics.md).
- **Creator workspace** (V1.5, pending merge): a sidebar with **Home** (each project's next step, recent Shorts and projects, a first-run checklist), projects with **Overview · Source · Clips · Assets · Analytics**, guided **Create a Short** (Start → Style → Review → Render, Auto Edit recommended), an editor with a dominant preview and five tool groups (Style, Captions, Opening, Visuals, Sound), moments best first (Top pick · Strong moment · Worth reviewing — editorial, never predictions), a search-first visual library, and analytics that answer *How are my Shorts doing?*. Checked at seven widths from 1440 to 375 px for overflow, WCAG 2.1 AA (axe-core), touch targets and console errors. Details: [docs/creator-experience.md](docs/creator-experience.md).
- **Ask PeakSift** (V1.6, pending merge): a project assistant beside every page — "What should I do next?", "Which moment should I start with?", "Give me 3 Short ideas from this video", "How can I improve this edit?" — answered from the creator's own data by a local model, with Based-on chips, idea cards and buttons re-checked on click; it suggests, the creator decides (it cannot publish, delete or change anything). A ⌘K / Ctrl K command menu jumps anywhere or asks. Not connected to the internet; no trends, no predictions. Details: [docs/creator-copilot.md](docs/creator-copilot.md).
- **Brand Studio** (V1.7, pending merge): set up **how your Shorts look** once — a brand with colours, a caption emphasis colour, your logo (a corner and a size) and an end-card line — and **how your Shorts are edited** as reusable, versioned **templates** (framing, captions, opening hook, visuals, sound, logo, end card). *Create a Short* and Auto Edit start from your default template; every Short stays editable on its own; **Save as template** / **Update template** from the editor. The logo moves out of the captions' way, waits for a top hook and hides behind a same-corner picture-in-picture; colours that would be hard to read are left out. Old Shorts never change when a template or brand does. No custom fonts, motion graphics, marketplaces or generated branding. Details: [docs/brand-studio.md](docs/brand-studio.md).
- **Publishing to YouTube**: connect a YouTube account in **Settings** (Google's consent page; upload access only — PeakSift cannot read, change or delete anything on the channel), then **Publish to YouTube** from the editor with a reviewed title, description, tags, visibility (**Private** by default) and the made-for-kids declaration. Uploads use YouTube's resumable protocol, show real progress, retry safely and never create the same video twice; refresh tokens are encrypted and never leave the server. Off until an operator configures it. Details: [docs/publishing.md](docs/publishing.md), [docs/youtube-setup.md](docs/youtube-setup.md).
- **Production operation**: media in a local directory or a **private S3-compatible bucket** (MinIO, AWS S3, R2) with copy-first migration, project/edit/audio **deletion** with cleanup, strict production configuration, liveness/readiness checks, request ids in redacted JSON logs, Redis **rate limits**, security headers and a CSP, **verifiable backups** with disposable restore tests, and non-root containers behind an HTTPS proxy. Details: [docs/production.md](docs/production.md).
- **Product design**: a shared design system (surface and status tokens, one button shape, panels, status pills, alerts, empty states, skeletons, progress), a project page organised as a workflow stepper plus numbered sections (Source video, Transcript, Clip moments, Generated clips), ranked candidate cards that lead with rank, title, score and hook, and context-specific empty, working and error states. Details: [docs/short-form-editing.md](docs/short-form-editing.md).
- PostgreSQL schema (`users`, `projects`, `videos`, `transcriptions`, `transcript_segments`, `clip_detection_runs`, `clip_candidates`, `clips`, `clip_edits`, `reframe_analyses`, `reframe_keyframes`, `caption_tracks`, `caption_words`, `audio_assets`, `visual_assets`, `broll_analyses`, `broll_suggestions`, `auto_edit_plans`, `visual_semantic_indexes`, `visual_asset_embeddings` (pgvector), `publishing_connections`, `oauth_states`, `publish_jobs`, `published_contents`, `performance_snapshots`, `performance_daily_metrics`, `analytics_syncs`, `insight_sets`, `creator_insights`, `copilot_threads`, `copilot_messages`, `brand_profiles`, `short_templates`) managed with Alembic migrations.
- Automated tests (about 3,200 backend and 146 frontend unit tests; the V1.1–V1.7 additions have run in local validation only until GitHub Actions is available again), linting, type checks and CI with PostgreSQL, Redis, FFmpeg and a live MinIO (including real clip, captioned short, word-synced caption, moving-crop and measured audio-mix renders), production containers started and smoke-tested, and a repository security scan.

**Not built yet** (see [docs/milestones.md](docs/milestones.md)):

| Feature                                                              | Milestone |
| -------------------------------------------------------------------- | --------- |
| Creator intelligence & metadata, more publishing destinations        | later     |
| Stock or global asset libraries, Morocco Mode                        | later     |

The dashboard's Videos and Clips cards do not show counts yet. Smart reframing follows visible faces only — no speaker identification, object tracking, zoom or split screen — and word timing is as accurate as the speech recognizer's word timestamps (no manual timing editor); audio ducking follows the clip's overall loudness (no voice isolation), and there is no timeline editor, custom fonts or music library; publishing is YouTube only (see [Known limitations](#known-limitations)).

## Architecture (as built)

```
Browser ──▶ (HTTPS proxy) ──▶ Next.js frontend ──fetch, cookie──▶ FastAPI backend ──▶ PostgreSQL
                                                              │                         ▲
                                                              ├──▶ media storage: MEDIA_ROOT or a private S3 bucket (videos, audio, clips, shorts)
                                                              ├──▶ ffprobe (metadata)   │ status, segments, candidates
                                                              └──▶ Redis ──▶ Celery worker ──▶ transcription: ffmpeg → chunks → faster-whisper | OpenAI
                                                                                           ├─▶ clip detection: transcript windows → Ollama | OpenAI → validate → rank
                                                                                           ├─▶ clip rendering: ffmpeg (libx264/aac) → ffprobe → MEDIA_ROOT/clips/
                                                                                           ├─▶ short-form edits: transcript or word timing → ASS captions; music/effects → mix → ducking → loudness → ffmpeg (9:16 layout | moving crop + libass, AAC) → ffprobe → MEDIA_ROOT/edits/
                                                                                           ├─▶ smart reframe: ffmpeg frames → YuNet faces → tracks → crop path → reframe_keyframes
                                                                                           ├─▶ word timing: ffmpeg PCM → faster-whisper word timestamps → validate → caption_words
                                                                                           └─▶ publishing: encrypted refresh token → google-auth → resumable videos.insert → YouTube
```

Jobs read their inputs into a per-attempt scratch directory (`WORK_ROOT`) and store only validated results in media storage.

- **Frontend** — Next.js App Router, TypeScript, Tailwind CSS. Talks to the API with `credentials: "include"`; asks `GET /auth/session` to learn who is signed in. No tokens in browser storage.
- **Backend** — FastAPI, SQLAlchemy 2 (sync), Alembic, psycopg 3. Argon2id password hashing; HS256 JWT delivered in an HttpOnly `SameSite=Lax` cookie; CORS limited to the frontend origin. Uploads are spooled, validated and stored through the storage contract (local directory or private S3 bucket), then probed with ffprobe synchronously; transcription and clip detection run in a Celery worker over Redis, with the database as the source of truth for job state.
- **Database** — PostgreSQL. `users`, `projects`, `videos`, `transcriptions`, `transcript_segments`, `clip_detection_runs`, `clip_candidates`, `clips`, `clip_edits`, `reframe_analyses`, `reframe_keyframes` tables, UUID keys, timezone-aware timestamps.

Details: [docs/architecture.md](docs/architecture.md), [backend/README.md](backend/README.md), [frontend/README.md](frontend/README.md).

## Local development

### Prerequisites

- Node.js 20.9+
- Python 3.11+
- PostgreSQL 14+ with the [pgvector](https://github.com/pgvector/pgvector) extension available (the migrations create it) — either Docker (`docker compose up -d`, which creates the `peaksift` and `peaksift_test` databases on the `pgvector/pgvector:pg16` image) or a local installation plus pgvector (`brew install pgvector` for Homebrew's current PostgreSQL, or build it for your server version: `make PG_CONFIG=… && make install`)
- FFmpeg (`ffprobe` for metadata, `ffmpeg` for audio and rendering): `apt install ffmpeg` on Ubuntu. On macOS use `brew install ffmpeg-full` and set `FFMPEG_PATH` / `FFPROBE_PATH` to `/opt/homebrew/opt/ffmpeg-full/bin/…` — Homebrew's default `ffmpeg` has no libass, so captioned shorts are refused with it. Without FFmpeg uploads end in status `failed` and transcription cannot run.
- Caption fonts: Noto Sans (and Noto Sans Arabic) — `apt install fonts-noto-core` / `brew install --cask font-noto-sans font-noto-sans-arabic`.
- Redis 7+ — Docker Compose (included) or `brew install redis && brew services start redis`. Broker for background jobs; the API starts without it, but starting a transcription or a clip detection answers `503` until it is reachable.
- Ollama (optional, for local AI clip detection): `brew install ollama`, `ollama serve`, `ollama pull llama3.2:3b`. Without it the local provider is listed as unavailable; the hosted OpenAI provider needs `OPENAI_API_KEY` instead.

### 1. PostgreSQL and Redis

```bash
docker compose up -d                 # PostgreSQL + Redis; or: createdb peaksift && createdb peaksift_test, brew services start redis
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # set DATABASE_URL and SECRET_KEY (openssl rand -hex 32)
alembic upgrade head
uvicorn app.main:app --reload        # http://localhost:8000 — docs at /docs
```

Uploaded videos, audio and rendered media are written under `backend/media/` (`MEDIA_ROOT`), which is git-ignored, or to a private S3-compatible bucket with `STORAGE_BACKEND=s3`. Jobs work in temporary per-attempt directories under `WORK_ROOT`.

### 3. Celery worker (transcription, clip detection, clip rendering, short-form edits, smart reframing, word timing)

In a second terminal, same virtualenv and directory:

```bash
cd backend && source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info
```

The default speech-to-text provider is faster-whisper on CPU (`FASTER_WHISPER_MODEL=small`, `int8`); the model (~460 MB) is downloaded on the first transcription, never at startup. On macOS, CPU mode is the supported path — there is no Apple-GPU acceleration in this stack. Set `FASTER_WHISPER_MODEL=tiny` to try the mechanics quickly, or `TRANSCRIPTION_PROVIDER=openai` with `OPENAI_API_KEY` for the hosted provider.

The same worker runs clip detection, clip rendering, short-form edits and smart-reframing analyses (CPU `libx264`; your FFmpeg must include the `libx264` and `aac` encoders, and libass for captions — Ubuntu's `ffmpeg` and Homebrew's `ffmpeg-full` do). For the local AI provider, start Ollama (`ollama serve`) and pull a model from `OLLAMA_CLIP_MODELS` (default `llama3.2:3b`); the worker never pulls or loads a model itself.

For smart reframing, install the face detector model once (MIT-licensed OpenCV Zoo YuNet, pinned sha256, git-ignored; PeakSift never downloads it by itself):

```bash
cd backend && python scripts/fetch_reframe_model.py
```

Without it, **Analyze framing** answers "Smart framing is not available on this server"; manual focal-point crops still work.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:3000
```

Open **http://localhost:3000** (not `127.0.0.1`) so the auth cookie, CORS origin and video preview line up.

### Checks

```bash
cd backend && ruff check . && ruff format --check . && pytest
cd backend && python scripts/celery_smoke.py      # real worker round-trip over Redis + task registration
cd backend && python scripts/smart_crop_probe.py  # this FFmpeg renders the deepest allowed smart-crop path
cd frontend && npm run lint && npm run build
```

Backend tests use a separate database (`TEST_DATABASE_URL`, default `peaksift_test`), a temporary media directory and Celery eager mode; they never touch your development data, never download a speech model (inference is mocked), never call OpenAI and never need Ollama (the provider is tested against a mocked transport and an in-process fake server). Media fixtures are generated with `ffmpeg` at test time; ffmpeg- and Redis-dependent tests skip when those are missing locally and are mandatory in CI. Face detection is tested against a fake ONNX session. Opt-in real-model checks: `PEAKSIFT_REAL_WHISPER=1`, `PEAKSIFT_REAL_OLLAMA=1` and `PEAKSIFT_REAL_DETECTOR=1` (with `REFRAME_TEST_FACE_IMAGE`).

## Upload flow

1. Open a project and choose (or drag in) an MP4, MOV or WebM file.
2. The browser streams it to `POST /projects/{id}/videos` with a progress bar.
3. The API validates the name, extension and MIME type, spools the file locally, stores it in media storage under a generated key, enforces `MAX_VIDEO_UPLOAD_BYTES` (default 2 GiB), then runs `ffprobe`.
4. The project page shows the result: **Ready** with real metadata and a preview player, or **Failed** with the reason and an option to upload a different file.

### Configuration that matters here

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEDIA_ROOT` | `./media` (relative to `backend/`) | Where uploaded files live |
| `MAX_VIDEO_UPLOAD_BYTES` | `2147483648` (2 GiB) | Upload size limit (`413` beyond it) |
| `FFPROBE_PATH` | `ffprobe` | ffprobe binary |
| `FFPROBE_TIMEOUT_SECONDS` | `30` | Per-file probe limit; exceeding it marks the video `failed` |

## Transcription flow

1. On a ready video, click **Transcribe video**. The API creates the job, queues it in Redis and returns at once.
2. The Celery worker extracts normalized audio (mono 16 kHz 64 kbps MP3), splits it into `TRANSCRIPTION_CHUNK_SECONDS` chunks (default 10 min) and transcribes them in order with the configured provider, committing timestamped segments and real progress after every chunk.
3. The page polls every 4 s while the job is `queued` / `extracting_audio` / `transcribing`, then shows the transcript — `HH:MM:SS` timestamps, 200 segments per page with **Load more**, **Copy transcript** — or a failure/stalled state with **Retry transcription**.

### Providers and timestamps

| Provider (`TRANSCRIPTION_PROVIDER`) | Where it runs | Timestamps | Setup |
| --- | --- | --- | --- |
| `faster_whisper` (default) | locally in the worker (CPU; CUDA optional) | native segment timestamps | nothing besides FFmpeg; model downloads on first use (`FASTER_WHISPER_MODEL`, `_DEVICE`, `_COMPUTE_TYPE`, `_BEAM_SIZE`) |
| `openai` | OpenAI API | `OPENAI_TIMESTAMP_MODEL=whisper-1` with `verbose_json` segment timestamps | `OPENAI_API_KEY` (never committed, never shown); `gpt-4o-mini-transcribe` / `gpt-4o-transcribe` are text-only in the current API and are refused for timing |

PeakSift cuts clips from transcript timestamps, so a provider must return real segment timestamps; text-only responses are never padded with invented times. Provider choice is server configuration.

### Statuses, progress and retries

`queued` → `extracting_audio` → `transcribing` → `completed` | `failed`. Progress is real (5 % once audio is ready, then chunks done ÷ total). Transient provider errors (rate limits, timeouts, 5xx) are retried in-task with exponential backoff; configuration, invalid-audio and malformed-output errors fail immediately with a safe `error_message`. A job whose worker stopped reporting for `TRANSCRIPTION_STALE_AFTER_SECONDS` (30 min) is flagged `is_stale` and can be retried; a Celery task id acts as a fencing token so two workers never both complete the same job.

## Clip detection flow

1. On a transcribed video, the **AI clip detection** panel lists the providers and models the server allows (`OLLAMA_CLIP_MODELS`, `OPENAI_CLIP_MODELS`) and says why one is unavailable. Click **Find clip moments**; the API records the run and queues it at once.
2. The worker prepares the transcript (normalised, validated, fingerprinted), splits it into bounded overlapping windows (default 5 minutes / 8000 characters), asks the model for candidates per window with a strict JSON schema, **validates every proposal** (snapped to transcript-line boundaries, inside the video, 15–90 s, whole-number scores 0–100, bounded texts — anything else is rejected, never clamped or invented), deduplicates overlaps and ranks by a documented weighted score, then stores the top 10 with the completed status in one transaction.
3. The page polls every 4 s through *Preparing transcript → Analyzing (window i of n) → Validating → Ranking*, then shows ranked cards with an in-page **Preview** of that range (the owner-only video stream), **Save** / **Dismiss**, filters and run history. Failed or stalled runs can be retried (bounded); re-transcribing flags older candidates as belonging to a previous transcript.

Scores are the model's editorial judgement normalised to 0–100 — not predictions of views. Full reference: [docs/clip-detection.md](docs/clip-detection.md).

## Clip generation flow

1. On a candidate card, click **Generate clip**. The API takes the candidate's persisted, validated boundaries (the browser sends no timestamps), re-checks them against the source, records one clip per candidate and queues the render at once; a repeat click returns the same clip.
2. The worker renders the range with FFmpeg — re-encoded (never stream-copied) with input seeking, so the clip starts at the requested frame — to H.264 + AAC in a fast-start MP4 at the source's resolution and orientation, writes it to a per-attempt temp file, validates it with ffprobe (codec, size, duration within 1 s, audio iff the source has audio), renames it atomically to `clips/<id>/clip.mp4` and only then marks the clip `ready`.
3. The card polls every 4 s through *Queued → Rendering → Validating*, then shows the **Rendered clip** player (owner-only Range stream) and **Download MP4** (attachment with a safe filename). Failed or stalled renders show a safe message and **Retry render**.

Full reference: [docs/clip-generation.md](docs/clip-generation.md).

## Short-form editing flow

1. On a ready clip, **Create vertical short** opens the short-form editor (`/projects/[id]/clips/[clipId]`): a 9:16 stage with a labelled, approximate live preview (layout and a real transcript caption) beside visual settings — layout cards (**Center crop**, **Blur background**, **Fit**), a **Captions** switch, caption-style cards (**Clean**, **Bold**, **Creator**) and a **Top** / **Center** / **Bottom** position picker. Click **Render short**; the API validates the options against allow-lists, deduplicates identical settings and queues the render at once.
2. The worker builds captions from the persisted transcript (clip-local times, short cues, proportional word timing within each segment — phrase-level, not word-level), writes an escaped ASS file into the attempt's private workspace, composes the clip at 1080 × 1920 with FFmpeg (and libass for captions), validates the output with ffprobe, renames it atomically to `edits/<id>/edited.mp4` and only then marks the edit `ready`.
3. The editor shows the real render state in place of the button, then switches the stage to the rendered short with **Download short**, **Create another version** and **Back to clip**. Every version is listed by its settings with status, play and download; failed or stalled renders explain the problem and offer **Retry render**.

Full reference: [docs/short-form-editing.md](docs/short-form-editing.md).

## Smart reframing flow

1. In the editor, choose **Smart reframe** and click **Analyze framing**. The API records an analysis for the clip and the server's configuration (repeat clicks return the same one) and queues it.
2. The worker samples frames from the clip through an FFmpeg pipe (2 per second, downscaled, rotation applied), finds faces with a local YuNet detector, links them into tracks, chooses the subject to follow (most prominent and persistent face, with hysteresis; a close pair is framed together), and plans a fixed-size 9:16 crop path: a dead zone against jitter, face margins, look-ahead, smoothing, a pan-speed limit, a camera cut at obvious shot changes, and centre fallback when nobody is visible. The keyframes, statistics and `completed` are written in one transaction.
3. The panel shows *Reading frames → Finding faces → Following the subject → Planning the camera path* with real progress, then a plain-language summary (**Strong tracking**, **Some center fallback** or **Manual framing recommended**). The stage previews the moving crop. **Render short** renders it as a time-varying FFmpeg crop with captions fixed on screen; changing captions reuses the analysis. **Focal point** offers a fixed manual crop instead.

A detector that is missing or crashes fails the analysis with a clear message; it is never reported as "no faces". Full reference: [docs/smart-reframing.md](docs/smart-reframing.md).

## Dynamic captions flow

1. In the editor, turn on **Captions**, keep **Word synced** and click **Generate word sync**. The API records a caption track for the clip and the server's timing configuration (repeat clicks return the same one) and queues it.
2. The worker decodes the clip's audio, runs faster-whisper with word timestamps (the same lazily loaded model as transcription), validates every word (refusing impossible timing, dropping empty or tiny words, trimming overlaps) and stores the clip-local words and `completed` in one transaction. The panel shows the stage and progress, then "Word synced · N words timed from the clip's audio".
3. Pick a caption style and position, and optionally an opening hook. The preview draws the renderer's own cues and active word over the playing video, with an optional safe-area guide. **Render short** renders word-synced captions with libass (`caption_v2`); old edits keep the V0.6 renderer (`caption_v1`).

If word timing fails, the panel explains why and offers **Retry** or **Use phrase timing instead**. Full reference: [docs/dynamic-captions.md](docs/dynamic-captions.md).

## Audio flow

1. In the editor's **Audio** section, upload or pick music and sound effects (the project's own uploads; files are probed with ffprobe, stored privately under generated keys and given a waveform). Upload only audio you own or have permission to use.
2. Set the original level, music volume, start point, looping and fades, keep **Automatic ducking** on (or pick its strength), place effects on the timeline, and play the preview — the music and effects follow the preview video's clock.
3. **Render short**: the worker re-checks the assets, mixes everything onto a bed of exactly the clip's length (FFmpeg: trim/loop, fades, `sidechaincompress` ducking, delayed effects), applies a −1 dBFS safety limiter and two-pass `loudnorm` to −14 LUFS, muxes the track as AAC, validates it (stereo, 48 kHz, the video's length) and records the measured loudness. Edits without an audio section render exactly as before.

Full reference: [docs/audio-sound-design.md](docs/audio-sound-design.md).

## Visuals flow

1. On the project page, upload images and B-roll videos you own or may use to the **Visual assets** library (validated by content, stored privately, thumbnailed) and describe and tag them.
2. In the editor's **Visuals** section, **Suggest B-roll** runs a background job over the clip's words: a local Ollama model (or the keyword fallback, labelled as such) proposes 1–6 s moments with a query and a reason; validation, grounding and density rules keep only honest, spaced suggestions, each listing up to three matching assets from your library.
3. Use a match, choose any asset, or **Add visual**; set the mode (cutaway, picture-in-picture, overlay), timing and options and watch the live preview.
4. **Render short**: the worker re-checks every asset, fetches it into the attempt's scratch, and composites the visuals between the framing and the captions (FFmpeg; never stretched, B-roll muted, the clip's duration and frame rate kept). Edits without visuals render exactly as before.

Full reference: [docs/broll-visual-enrichment.md](docs/broll-visual-enrichment.md).

## Auto Edit flow

1. Prepare the clip in the editor (optional but recommended): **Analyze framing**, **Generate word sync**, **Suggest B-roll**, and tag your visual assets. Auto Edit never starts these itself.
2. On the Auto Edit page, pick a recipe and (optionally) a music track; the worker gathers the completed inputs, asks the local model (bounded, one corrective attempt; the deterministic rules stand in when it cannot answer) and validates every choice into a normal edit configuration.
3. Review the plan; **Use this edit** creates the edit through the same checks as the edit API and the editor opens with exactly that version; **Edit choices** opens the settings without rendering; **Try another plan** keeps the history.

Full reference: [docs/auto-edit.md](docs/auto-edit.md).

## Visual search flow

1. Upload images and videos to a project's visual library; each is indexed in the background (an image in about 0.1 s, a short video in about 1.5 s, on a laptop CPU).
2. **Search your visuals** by what they show (plus names, descriptions and tags); B-roll suggestions show their best matches; Auto Edit places strong matches only.
3. Operators install the model once (`python scripts/fetch_semantic_model.py`) and can reindex after a model change (`python -m app.cli.semantic reindex`).

Full reference: [docs/semantic-assets.md](docs/semantic-assets.md).

## Security model (high level)

- Every project, video, detection-run, candidate, clip and edit endpoint is scoped to the signed-in owner; anything else is a `404`.
- Rendered clips and shorts are private: preview and download go through owner-checked endpoints; candidate titles only influence the sanitised download name, never a storage path.
- Edit options are allow-listed enums (plus a validated analysis id or focal point); users never submit filters, fonts, paths or ASS syntax. Smart-reframing tuning, the detector and its model file are server configuration; stored crop paths are re-validated before they reach FFmpeg, as numbers only. Transcript text is untrusted: it is escaped for ASS (no override tags or line commands can form) and never reaches a shell, a filtergraph or a path.
- Users choose an AI provider and model only from server allow-lists; the Ollama endpoint and the OpenAI key are server configuration and never appear in responses, errors or the frontend. Model output is validated and bounded before anything is stored.
- Browser-supplied filenames are metadata only. Files are stored under application-generated UUID keys through one storage contract; locally the single path-resolution function refuses anything outside `MEDIA_ROOT`, and an S3 bucket is private (no ACLs, no public or presigned URLs).
- Uploads are validated in layers (extension, MIME plausibility, size during streaming, then ffprobe proving the bytes are readable media). Oversized, empty or unreadable uploads leave no stray files.
- ffprobe and ffmpeg are invoked with argument lists (no shell) and timeouts; their stderr is never stored or returned. Only database ids cross the job broker.
- The OpenAI key lives in server settings only — never in responses, logs, task payloads, the frontend or CI.
- Nothing in media storage is served statically; the only way to read bytes is the authenticated, owner-only content endpoint.
- Publishing: the YouTube scope is upload-only; OAuth uses PKCE and a single-use state bound to the user; refresh tokens are encrypted with AES-256-GCM under a key from the environment; tokens, codes and upload session URIs never reach the browser or the logs ([docs/publishing.md](docs/publishing.md)).
- Production: strict startup configuration, HTTPS-only cookies, trusted-proxy client addresses, Redis rate limits on sign-in and every expensive operation, security headers and a CSP, redacted logs ([docs/production.md](docs/production.md)).
- Visual assets are typed by their contents (Pillow, ffprobe), with pixel and duration limits checked before decoding; images are re-encoded (no metadata kept); descriptions and tags are plain text; model suggestions are validated and grounded and never reach a filtergraph; asset ownership is re-checked at render.
- Semantic search: images and frames are embedded on the server only (no cloud vision or embedding service); search and matching scan only the project's own vectors of the current model; responses and logs never carry vectors, scores, model locations or pixel data; the model files are pinned and sha256-verified.
- Auto Edit: the planner sees facts and symbolic handles only; its JSON proposal is validated by the server (handles → ids, recipe allow-lists, grounded hooks, matching project assets only); model output never reaches filters, paths or volumes; responses never carry prompts, model names or addresses.
- Error responses never include filesystem paths, storage keys or submitted values.

## Known limitations

- Metadata probing runs inside the upload request; very large files make the upload response wait for ffprobe.
- The frontend does not know the size limit in advance; an oversized file is rejected by the API with a `413` message.
- Deleting covers whole projects, edits and unused audio files; there is no per-video or per-clip deletion, and replacing a video keeps the previous file and record (and its transcription).
- Chunk boundaries are plain time cuts, not silence-aware: a word spoken across a boundary can be split between two segments. Chunks are transcribed sequentially (no parallelism, no GPU workers, no provider fallback chains).
- Transcripts: no speaker diarization, word-level timestamps (word timing exists per clip, for captions), translation, transcript editing or live transcription. The `speaker` column is reserved and always null.
- A job interrupted by a worker crash restarts from the beginning via the stale rule or retry (no chunk-level resume).
- Transcription quality has only been sanity-checked on synthesised English speech; no Darija/Moroccan benchmarking has been done.
- Clip detection analyses windows sequentially and cuts them on time/character budgets, not topics; snapping is line-granular; deduplication is temporal only; small local models yield fewer usable candidates. The hosted provider sends transcript text to OpenAI.
- Generated clips keep the original aspect ratio; vertical output comes from short-form edits. Rendering is CPU-only with fixed MP4/H.264/AAC profiles and stage (not frame) progress; there is no clip deletion, retention or render cancellation.
- Smart reframing is face-first: no speaker identification or active-speaker/audio mapping, no face recognition, no tracking of bodies, pets or objects, no dynamic zoom, no split screen and no keyframe timeline. Shot changes are inferred from one face vanishing as another appears, not from scene analysis; very small, occluded or profile faces may be missed (centre fallback). Analysis is CPU-only.
- Short-form edits: word-synced captions depend on the speech recognizer's word timestamps (word-timed, not phoneme aligned) and can lead or lag slightly on fast or noisy speech; there is no manual word-timing editor, per-word positioning, custom font, brand kit or arbitrary animation. Phrase-timed and V0.6 captions use approximate word timing within transcript segments. Emoji are monochrome in dynamic captions (skin tones are not drawn) and left out of V0.6 captions; Arabic typography has had limited QA. Word timing runs locally on the CPU. No timeline or trimming.
- Publishing: YouTube only — no other platforms, scheduling, analytics, comments or thumbnails; PeakSift cannot edit or delete published videos. Google keeps uploads from unverified projects private and its default quota allows about six uploads a day; processing completion is not observable with the upload-only scope.
- Deployment: single host with Docker Compose (no Kubernetes, multi-region, CDN or GPU autoscaling); renders on S3 download their input each time.
- Visuals: a small local model can return few or no suggestions and the keyword fallback finds only proper names; no stock media, internet search or generated imagery; no zoom/pan, keyframes, masks or split screen; one cutaway and one inset at a time; fade is the only transition; B-roll sound is never used; the editor preview approximates the render.
- Visual search: similarity is not understanding (a picture that looks right can be wrong for the moment); long videos are represented by a few sampled frames; results depend on the model (common objects and scenes work best); no internet or stock search, generated media, face recognition or OCR; thresholds are calibrated cut-offs, not probabilities; each API process holds about 0.5 GB for the text encoder once it has searched.
- Auto Edit: plans are as good as the prepared inputs (framing, word timing, B-roll suggestions, tagged assets); a small local model is conservative; hooks use only the clip's words; transition sounds are recognised by name; an applied plan whose version was deleted cannot be applied again.
- Audio: ducking reacts to the clip's overall audio energy (background noise ducks too; no voice isolation or stem separation); no waveform zoom, multitrack timeline, automation, EQ or beat detection; no music or effect library (user-supplied audio only); the browser preview does not imitate ducking or loudness and cannot play level boosts.

## Routes

**Frontend:** `/`, `/login`, `/register`, `/dashboard`, `/projects`, `/projects/new`, `/projects/[id]`, `/projects/[id]/clips/[clipId]` (short-form editor, with Visuals), `/projects/[id]/clips/[clipId]/auto-edit` (Auto Edit), `/settings` (YouTube connection)

**API:** `GET /health` · `POST /auth/register` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` · `GET /auth/session` · `GET /projects` · `POST /projects` · `GET /projects/{id}` · `POST /projects/{id}/videos` · `GET /projects/{id}/videos` · `GET /projects/{id}/videos/{video_id}` · `GET /videos/{video_id}/content` · `POST /projects/{id}/videos/{video_id}/transcription` · `GET …/transcription` · `POST …/transcription/retry` · `GET …/transcript` · `GET /clip-detection/providers` · `POST /projects/{id}/videos/{video_id}/clip-detection` · `GET …/clip-detection` · `GET …/clip-detection/{run_id}` · `POST …/clip-detection/{run_id}/retry` · `GET …/clip-detection/{run_id}/candidates` · `GET …/candidates/{candidate_id}` · `POST …/candidates/{candidate_id}/save|dismiss|reset` · `POST …/candidates/{candidate_id}/clip` · `GET …/candidates/{candidate_id}/clip` · `POST …/candidates/{candidate_id}/clip/retry` · `GET /projects/{id}/videos/{video_id}/clips` · `GET /clips/{clip_id}/content` · `GET /clips/{clip_id}/download` · `POST /projects/{id}/videos/{video_id}/clips/{clip_id}/edits` · `GET …/edits` · `GET …/edits/{edit_id}` · `POST …/edits/{edit_id}/retry` · `GET /edits/{edit_id}/content` · `GET /edits/{edit_id}/download` · `POST …/clips/{clip_id}/reframe` · `GET …/reframe` · `GET …/reframe/current` · `GET …/reframe/{analysis_id}` · `GET …/reframe/{analysis_id}/path` · `POST …/reframe/{analysis_id}/retry` · `GET /health/live` · `GET /health/ready` · `DELETE /projects/{id}` · `DELETE …/edits/{edit_id}` · `DELETE …/audio-assets/{asset_id}` · `GET /visual-upload-limits` · `GET /visual-layout` · `POST|GET /projects/{id}/visual-assets` · `GET|PATCH|DELETE …/visual-assets/{asset_id}` · `GET …/visual-assets/{asset_id}/content|thumbnail` · `GET …/visual-assets/search` · `POST …/visual-assets/{asset_id}/visual-search/retry` · `GET …/clips/{clip_id}/broll` · `POST …/broll/analyses` · `GET …/broll/analyses/{analysis_id}` · `GET …/broll/analyses/{analysis_id}/suggestions` · `POST …/broll/analyses/{analysis_id}/retry` · `PATCH …/broll/suggestions/{suggestion_id}` · `GET /auto-edit/recipes` · `POST|GET …/clips/{clip_id}/auto-edits` · `GET …/auto-edits/{plan_id}` · `POST …/auto-edits/{plan_id}/retry|regenerate|apply` · `GET|DELETE /publishing/youtube` · `POST /publishing/youtube/connect` · `GET /publishing/youtube/callback` · `GET|POST /edits/{edit_id}/publish` · `GET /publish-jobs/{job_id}` · `POST /publish-jobs/{job_id}/retry` — see [backend/README.md](backend/README.md#api).

## Continuous integration

Every push to `main` and every pull request runs [GitHub Actions](.github/workflows/ci.yml): the frontend job runs `npm ci`, lint, unit tests (`npm test`), a type check and build; the backend job installs FFmpeg, runs Ruff, applies and checks the Alembic migrations against a PostgreSQL service container, runs the test suite — including the real-ffmpeg/ffprobe media tests (fixtures generated at test time), audio extraction, chunking and timestamp shifting with synthetic clips, Celery in eager mode, and a live-Redis connection check against a Redis service container — clip detection end-to-end with a fake provider and the real Ollama provider against an in-process fake server, real FFmpeg clip renders end-to-end through the API with Range delivery and download, real 9:16 short renders with burned-in captions checked against actual frame pixels, the whole smart-reframing stack (sampling with real FFmpeg, tracking, path planning, the analysis job and API, and a moving-crop render verified frame by frame against a synthetic moving marker) — after installing the Noto fonts and checking that FFmpeg provides `libx264`, `aac`, libass and the layout filters, that fontconfig resolves the caption fonts and that a probe caption really draws text (`REQUIRE_LIBASS=1`: caption tests cannot skip), font probes proving the caption, Arabic and emoji families resolve and really draw (`scripts/caption_font_probe.py`), an end-to-end word-synced caption render with a hook checked on decoded frames (`scripts/dynamic_caption_probe.py`), an audio-mix matrix with measured ducking and loudness (`scripts/audio_mix_probe.py`), a render of the deepest allowed smart-crop path on the runner's FFmpeg (`scripts/smart_crop_probe.py`), a guard against tracked model weights or media, and finally a tiny real worker smoke (`scripts/celery_smoke.py`: start a worker, round-trip `ping`, verify the transcription, clip detection, clip rendering, short-form edit, smart-reframe and caption-timing tasks are registered, stop). The face detector is tested against a fake ONNX session, so CI never downloads a model. Speech-model inference is mocked and `HF_HUB_OFFLINE=1` guarantees CI never downloads a model; `OLLAMA_BASE_URL` points at a closed port so no real inference can happen; there is no OpenAI key in CI. The backend job also builds MinIO from source and runs the storage suites against it (required, never skipped). A **production-containers** job builds every image, starts the HTTPS Compose stack, smoke-tests it through the proxy (upload to MinIO, Range, Secure cookies), runs a backup, verification and disposable restore inside the stack, and checks for non-root users and for any secret fragment in the logs; a **security** job scans the repository for credentials and audits Python and production JavaScript dependencies. YouTube publishing is tested on mocks only. CI validates only — nothing is deployed.

Development happens on feature branches merged through pull requests; see [CLAUDE.md](CLAUDE.md#git-workflow).

## Localization: Global + Morocco Mode (future)

PeakSift will ship a **Global** experience available to everyone.

**Morocco Mode** is a planned future localization layer that *extends* the Global experience — users keep every Global tool and library, plus Darija-aware analysis, Moroccan cultural context, local sound effects and creator assets, and Morocco-specific clip suggestions. It is not a separate app, and **it is not implemented**: only its UI architecture exists, as a preview behind `NEXT_PUBLIC_MOROCCO_MODE_PREVIEW`, where every Moroccan capability reads "Not available yet".

## Repository structure

```
PeakSift-AI/
├── frontend/             # Next.js app — see frontend/README.md
├── backend/              # FastAPI service — see backend/README.md
├── deploy/               # Production images, HTTPS proxy, Compose stack, backup/smoke scripts — see deploy/README.md
├── docs/                 # Architecture, milestones, feature references, production, publishing, YouTube setup, user guide
├── docker/               # PostgreSQL init script for Docker Compose
├── docker-compose.yml    # Local PostgreSQL
└── .github/workflows/    # CI
```
