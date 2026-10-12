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
- **Morocco Mode** (future) *extends* Global — it is not a separate app. Morocco Mode users keep all Global tools and libraries, plus: Darija-aware AI analysis, Moroccan humor and cultural context, Moroccan sound effects and creator assets, local memes/reactions, Moroccan caption styles, Morocco-specific clip suggestions, and local trend/context intelligence.
- **Do not implement Morocco Mode** until its milestone is explicitly started. Do not add speculative hooks or abstractions for it either.

## Current state

**Milestones 1–4 are complete** (see [docs/milestones.md](docs/milestones.md)): landing page, email/password auth, owner-scoped projects, dashboard, source-video upload with ffprobe metadata and preview, background transcription (Redis + Celery, normalized audio, chunking, faster-whisper / OpenAI providers, timestamped transcript API and viewer), and AI clip detection (transcript windows → Ollama / OpenAI structured output → validation → ranking → candidates with preview and save/dismiss; see [docs/clip-detection.md](docs/clip-detection.md)), with tests and CI.

**Next is Milestone 5 — Clip Generation.** Do not start it, or any later feature (cutting/exporting clips, captions, reframing, editor, Morocco Mode, payments), until explicitly instructed.

## Stack (as built)

- Frontend: Next.js (App Router), TypeScript, Tailwind CSS in `frontend/`
- Backend: FastAPI, SQLAlchemy 2 (synchronous), Alembic, psycopg 3, pydantic-settings in `backend/`
- Database: PostgreSQL
- Auth: Argon2id (`pwdlib`), HS256 JWT (`PyJWT`) in an HttpOnly `SameSite=Lax` cookie
- Media: local filesystem storage under `MEDIA_ROOT` (dev only); `ffprobe`/`ffmpeg` via argument-list subprocesses with timeouts; `python-multipart` for uploads
- Background jobs: Celery on Redis (`app/workers/`), one job per worker, database is the source of truth
- Speech-to-text: provider contract in `app/services/transcription/`; `faster-whisper` (local, lazy) and the OpenAI SDK (`whisper-1` for timestamps); provider is server configuration
- Clip detection: provider contract in `app/services/clip_detection/` (windowing, validation, ranking, pipeline); `ollama` (httpx against an operator-configured endpoint) and `openai` (structured outputs); users choose provider/model only from server allow-lists
- Tooling: pytest, Ruff, ESLint, GitHub Actions (backend job installs FFmpeg)
- Planned later: S3-compatible object storage, clip rendering

## Conventions

- Schema changes go through Alembic: edit models, `alembic revision --autogenerate`, review the file, commit it. CI runs `alembic check`.
- Backend tests use `TEST_DATABASE_URL` (default `peaksift_test`); never point tests at a development database.
- Keep ORM models, request schemas and response schemas separate. Never expose `password_hash` or other internals.
- Every project endpoint is scoped to the current user; return `404` rather than revealing another user's resources.
- Frontend: call the API only through `lib/api.ts`; keep auth state in `AuthProvider`; no tokens in browser storage; the API is the security boundary.
- Prefer small, honest UI: real data or clearly labelled placeholders, never fake numbers.
- Media: never use a browser-supplied filename as a path; storage keys are generated and resolved only through `LocalMediaStorage.path_for`. Never commit anything under `media/`; test fixtures are generated with `ffmpeg` at test time. External tools are run with argument lists and timeouts, never `shell=True`, and their stderr is never stored or returned.
- Error messages and responses must not contain filesystem paths, storage keys, submitted values, API keys or task ids.
- Transcript timestamps are never fabricated: a provider without segment timestamps is refused; segments are validated (and re-validated in the pipeline) and shifted to absolute time before persisting. Provider SDK objects never leave the provider module.
- Celery tasks receive database ids only and must stay idempotent on database state; never load a speech model at import or API startup. Generate a job's task id before committing its row (fencing token), then enqueue with that id.
- Clip candidates: everything a model returns is untrusted until `validation.py` has snapped it to transcript lines and checked bounds; never clamp or invent values, never store a model's quotation as the transcript excerpt, keep scores on the documented 0–100 editorial scale and never present them as performance predictions.
- Tests: Celery eager mode, mocked speech models and a fake OpenAI client; CI sets `HF_HUB_OFFLINE=1` and never has an API key.
- Read `README.md`, `docs/architecture.md`, `docs/clip-detection.md`, `backend/README.md` and `frontend/README.md` before changing the corresponding area.

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
