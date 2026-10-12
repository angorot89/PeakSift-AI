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

## Current milestone

**Milestone 1 — Foundation V0.1.** Scope: repository structure, documentation, and (in later tasks) minimal frontend and backend scaffolding. Out of scope: auth, database models, AI, transcription, video processing.

See [docs/milestones.md](docs/milestones.md) and [docs/architecture.md](docs/architecture.md).

## Planned tech stack

- Frontend: Next.js (React, TypeScript) in `frontend/`
- Backend: FastAPI (Python) in `backend/`
- Database: PostgreSQL
- Media storage: S3-compatible object storage
- Media processing: FFmpeg
- AI: speech-to-text + LLM-based clip analysis

## Working rules

1. **Inspect existing code before changing it.** Read the relevant files first; match existing conventions.
2. **Build one feature at a time.** Keep each task small and focused.
3. **Do not overengineer.** Build what the current task needs — no speculative abstractions.
4. **Never commit secrets.** No API keys, tokens, passwords, or credentials in the repo.
5. **Use environment variables** for configuration and secrets. Commit `.env.example` files only, never `.env`.
6. **Test important backend functionality.**
7. **Report after every task:** list changed files and test results.
8. **Never continue automatically into the next task.** Stop and wait for instructions.
9. **IMPORTANT: after every completed task, commit and push the change to GitHub before starting the next modification.**
