# CLAUDE.md

Guidance for Claude Code (and any AI assistant) working in this repository.

## Product vision

PeakSift AI — *"Find the moments worth clipping."* — is a short-form clipping and creation platform (same general category as StreamLadder).

Long-term:
- Creators upload long-form videos, streams, podcasts, interviews, or recordings.
- AI identifies the strongest moments worth clipping.
- Candidate clips are ranked.
- Clips are edited for TikTok, YouTube Shorts, and Instagram Reels.
- Later: captions, hooks, sound effects, creator assets, and export tools.

## Global + Morocco Mode

- **Global** is the base experience, available to everyone.
- **Morocco Mode** (V1.8) *extends* Global — it is not a separate app and never hides a Global tool, template or asset. It adds only what is real: Darija hooks from the creator's own words, curated Morocco formats on existing settings, the creator's own Moroccan visuals and sounds (local-first, Global kept), market-aware Auto Edit and Ask PeakSift answers (see [docs/morocco-mode.md](docs/morocco-mode.md)). Market (`global`/`ma`) and content language are separate.
- Never show invented Darija, sounds, trends, places, assets, figures or audience claims; nothing is "trending" (there is no trend source — `MarketTrendProvider` is documentation only). Do not add other markets, trend sources or model-written Darija until explicitly instructed.

## Current state

**Milestones 1–10 are complete** (see [docs/milestones.md](docs/milestones.md)): landing page, email/password auth, owner-scoped projects, dashboard, source-video upload with ffprobe metadata and preview, background transcription (Redis + Celery, normalized audio, chunking, faster-whisper / OpenAI providers, timestamped transcript API and viewer), and AI clip detection (transcript windows → Ollama / OpenAI structured output → validation → ranking → candidates with preview and save/dismiss; see [docs/clip-detection.md](docs/clip-detection.md)), clip generation (candidate → background FFmpeg render → validated private MP4 with preview and download; see [docs/clip-generation.md](docs/clip-generation.md)), and short-form editing (ready clip → 9:16 center crop / blur background / fit with transcript captions burned in by libass → validated private short with preview and download; see [docs/short-form-editing.md](docs/short-form-editing.md)), and smart reframing (sampled frames → local YuNet face detection → tracking → smooth 9:16 crop path → moving FFmpeg crop, with centre and manual focal-point fallbacks; see [docs/smart-reframing.md](docs/smart-reframing.md)), and dynamic captions (faster-whisper word timing per clip → validated `caption_words` → word-aware cues → `caption_v2` libass captions with the active word emphasised, four creator presets, a social safe area and an opening hook, previewed live in the editor; see [docs/dynamic-captions.md](docs/dynamic-captions.md)), and audio & sound design (private project audio uploads validated by ffprobe with waveform peaks → an edit's `audio` section: levels, music start/loop/fades, `sidechaincompress` ducking presets, timed sound effects → FFmpeg mix in the attempt workspace → −1 dBFS limiter + two-pass `loudnorm` to −14 LUFS → AAC in the short; editor Audio section with a video-clocked preview; see [docs/audio-sound-design.md](docs/audio-sound-design.md)), and production & publishing V1.0 (private S3-compatible media storage behind one storage contract, deletion and cleanup, strict production configuration, health checks, redacted JSON logs with request ids, Redis rate limits, security headers, verifiable backups, production containers behind HTTPS, and YouTube publishing with upload-only OAuth, encrypted tokens and duplicate-free resumable uploads; see [docs/production.md](docs/production.md) and [docs/publishing.md](docs/publishing.md)), with tests and CI; V1.0 is released as v1.0.0.

**V1.1 B-roll & Visual Enrichment: implementation complete, pending CI/merge/release** (stacked
PRs waiting for GitHub Actions; not merged, not tagged): a per-project visual library
(validated, normalized images and B-roll videos with thumbnails, descriptions and tags),
local-AI B-roll suggestions with a keyword fallback, grounding and density rules, matching to
the creator's own assets, and an edit `visuals` section (cutaway, picture-in-picture, overlay,
fades) composited between framing and captions; see
[docs/broll-visual-enrichment.md](docs/broll-visual-enrichment.md).

**V1.2 Auto Edit & Creator Intelligence: implementation complete locally, pending
CI/merge/release** (stacked PRs on top of the unmerged V1.1 stack; not merged, not tagged):
versioned creator recipes, a local Ollama planner and a deterministic fallback behind a
handle-based contract, an authoritative server validator, a fenced planning job, the Auto
Edit API and review page, editor hydration from versions and plans, B-roll "used" state from
current visuals and a fresh asset chooser; see [docs/auto-edit.md](docs/auto-edit.md).

