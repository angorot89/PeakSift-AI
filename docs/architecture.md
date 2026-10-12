# Architecture

Two sections: what is **built** (Milestone 1) and what is **planned**. Planned parts are decided milestone by milestone and may change.

## Built (Milestone 1 — Foundation V0.1)

```
┌───────────────────┐   HTTP/JSON + HttpOnly cookie   ┌───────────────────┐        ┌────────────┐
│  Next.js frontend │ ──────────────────────────────▶ │  FastAPI backend  │ ─────▶ │ PostgreSQL │
│  (App Router)     │ ◀────────────────────────────── │  SQLAlchemy 2     │        │ users,     │
└───────────────────┘                                 │  Alembic          │        │ projects   │
                                                      └───────────────────┘        └────────────┘
```

### Frontend (`frontend/`)

- Next.js App Router, TypeScript, Tailwind CSS.
- Pages: landing (`/`), `/login`, `/register`, and a signed-in area (`/dashboard`, `/projects`, `/projects/new`, `/projects/[id]`) under one route group that wraps pages in a client-side guard and an app shell.
- Auth state lives in a small React context (`AuthProvider`). On load it calls `GET /auth/me`; the backend is the authority. Tokens are never stored in JavaScript-accessible storage.
- A single fetch wrapper (`lib/api.ts`) adds the API base URL (`NEXT_PUBLIC_API_URL`), sends cookies, and turns error bodies into messages.

### Backend (`backend/`)

- FastAPI with routers for `health`, `auth` and `projects`; request/response schemas (Pydantic) are separate from ORM models.
- Settings from environment variables via pydantic-settings; `DATABASE_URL` and `SECRET_KEY` are required.
- SQLAlchemy 2 with a **synchronous** engine and one session per request (`get_db`). Async was deliberately not introduced.
- Alembic migrations are the only way the schema changes; `alembic check` runs in CI to catch model/migration drift.

### Authentication

- Passwords: Argon2id (`pwdlib`). Never logged or returned.
- Session: HS256 JWT (`PyJWT`), `sub` = user UUID, with `iat`/`exp` (default 7 days).
- Transport: `HttpOnly`, `SameSite=Lax`, `Path=/` cookie; `Secure` in production. CORS allows only the configured frontend origin, with credentials.
- Logout clears the cookie; there is no server-side revocation yet.
- Validation errors never echo submitted values.

### Data model

| Table      | Columns                                                                 |
| ---------- | ----------------------------------------------------------------------- |
| `users`    | `id` (uuid), `email` (unique, indexed), `password_hash`, `created_at`   |
| `projects` | `id` (uuid), `user_id` (FK → users, cascade delete), `name`, `status`, `created_at`, `updated_at` |

Timestamps are timezone-aware. `status` is currently always `created`.

### Testing and CI

- Backend: pytest against a dedicated PostgreSQL test database; migrations are applied at the start of the session and every test is rolled back.
- Frontend: ESLint and a production build.
- GitHub Actions runs both on every push to `main` and every pull request.

## Planned (later milestones)

```
Backend ──▶ Object storage (source videos, generated clips)
        ──▶ Background processing (transcription, clip detection, rendering)
```

1. **Upload (Milestone 2)** — media stored in S3-compatible object storage; a record in the database. Large files never go in the database.
2. **Transcription (Milestone 3)** — audio extracted with FFmpeg and transcribed with timestamps.
3. **Clip detection (Milestone 4)** — AI analyses the transcript (later other signals) to propose and score candidate moments.
4. **Clip generation (Milestone 5)** — FFmpeg cuts and reformats selected moments into vertical clips.
5. **Creator intelligence (Milestone 6)** — titles, hooks and metadata.

Long-running work will run outside the request cycle; the mechanism is chosen when first needed. None of this exists yet.

## Localization

The Global experience is the base. Morocco Mode, when built, extends it (additional analysis context and asset libraries) rather than forking it. No localization code exists yet.

## Principles

- Configuration and secrets via environment variables; only `.env.example` files are committed.
- Keep the system simple; add components only when a milestone requires them.
- The API is the security boundary; frontend route guards are a convenience.
