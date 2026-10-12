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

## Milestone 2 — Video Upload V0.2

- Upload long-form video files to object storage
- Store media and basic metadata on a project

## Milestone 3 — Transcription V0.3

- Extract audio (FFmpeg) and generate timestamped transcripts

## Milestone 4 — AI Clip Detection V0.4

- Identify candidate moments worth clipping
- Score and rank candidates

## Milestone 5 — Clip Generation V0.5

- Cut selected moments into short-form vertical clips

## Milestone 6 — Creator Intelligence & Metadata

- Titles, hooks, descriptions, and other metadata for generated clips

## Later

- Clip editor (captions, hooks, sound effects)
- Global asset libraries
- Morocco Mode (localization layer extending Global)
- Additional localization