**V1.3 Semantic Asset Intelligence: implementation complete locally, pending
CI/merge/release** (stacked PRs on top of the unmerged V1.2 stack; not merged, not tagged): local
CLIP ViT-B/32 embeddings of every visual asset (onnxruntime, pinned model, pgvector storage, model
identity and stale detection), background image indexing and bounded video frame sampling, hybrid
search ("Search your visuals") with strong / possible tiers and benchmark-calibrated thresholds,
semantic B-roll matching with scene offsets, Auto Edit placing strong matches only (planner
contract v2), match previews, index states and retries; see
[docs/semantic-assets.md](docs/semantic-assets.md).

**V1.4 Performance Analytics & Learning: implementation complete locally, pending
CI/merge/release** (stacked PRs on top of the unmerged V1.3 stack; not merged, not tagged):
published content linked from publish jobs with immutable provenance, an explicit read-only
YouTube analytics permission upgrade, YouTube Data + Analytics providers and a deterministic
fake, a fenced sync pipeline with Celery beat, the Analytics pages, early windows and the
creator's own baseline, a deterministic insights engine with a corrected significance test, and
optional Auto Edit hints; see [docs/performance-analytics.md](docs/performance-analytics.md).

**V1.5 Creator Experience & Modern Workspace: implementation complete locally, pending
CI/merge/release** (stacked PRs on top of the unmerged V1.4 stack; not merged, not tagged): one
workspace navigation (sidebar, Home, project tabs), a refined design system and status language,
Home and project overviews from owner-scoped summaries with tested next-best-action rules,
guided Short creation (Start → Style → Review → Render), the editor with a dominant preview and
five tool groups, moments best first with grounded labels, a search-first visual library,
analytics that answer "How are my Shorts doing?", a terminology/feedback pass, responsive and
accessibility hardening (112/112 browser checks), and creator-journey acceptance; see
[docs/creator-experience.md](docs/creator-experience.md) and [docs/design-system.md](docs/design-system.md).

**V1.6 Creator Copilot & Content Strategy: implementation complete locally, pending
CI/merge/release** (stacked PRs #216–#227 on top of the unmerged V1.5 stack; not merged, not
tagged): *Ask PeakSift* — a bounded owner-scoped context with handles, per-project conversations,
a local Ollama assistant behind a strict JSON contract, allow-listed actions re-checked on click,
one next-best-action engine shared with Home, content strategy and grounded Short idea cards,
the panel and a ⌘K command menu, prompt-injection hardening, and PeakSift's own answers for what
it knows exactly; see [docs/creator-copilot.md](docs/creator-copilot.md).

**V1.7 Brand Studio & Reusable Templates: implementation complete locally, pending
CI/merge/release** (stacked PRs #228–#238 on top of the unmerged V1.6 stack; not merged, not
tagged): brands (colours with contrast checks, a logo from the creator's images, an end-card
line) and versioned templates (allow-listed framing, captions, hook, visuals, sound, logo and
end-card settings), brand rendering from the edit snapshot (logo placement policy, caption
emphasis, hook accent, silent end card), Auto Edit with frozen templates and a documented
precedence, Brand Studio, the template builder and library, the create flow and editor
integration (Save as / Update template, explicit only), Ask PeakSift about brands and
templates, hardening and a real-render release gate; see [docs/brand-studio.md](docs/brand-studio.md).

