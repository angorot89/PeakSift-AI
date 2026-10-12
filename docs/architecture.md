# Architecture (planned)

This describes the **planned** high-level architecture. Nothing here is implemented yet. Details will be decided milestone by milestone.

## Components

```
┌────────────┐      HTTP/JSON      ┌────────────┐
│  Frontend  │ ──────────────────▶ │  Backend   │
│  Next.js   │ ◀────────────────── │  FastAPI   │
└────────────┘                     └─────┬──────┘
                                         │
                     ┌───────────────────┼────────────────────┐
                     ▼                   ▼                    ▼
               ┌──────────┐      ┌──────────────┐     ┌──────────────┐
               │ Postgres │      │ Object store │     │ Background   │
               │          │      │ (media)      │     │ processing   │
               └──────────┘      └──────────────┘     └──────────────┘
```

- **Frontend (`frontend/`)** — Next.js app. Upload UI, viewing candidate clips, and later the clip editor.
- **Backend (`backend/`)** — FastAPI service. REST API for uploads, jobs, transcripts, and clips.
- **Database** — PostgreSQL for metadata (videos, jobs, transcripts, clip candidates).
- **Object storage** — S3-compatible storage for source videos and generated clips. Large files do not go in the database.
- **Background processing** — long-running work (transcription, clip detection, rendering) runs outside the request cycle. The exact mechanism will be chosen when it is first needed.

## Planned processing pipeline

1. **Upload** — source media stored in object storage; a record is created in the database.
2. **Transcription** — audio extracted (FFmpeg) and transcribed with timestamps.
3. **Clip detection** — AI analyzes the transcript (and later other signals) to propose and score candidate moments.
4. **Clip generation** — FFmpeg cuts and reformats selected moments into vertical short-form clips.

## Localization

The Global experience is the base. Morocco Mode, when built, will extend it (e.g. additional analysis context and asset libraries) rather than fork it. No localization architecture is defined yet.

## Principles

- Configuration and secrets via environment variables.
- Keep the system simple; add components only when a milestone requires them.
