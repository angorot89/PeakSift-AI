# PeakSift AI

**Find the moments worth clipping.**

PeakSift AI is a short-form clipping and creation platform. Creators bring long-form content — videos, streams, podcasts, interviews, recordings — and PeakSift helps them find the strongest moments and turn them into short-form clips for TikTok, YouTube Shorts, and Instagram Reels.

## Current status

**Milestone 1 — Foundation V0.1** (in progress)

The repository currently contains project structure and documentation only. There is no application code yet; none of the features described below exist today.

## Planned workflow

1. **Upload** a long-form video, stream, podcast, or recording.
2. **Transcribe** the audio.
3. **Detect** candidate moments worth clipping using AI.
4. **Rank** candidate clips.
5. **Generate** short-form clips sized for vertical platforms.
6. **Edit & export** — later: captions, hooks, sound effects, creator assets, and export tools.

See [docs/milestones.md](docs/milestones.md) for the delivery roadmap.

## Planned tech stack

| Area      | Planned choice                          |
| --------- | --------------------------------------- |
| Frontend  | Next.js (React, TypeScript)             |
| Backend   | FastAPI (Python)                        |
| Database  | PostgreSQL                              |
| Storage   | S3-compatible object storage for media  |
| Media     | FFmpeg                                  |
| AI        | Speech-to-text + LLM-based clip analysis |

These choices are planned and may be refined as milestones are delivered. See [docs/architecture.md](docs/architecture.md).

## Localization: Global + Morocco Mode (future)

PeakSift will ship a **Global** experience available to everyone.

**Morocco Mode** is a planned future localization layer that *extends* the Global experience — users keep every Global tool and library, plus Darija-aware analysis, Moroccan cultural context, local sound effects and creator assets, and Morocco-specific clip suggestions. It is not a separate app, and it is not implemented yet.

## Repository structure

```
PeakSift-AI/
├── frontend/   # Next.js app (not yet initialized)
├── backend/    # FastAPI service (not yet initialized)
└── docs/       # Architecture and milestone docs
```