**Visual UI/UX overhaul: implementation complete locally, pending CI/merge/release** (stacked PRs
#239–#246 on top of the unmerged V1.7 stack; not merged, not tagged): warm design tokens and
primitives (`VideoFrame`, `PeakArt`, tinted status pills), a new app shell, Home and the project
workspace (creator workflow, moment cards with real frames), the editor (Template/Brand chips, a
Brand tool), Brand Studio library cards, Ask PeakSift tiles and idea cards, creator analytics, a
feature-gated **Morocco Mode preview** (UI architecture only; superseded by V1.8) and a 330/330
browser audit; see
[docs/creator-experience.md](docs/creator-experience.md) and [docs/design-system.md](docs/design-system.md).

**Visual timeline & editor pass: implementation complete locally, pending CI/merge/release**
(stacked PRs #247–#255 on top of the unmerged UI/UX stack; not merged, not tagged): the Short
editor's timeline — a duration-aware scale, an animation-frame playhead, seeking by click, drag
or keyboard, Video / Opening / Visuals / Captions / Sound / Music tracks derived from the edit's
settings, drag, resize and snapping of supported timing with validation and keyboard editing,
preview sync, tooltips and an honest render state, panels that follow the selection, phones and
touch screens, and a real-render release gate (`scripts/timeline_acceptance.py`); see
[docs/editor-timeline.md](docs/editor-timeline.md).

**Shorts Library & Publishing Center: implementation complete locally, pending CI/merge/release**
(stacked PRs #257–#264 on top of the unmerged #256; not merged, not tagged): the Short as a
first-class object — `/shorts` (every Short and draft with one creator-level status derived in
`services/shorts_library.py`, filters, search, sort, valid actions only), `/shorts/[id]` (player,
the state's one next action, provenance as recorded, versions, a publishing panel with
connect-and-return, real stages and safe retry, and performance from V1.4 analytics), Home, the
project, Analytics, the editor and the next step leading to it, phones and accessibility; see
[docs/shorts-library.md](docs/shorts-library.md).

**V1.8 Morocco Mode: implementation complete locally, pending CI/merge/release** (stacked PRs
#265–#274 on top of the unmerged #264; not merged, not tagged): markets and content languages
(`global`/`ma`, creator default, per project, frozen in each Short), hedged language detection
with Darija markers, grounded hook ideas (the clip's own lines; Darija across scripts by
transliteration only; the local model rewrites only French ↔ English), seven curated Morocco
formats, creator-labelled assets (origin with licence, market, category, location) with
local-first search inside strength tiers, market-aware Auto Edit, Ask PeakSift's own Morocco
answers with a stereotype screen, the live `/morocco` and Creator Kit, and the release gates
(`scripts/morocco_acceptance.py`, `scripts/darija_quality.py`); see
[docs/morocco-mode.md](docs/morocco-mode.md).

**Built after V1.8 at the creator's explicit instruction (26 November 2026), from the
StreamLadder benchmark in
[docs/product-research/streamladder-live-benchmark.md](docs/product-research/streamladder-live-benchmark.md):**
quick start on Home (one upload → project, transcription, then moments by themselves), Find
Clips (plain-language search of the transcript; a kept result is a saved moment), scheduled
publishing (a `scheduled` publish job released by Celery beat, and the `/schedule` calendar),
posting times, and publishing to TikTok and Instagram Reels behind the same contract (a
connection per platform, `services/publishing/platforms.py`; each switched on by its own
setting);
see [docs/creator-experience.md](docs/creator-experience.md) and
[docs/publishing.md](docs/publishing.md). On `main` since 26 November 2026; not tagged. Then,
from the StreamLadder clip-editor study (28 November 2026), **Tighten**: remove the pauses
between words and cut parts by hand ([docs/tighten.md](docs/tighten.md)), and **creator caption
styles** — 14 presets with six pinned open-licence display fonts ([docs/caption-styles.md](docs/caption-styles.md)). The
list below still applies to everything else.

**No later milestone has been defined.** Do not start new features (autonomous or scheduled publishing, multi-platform publishing,
generated images, video, music or sound effects, voice cloning, performance or virality
scores or predictions, automatic thumbnails, analytics beyond V1.4 (other platforms, revenue,
audience demographics, competitor or cross-creator benchmarking, scraping), A/B publishing or
automatic title changes, collaboration, billing, custom model training,
stock media, internet image
search or generated imagery, image generation or editing, video generation, facial identity recognition, OCR, zoom/pan or keyframed visuals,
split screen, speaker diarization or active-speaker detection, generic object tracking, dynamic zoom, keyframe/timeline editor, manual caption timing or per-word positioning, custom fonts, a graphic design tool or motion graphics, template marketplaces or generated branding, transitions beyond a fade, music or sound-effect libraries, generative audio, stem separation, beat-synced editing, a multitrack/DAW timeline, publishing to platforms other than YouTube, scheduled or multi-platform publishing, comments, thumbnails, editing or deleting published videos, Kubernetes or multi-region deployment, other markets, market trends or trend sources, Darija written by a model, payments) until explicitly instructed.

## Stack (as built)

- Frontend: Next.js (App Router), TypeScript, Tailwind CSS in `frontend/`
- Backend: FastAPI, SQLAlchemy 2 (synchronous), Alembic, psycopg 3, pydantic-settings in `backend/`
- Database: PostgreSQL
- Auth: Argon2id (`pwdlib`), HS256 JWT (`PyJWT`) in an HttpOnly `SameSite=Lax` cookie
- Media: storage contract with a local directory (`MEDIA_ROOT`) or a private S3-compatible bucket (`STORAGE_BACKEND`, boto3); jobs work in per-attempt scratch directories under `WORK_ROOT`; `python -m app.cli.media` (migrate, verify, cleanup) and `python -m app.cli.backup` (create, verify, restore-test); `ffprobe`/`ffmpeg` via argument-list subprocesses with timeouts; `python-multipart` for uploads
- Background jobs: Celery on Redis (`app/workers/`), one job per worker, database is the source of truth
- Speech-to-text: provider contract in `app/services/transcription/`; `faster-whisper` (local, lazy) and the OpenAI SDK (`whisper-1` for timestamps); provider is server configuration
- Clip detection: provider contract in `app/services/clip_detection/` (windowing, validation, ranking, pipeline); `ollama` (httpx against an operator-configured endpoint) and `openai` (structured outputs); users choose provider/model only from server allow-lists
- Tooling: pytest, Ruff, ESLint, GitHub Actions (backend job installs FFmpeg with libass and the Noto fonts)
- Clip rendering: `app/services/clip_render/` (artifact storage, FFmpeg renderer, Celery pipeline); output profile `source_mp4_v1` = fast-start MP4, libx264 + aac, source geometry
- Short-form editing: `app/services/clip_edit/` (edit config, 9:16 composition, transcript captions, ASS styles, edit artifacts, Celery pipeline); profile `vertical_1080x1920_v1`; libass + fontconfig fonts (Noto Sans), never committed font files
- Smart reframing: `app/services/reframe/` (config snapshot, FFmpeg frame sampling, detector contract, YuNet face detector on onnxruntime, tracking, crop path, Celery pipeline); rendered by `clip_edit/smart_crop.py` as a time-varying FFmpeg crop. The model is installed by `scripts/fetch_reframe_model.py` (pinned sha256), never committed or auto-downloaded
- Dynamic captions: `app/services/caption_timing/` (config snapshot, word-timing provider contract, faster-whisper word timestamps, validation, Celery pipeline) and `clip_edit/` (`dynamic_cues.py`, `caption_v2.py`, `caption_metrics.py`, `safe_area.py`, `hook.py`, `emoji.py`, `dynamic_text.py`); fonts Noto Sans, Noto Sans Arabic and a monochrome emoji font (Symbola or Noto Emoji), never committed
- Production: `APP_ENV=production` validation in `app/core/config.py`; `app/core/observability.py` (request ids, redacted JSON logs), `rate_limit.py` (Redis), `security_headers.py`; `/health/live`, `/health/ready`, `python -m app.cli.health`; `deploy/` (non-root API image with gunicorn + uvicorn-worker, worker image, Next standalone image, MinIO built from source, nginx HTTPS proxy, Compose stack)
- Publishing: `app/services/publishing/` (AES-256-GCM token encryption, YouTube OAuth with google-auth-oauthlib, publish jobs and metadata rules, provider contract, YouTube resumable upload over httpx, fake provider, uploader, pipeline); `app/api/publishing.py`, `publish_jobs.py`; frontend `/settings` and the editor's publish dialog
- B-roll & visuals: `app/models/visual_asset.py`, `app/services/visual_assets.py` (Pillow/ffprobe validation, normalization, thumbnails), `app/models/broll.py`, `app/services/broll/` (providers, validation, grounding, pipeline, matching), `app/services/visuals/` (config, assets, layout, transitions, compositor); creator-supplied visuals only — never fetch, search or commit media; fixtures are generated with Pillow/FFmpeg
- Auto Edit: `app/models/auto_edit.py`, `app/services/auto_edit/` (fingerprint, state, recipes, contract, ollama, fallback, planners, validation, sources, config, pipeline, benchmark), `app/api/auto_edit.py`, `app/workers/auto_edit_tasks.py`, `scripts/auto_edit_benchmark.py`; frontend `components/app/auto-edit-view.tsx`, `lib/auto-edit*.ts`, `lib/edit-draft.ts`
- Semantic assets: `app/models/semantic.py` (`VisualSemanticIndex`, `AssetEmbedding`, pgvector `vector(512)`), `app/services/semantic/` (contract, vectors, images, clip_onnx, fake, registry, indexing, sampling, lifecycle, search, matching, benchmark), `app/workers/semantic_tasks.py`, `app/cli/semantic.py`, `scripts/fetch_semantic_model.py` (pinned files + sha256), `scripts/semantic_benchmark.py`, `scripts/semantic_search_probe.py`; frontend `lib/visual-search.ts`, `components/app/use-visual-search.ts`. Model weights are never committed or downloaded automatically; creator media never leaves the server
- Creator workspace: `app/services/workspace_summary.py` + `app/api/workspace.py` (`/workspace/home`, `/projects/{id}/summary`; not to be confused with `app/services/workspace.py`, the job scratch directories); frontend `components/app/app-shell.tsx`, `home-view.tsx`, `project/`, `create/`, `components/ui/` (design system), `lib/navigation.ts`, `lib/workspace*.ts`, `lib/status.ts`, `lib/moments.ts`, `lib/editor-tools.ts`, `lib/upload-batch.ts`
- Performance analytics: `app/models/performance.py`, `app/models/insight.py`, `app/services/performance/` (provenance, content, metrics, provider, youtube, fake, factory, sync, lifecycle, summary, normalization, insights, profile, retention), `app/api/performance.py`, `app/workers/performance_tasks.py` (Celery beat schedule), `app/cli/performance.py`, `scripts/insights_benchmark.py`; frontend `/analytics`, `components/app/analytics*`, `lib/performance*.ts`
- Shorts library: `app/services/shorts_library.py` (the one status derivation: `publication`,
  `short_status`, `draft_status`; library and detail queries), `app/api/shorts.py`
  (`GET /shorts`, `GET /shorts/{id}`), `app/schemas/shorts.py`; frontend `/shorts`,
  `/shorts/[shortId]`, `components/app/shorts/` (library view, card, detail view, publishing and
  performance panels), `lib/shorts.ts`, `lib/shorts-rules.ts` (status words, filters, search,
  sort, actions, publishing and performance views), `scripts/shorts_acceptance.py` (read-only
  release gate)
- Editor timeline: `frontend/lib/timeline.ts` (scale, items, drag, snapping, sync, render state; unit-tested), `lib/reveal.ts`, `components/app/editor/timeline/` (`timeline.tsx`, `tracks.tsx`), `backend/scripts/timeline_acceptance.py` (real-render gate)
- Visual shell and primitives: `app/globals.css` (tokens), `components/ui/` (`video-frame.tsx`, `peak-art.tsx`, `status-pill.tsx`), `components/app/app-shell.tsx`, `shell-search.tsx`, `page-header.tsx`
- Creator Copilot: `app/models/copilot.py` (`CopilotThread`, `CopilotMessage`),
  `app/services/copilot/` (context, history, prompt, contract, provider, answers, safety, ideas,
  actions, service), `app/services/next_action.py`, `app/services/strategy.py`,
  `app/services/routes.py`, `app/api/copilot.py`, `scripts/copilot_acceptance.py` (real-model
  release gate); frontend `components/app/copilot/`, `components/app/command-menu.tsx`,
  `lib/copilot.ts`, `lib/copilot-rules.ts`, `lib/command-menu.ts`
- Brand Studio: `app/models/brand.py` (`BrandProfile`), `app/models/short_template.py`
  (`ShortTemplate`), `app/services/branding/` (colors, profiles, template_config, templates),
  `app/services/auto_edit/template.py`, `app/services/clip_edit/brand.py` and `brand_render.py`,
  `app/services/copilot/branding.py`, `app/api/brand.py`, `scripts/brand_acceptance.py`
  (real-render release gate); frontend `/brand`, `components/app/brand/`,
  `components/app/editor/brand-strip.tsx`, `brand-logo-layer.tsx`, `lib/brand.ts`,
  `lib/brand-rules.ts`, `lib/template-rules.ts`
- Morocco Mode: `app/services/markets.py` (market profiles, `snapshot`), `language.py` (hedged
  detection, matching-only folding), `hooks.py` (transcript ideas, transliteration, reliable-pair
  rewrites, `check`), `asset_labels.py`, `branding/market_starters.py`, `copilot/market.py`,
  `app/api/markets.py`, `hooks.py`; `scripts/morocco_acceptance.py` (real-model, real-render
  release gate), `scripts/darija_quality.py` (manual set); frontend `/morocco`, `/morocco/kit`,
  `components/app/morocco/`, `editor/hook-ideas.tsx`, `project/project-market.tsx`,
  `project/project-sounds.tsx`, `asset-labels-form.tsx`, `lib/morocco.ts`, `lib/markets.ts`,
  `lib/hooks*.ts`, `lib/asset-labels.ts`
- Audio & sound design: `app/models/audio_asset.py`, `app/services/audio_assets.py` (upload validation, probing, waveform), `app/services/audio_mix/` (config, plan, ducking, loudness, mixer); user-supplied audio only — never commit audio files or fetch audio from the internet; test audio is generated with FFmpeg

## Conventions

- Schema changes go through Alembic: edit models, `alembic revision --autogenerate`, review the file, commit it. CI runs `alembic check`.
- Backend tests use `TEST_DATABASE_URL` (default `peaksift_test`); never point tests at a development database.
- Keep ORM models, request schemas and response schemas separate. Never expose `password_hash` or other internals.
- Every project endpoint is scoped to the current user; return `404` rather than revealing another user's resources.
- Frontend: call the API only through `lib/api.ts`; keep auth state in `AuthProvider`; no tokens in browser storage; the API is the security boundary.
- Prefer small, honest UI: real data or clearly labelled placeholders, never fake numbers.
- Media: never use a browser-supplied filename as a path; storage keys are generated and reach storage only through the `StorageProvider` contract in `app/services/storage.py` (locally, `LocalStorageProvider.path_for` is the path chokepoint); media endpoints stream through `stream_object`. Never commit anything under `media/`; test fixtures are generated with `ffmpeg` at test time. External tools are run with argument lists and timeouts, never `shell=True`, and their stderr is never stored or returned.
- Error messages and responses must not contain filesystem paths, storage keys, submitted values, API keys or task ids.
- Storage: persistent media goes only through `StorageProvider` (never `MEDIA_ROOT` paths in pipelines); jobs fetch inputs into their attempt's scratch and `put_file` validated results; "missing" (`ObjectNotFound`) and "unavailable" (`StorageUnavailable` → 503) stay distinct; buckets are private (no ACLs, no public or presigned URLs). Deleting is rows first, then files; leftovers are cleanup's job.
- Secrets: never commit or log credentials, refresh tokens, encryption keys or upload session URIs; settings report problems by name only (`hide_input_in_errors`); `.env.example` files hold placeholders only (CI scans the repository).
- Publishing: the YouTube scope is `youtube.upload` only; OAuth state is single-use, user-bound, hashed and short-lived; refresh tokens are stored only encrypted (associated data binds user, provider, key version); metadata follows YouTube's rules and is refused, never truncated; private by default; the session URI is stored (encrypted) before any byte is sent and uploads always resume from YouTube's confirmed offset — never create a second video, never claim "published" without YouTube saying so, and never fabricate real-provider evidence (the fake provider's results are labelled simulated).
- Transcript timestamps are never fabricated: a provider without segment timestamps is refused; segments are validated (and re-validated in the pipeline) and shifted to absolute time before persisting. Provider SDK objects never leave the provider module.
- Celery tasks receive database ids only and must stay idempotent on database state; never load a speech model at import or API startup. Generate a job's task id before committing its row (fencing token), then enqueue with that id.
- Short-form edits are derived artifacts: never modify the V0.5 clip file. Transcript text is untrusted — it reaches captions only through `escape_ass_text`, never a shell, filtergraph or path; edit options are allow-listed enums (no user ASS, fonts, filters or paths). `caption_v1` captions use persisted transcript timing (phrase-level); `caption_v2` word-synced captions use only persisted, re-validated `caption_words` from a real word-timing provider — never label proportional or generated timing as aligned, never call phrase timing word-synced, never paraphrase transcript text or group cues with an LLM. Old edits keep their renderer; V0.6 fingerprints must not change.
- Audio: an edit's `audio` section appears in the snapshot only when used (edits without it keep their fingerprints and render the clip's audio exactly as before). Levels are dB, times clip-local seconds; only validated numbers and allow-listed presets reach FFmpeg, files only as inputs. Asset references are checked for project ownership and kind at the API and again at render. The video's duration is authoritative. Never describe ducking as voice isolation, the loudness target as a platform standard, or the browser preview as the final mix.
- Visuals: an edit's `visuals` section appears only when used (old fingerprints unchanged). Uploads are typed by their contents, never names; images are re-encoded. B-roll suggestions are untrusted until validation and grounding — never clamp, repair or invent them, and keep the method label honest (local AI vs keyword fallback). Matches are offered, never placed. Only validated numbers and allow-listed enums reach the filtergraph; asset files are inputs only; B-roll is always muted; captions and the hook stay on top. Asset ownership and kind are checked at the API and again at render; an asset used by an edit cannot be deleted.
- Semantic assets: vectors are unit-length, validated (`to_unit`) and compared only within one identity (provider, model, revision, embedding version, dimension) — never mix models; a model change makes indexes stale. Providers take decoded canonical pixels, never paths; storage goes through `StorageProvider` into the attempt workspace. Indexing never blocks an upload or makes an asset unusable; failures carry safe messages. Search and matching are project-scoped; responses and logs never carry vectors, similarities, scores or model locations. Tiers are strong / possible with per-model versioned thresholds (calibrated by `scripts/semantic_benchmark.py`, never shown as percentages); only strong matches may be placed automatically, and video offsets are computed by the server. CI uses the deterministic fake provider and never downloads weights.
- Auto Edit: the model proposes, the server decides. Planners see facts and symbolic handles only (never ids); proposals are strict JSON of creator-level choices; `validate_plan` maps handles to ids, enforces the recipe and checks every choice against what exists, degrading optional choices with a creator-facing note. Never let model output become filters, paths, ids, providers, styles, coordinates or volumes; never pick music without the creator's explicit choice; hooks must be grounded (the clip's words, no new names or numbers); explanations are product copy, never prompts or reasoning. Auto Edit consumes completed analyses and never starts other jobs. Plans are applied only through `create_or_reuse_edit`; an applied plan never changes. Recipes are versioned; old plans keep their version. No performance or virality scores.
- Creator experience: every screen answers where am I, what is happening, what next — in the creator's words (never worker, provider, candidate, pipeline, fingerprint, embedding, model backend). Next steps come from real summaries through the server's deterministic next-action engine (`app/services/next_action.py`, shared by Home, the Overview and the Copilot); show a step or a figure only when its data exists ("—" for unreported). Status language is Waiting / a specific step / Ready / Needs attention (`lib/status.ts`). Toasts only confirm small completed actions (problems stay inline); confirm only destructive actions. Touch targets are 44 px on touch screens; every key screen must pass the browser audit (no overflow, no axe WCAG 2.1 AA violation, no console errors) at 1440/1280/1024/768/430/390/375. "Nothing yet" checks use `?optional=true` (200 null) rather than a logged 404; API changes for the UI are additive.
- Performance analytics: observational only — never predictions, virality scores or causal claims ("has tended to", "associated with", "in your recent uploads"). Analytics access is an explicit, creator-started upgrade (`youtube.readonly` + `yt-analytics.readonly` on top of upload); never broaden publishing scopes, never save a partial grant, keep the purpose in the OAuth state, and request access tokens per use with only that use's scopes (`invalid_scope` is not `invalid_grant`). Tokens stay in the existing encrypted store. NULL is never 0 (unreported figures stay NULL, missing days stay missing); every row records its `source` (`fake` is always labelled simulated, refused in production, never compared with real data) and its view definition (`metric_version`). Link published videos from publish jobs only (never by title, never another job's or creator's row); sync only PeakSift's own uploads of creators who granted access. Compare only complete windows of one source against the creator's own median, with minimum samples; insights must pass the corrected significance test (`scripts/insights_benchmark.py` gates the false-pattern rate) and use the fixed templates. No cross-user aggregates, no audience demographics, nothing synthetic outside isolated tests; creators can delete collected metrics. Auto Edit hints are opt-in, symbolic, inside the recipe, never music.
- Creator Copilot: the model proposes, the server decides. The model sees a bounded view with
  symbolic handles (never ids, keys, paths or other creators' data) and the transcript as fenced
  untrusted DATA; its JSON is parsed by `contract.parse_reply` (unknown types and invented handles
  dropped, text cleaned, labels written by PeakSift) and screened by `safety.py` (an answer
  claiming an action is never shown; repeated instructions and unknown times are removed).
  Sentences naming an internal term (keys and handles of the view, unknown identifiers, JSON,
  `null`) are removed by `safety.drop_internal_terms`, learnt from the data rather than listed.
  Actions are navigation or Create Short only and are re-checked when clicked — never publish,
  delete or change anything from the Copilot. What PeakSift knows exactly (next step, top pick,
  unused visuals, nothing published, what has worked, how published Shorts are doing, requests
  to act, ideas without a video) is answered by `answers.py`, not the model. Never claim performance, virality or causation; observed patterns
  keep their wording. Conversations are per project, one question at a time, clearable.
- Editor timeline: it shows the edit, it does not own it — items are derived from the editor's
  settings (`timelineItems`) and every change goes through the same setters the forms use (no
  second state; the server validates again at render). Only timing the edit supports may change
  (`editableEdges`); invalid moves go back with the reason, never get repaired. Playhead and
  "playing" marks update the DOM from one animation-frame clock (no React render per frame);
  timeline and preview use the same cue rule (`cueAt`). Selecting never scrolls the page
  (`revealInPanel`). Keyboard paths exist for every drag; 44 px targets on touch. Not an NLE: no
  ripple, keyframes or extra tracks.
- Caption styles (`docs/caption-styles.md`): still presets only. Display fonts are an allow-list
  (`caption_fonts.py`), pinned files installed by `scripts/fetch_caption_fonts.py`, never
  committed or downloaded by the app, used only when they match their sha256, copied into the
  attempt workspace (`fontsdir=fonts`); a missing font makes the style unavailable, never a silent
  substitute. Emphasis tags come only from the preset. One word and Reveal need real word timing.
  The four original presets render exactly as before.
- Tighten (`docs/tighten.md`): an edit's `cuts` section lists removed ranges in the clip's own
  time, only when used (old fingerprints unchanged); validated and merged, never repaired.
  Everything the creator places is on the Short's timeline; only source data (word timings,
  transcript phrases, the crop path) is moved onto it (`cuts.py`). The render tightens the clip in
  the attempt workspace first (`tighten.py`), then composes as before. Pauses come only from real
  word timing; the editor mirrors the server's rules in `lib/cuts.ts`.
- Shorts library: a Short is one rendered version (`ClipEdit`); a draft is a clip without a
  version. Its creator-level status is derived only in `services/shorts_library.py` and worded
  only in `lib/shorts-rules.ts` — never re-derive status words on a page. Never call an upload
  "Published" before YouTube confirmed it (`on_youtube`); a video YouTube has outranks a later
  failed attempt; real stages only, no guessed percentages. Provenance shows the template and
  brand recorded with the version (`origin`), never today's template. Show only valid actions
  (no disabled menus); nothing publishes without the creator's click; the connect return address
  must pass `safeReturnPath`. Figures only as reported ("—" otherwise). Library queries stay a
  fixed number of statements (tested).
- Morocco Mode: market and language are separate; a market's facts appear in plan
  fingerprints, Copilot views, provenance and search order only when set (Global unchanged).
  Darija reaches a creator only as their own words — verbatim, or transliterated between scripts
  and labelled "check the spelling"; the model never writes Darija and rewrites only reliable
  pairs, each result checked. Formats are curated (never "trending"); assets carry the creator's
  origin (licensed needs its licence), market, category and a location from the market's list —
  never guessed from pixels. Local first only *within* a strength tier; Auto Edit places strong
  matches only. Ask PeakSift answers market facts itself, never speaks for an audience, and
  `safety.drop_generalizations` removes stereotypes. Right-to-left creator text uses
  `dir="auto"`. No flags or national colours; the mode is said in words.
- Brands and templates are preferences; renders read only the edit snapshot. An edit's `brand`
  section appears only when used (old fingerprints unchanged); plans freeze the template version
  and brand, and a template or brand change never touches an existing plan or edit. Colours are
  hex only and contrast-checked (an unreadable colour is dropped, never adjusted); template
  settings are allow-listed and versioned; only validated numbers, colours and enums reach the
  filtergraph, the logo is an input file only (ownership and kind checked at the API and at
  render), text only through `escape_ass_text`. The logo placement policy is deterministic
  (`logo_plan`). Precedence: hard constraints > this Short > template > brand > recipe > hints >
  planner. Templates never pick music; saving or updating a template is always the creator's
  explicit action. No custom fonts, motion graphics, marketplaces or generated branding.
- Clip candidates: everything a model returns is untrusted until `validation.py` has snapped it to transcript lines and checked bounds; never clamp or invent values, never store a model's quotation as the transcript excerpt, keep scores on the documented 0–100 editorial scale and never present them as performance predictions.
- Clip rendering: boundaries always come from the persisted candidate, never from the request; re-encode (never `-c copy`); write to the attempt's temp file, validate with ffprobe, rename atomically, and only then mark `ready` in the same commit as `storage_key`. Every pipeline commit checks the fencing token. Clip media is private and served only through the owner-checked Range endpoints.
- Smart reframing: positions are fractions of the display-oriented source (x right, y down). Detector output is untrusted until `normalize_detection`; "no face" (empty list) and "detector broken" (`DetectorUnavailable`/`DetectorFailure` → failed analysis) must stay distinct. Every tuning value is server configuration in the versioned snapshot. Persisted keyframes are re-validated before rendering and only module-formatted numbers reach the filtergraph. Never load a detector at import or startup, never download or commit model weights, and never describe the feature as speaker detection.
- Tests: Celery eager mode, mocked speech models, a fake OpenAI client, a fake ONNX session, moto and a live MinIO for S3 (`TEST_S3_*`, required in CI), a mocked YouTube and the deterministic fake metrics provider (`PERFORMANCE_PROVIDER=fake`); CI sets `HF_HUB_OFFLINE=1`, never has an API key or Google credentials, never downloads a model and never calls Google.
- Read `README.md`, `docs/architecture.md`, `docs/clip-detection.md`, `docs/clip-generation.md`, `docs/short-form-editing.md`, `docs/editor-timeline.md`, `docs/shorts-library.md`, `docs/smart-reframing.md`, `docs/dynamic-captions.md`, `docs/audio-sound-design.md`, `docs/broll-visual-enrichment.md`, `docs/auto-edit.md`, `docs/semantic-assets.md`, `docs/performance-analytics.md`, `docs/creator-experience.md`, `docs/design-system.md`, `docs/creator-copilot.md`, `docs/brand-studio.md`, `docs/morocco-mode.md`, `docs/production.md`, `docs/publishing.md`, `docs/youtube-setup.md`, `deploy/README.md`, `backend/README.md` and `frontend/README.md` before changing the corresponding area.

## Working rules

1. **Inspect existing code before changing it.** Read the relevant files first; match existing conventions.
2. **Build one feature at a time.** Keep each task small and focused.
3. **Do not overengineer.** Build what the current task needs — no speculative abstractions.
4. **Never commit secrets.** No API keys, tokens, passwords, or credentials in the repo.
5. **Use environment variables** for configuration and secrets. Commit `.env.example` files only, never `.env`.
6. **Test important backend functionality.** Run `pytest`, `ruff check`, `ruff format --check`, `npm run lint`, `npm run build` before committing.
7. **Report after every task:** list changed files and test results.
8. **Never continue automatically into the next task.** Stop and wait for instructions.
9. **IMPORTANT: every change reaches GitHub immediately** — never accumulate unpushed local work. Never force-push or rewrite pushed commits.
10. **Never commit feature development directly to `main`.** Follow the Git workflow below.

## Git workflow

The GitHub history should let someone understand PeakSift's development by reading the Pull Requests. For every logical feature:

1. Make sure `main` is current (`git checkout main && git pull --ff-only`).
2. Create a descriptively named branch (`feat/video-upload-api`, `fix/login-error-copy`, `chore/...`, `docs/...`).
3. Implement the feature.
4. Run all relevant checks: `pytest`, `ruff check`, `ruff format --check`, `npm run lint`, `npm run build`.
5. Commit with meaningful messages.
6. Push the branch immediately.
7. Open a Pull Request into `main` with: a clear human-readable title, a concise summary, a **What changed** section, a **Testing** section, and any important architectural notes.
8. Wait for CI to pass.
9. Merge the PR into `main`.
10. Verify local `main` matches `origin/main`.
11. Delete the merged feature branch (remote and local).
12. Only then begin the next logical feature.
