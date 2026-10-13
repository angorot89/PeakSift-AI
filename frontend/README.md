# PeakSift AI — Frontend

Next.js (App Router) + TypeScript + Tailwind CSS. Contains the landing page, login / register, the dashboard and projects, and the project page's source-video upload, metadata, preview, transcription workflow and AI clip detection (provider choice, staged progress, ranked candidate cards with preview and save/dismiss) and clip generation (Generate clip, real render states, rendered clip player, Download MP4) — all backed by the FastAPI API.

## Run locally

Requires Node.js 20.9+. The backend must be running too (see [../backend/README.md](../backend/README.md)).

```bash
cd frontend
npm install
cp .env.example .env.local   # optional; the default API URL is http://localhost:8000
npm run dev                  # http://localhost:3000
```

Open the app at **http://localhost:3000** (not `127.0.0.1`): the auth cookie is set by the API for the `localhost` host, and the backend's CORS allow-list is `FRONTEND_URL` (default `http://localhost:3000`).

Other scripts:

```bash
npm run lint     # ESLint
npm run build    # Production build
npm run start    # Serve the production build
```

## Configuration

| Variable              | Default                 | Purpose                      |
| --------------------- | ----------------------- | ---------------------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the FastAPI API  |

## Pages

| Route       | Description                                                        |
| ----------- | ------------------------------------------------------------------ |
| `/`         | Landing page                                                       |
| `/login`    | Email + password login; generic error on bad credentials           |
| `/register` | Create an account (email, password ≥ 8 chars, confirmation)        |
| `/dashboard` | Project count, placeholders for videos/clips (not built yet), recent projects |
| `/projects` | The signed-in user's projects                                       |
| `/projects/new` | Create a project (name only)                                   |
| `/projects/[id]` | The project workspace. A **workflow stepper** (Upload, Transcribe, Find clips, Generate, Edit — Done / In progress / Next / Needs attention, each linking to its section, nothing locked) above four numbered panels: **1 Source video** (upload drop zone with real progress, then a labelled "Source preview" player beside duration/resolution/size/upload date; codecs behind "Show technical details"; Replace), **2 Transcript** (start, live status with real progress, stalled/failed alerts with retry, a bounded scrollable timestamped transcript, Copy transcript), **3 Clip moments** (provider/model choice from server allow-lists, "Find clip moments", staged progress, run history, and ranked candidate cards: rank, title, time range, one prominent overall score, the hook, "Why it was selected" (clamped), score breakdown and transcript excerpt behind a disclosure, Saved/Dismissed chips, Preview source in a labelled frame, Generate clip with real render states, and a compact "Generated clip" player with **Create vertical short** and **Download MP4**), **4 Generated clips** (frame thumbnails, status, number of shorts, Download, Create short / Open editor) |
| `/projects/[id]/clips/[clipId]` | The **short-form editor** for one ready clip: a 9:16 stage (labelled approximate **Preview** with a real transcript caption, or the **Rendered short**), visual settings (layout cards, Captions switch, caption-style cards with typographic samples, Top/Center/Bottom picker), **Render short** replaced by the real Queued/Rendering/Validating state while it runs, the rendered result with **Download short** / **Create another version** / **Back to clip**, and the versions list named by settings (status, play, download, retry) |

`/dashboard` and `/projects*` require a signed-in user; visitors are redirected to `/login`. That redirect is a convenience — the API enforces authorization on every request. Signed-in visitors to `/login` or `/register` are sent to `/dashboard`.

## How authentication works in the browser

- The API sets an **HttpOnly** cookie on login/register; the frontend never sees or stores the token (nothing in `localStorage`/`sessionStorage`), and every API call uses `credentials: "include"`.
- On page load `AuthProvider` calls `GET /auth/me` to find out who is signed in; the backend is the source of truth. The header shows **Log in / Get Started** or the user's email with **Log out**.
- Logout calls `POST /auth/logout`, which clears the cookie.
- The video preview is a plain `<video src="…/videos/{id}/content">`; the browser attaches the cookie because the frontend and API are same-site (`localhost` in development), and the API checks ownership on every byte-range request. Candidate previews ("Preview source") reuse the same stream with a media fragment (`#t=start,end`) and stop at the end of the range. Rendered clips play from `<video src="…/clips/{id}/content">` with the same cookie mechanism, and **Download MP4** is a plain link to `…/clips/{id}/download` (an attachment), so nothing is buffered in JavaScript. Edited shorts work the same way through `…/edits/{id}/content` and `…/edits/{id}/download`.

## Design system

- **Tokens** (`app/globals.css`): three surface levels (`surface`, `surface-2`, `surface-3`), `border` / `border-strong`, text (`foreground`, `muted`, `subtle`), one accent (`accent`, `accent-soft`) used sparingly, status colours (`success`, `warning`, `danger`), restrained `fade-in` / `shimmer` motion, and tabular numerals for `<time>` and `.tabular`. `prefers-reduced-motion` disables animation and transitions.
- **Components** (`components/ui/`): every section is a `Panel` (one radius, one border, a header row with optional step number, status and actions); state is a `StatusPill` (dot + words, never colour alone); problems are an `InlineAlert` (heading, explanation, recovery action); empty states are an icon + one-line title + one-line next step; loading uses skeletons or a context-specific `WorkingState` with backend progress only; every video sits in a labelled `MediaFrame` (Source preview, Generated clip) or the editor's 9:16 frame.
- **Icons**: `lucide-react` (pinned exact version); no emoji as UI icons.

## Uploads

`lib/videos.ts` uploads with `XMLHttpRequest` (for real progress events) to `POST /projects/{id}/videos`. Accepted: `.mp4`, `.mov`, `.webm`. The size limit is enforced by the API (`MAX_VIDEO_UPLOAD_BYTES`, default 2 GiB → `413`); the UI shows the API's message. After the bytes are sent the UI shows "Reading video metadata…" while the server runs ffprobe, then renders the returned metadata — only fields that exist — or the failure state.

## Structure

```
app/
  layout.tsx       # Root layout: fonts, metadata, global styles, AuthProvider
  page.tsx         # Landing page
  login/, register/
  (app)/           # Signed-in area: layout.tsx = RequireAuth + AppShell
    dashboard/, projects/, projects/new/, projects/[id]/
  globals.css      # Tailwind import, theme tokens, base styles
  icon.svg         # Favicon
components/
  app/             # App shell, route guard, dashboard/projects views, states, source video,
                   # transcription panel + viewer, clip detection panel + candidate review,
                   # clip render controls + rendered clip, project workflow stepper,
                   # generated clips panel, short-editor view; editor/ = stage, controls, versions
  auth/            # AuthProvider/useAuth, login & register forms, header auth state
  landing/         # Landing page sections
  ui/              # Design system: Button/ButtonLink (one shape; primary/secondary/ghost/danger,
                   # sm/md/lg), Panel, StatusPill, InlineAlert, EmptyState, Skeleton,
                   # ProgressBar/Spinner/WorkingState, MediaFrame, Field, FormError, SectionHeading
  logo.tsx, site-header.tsx, site-footer.tsx
lib/
  api.ts           # fetch wrapper (base URL, cookies, error parsing)
  auth.ts          # Typed calls to /auth/* and the User type
  projects.ts      # Typed calls to /projects and the Project type
  videos.ts        # Video type, accepted formats, list + XHR upload with progress
  transcription.ts # Transcription/transcript types, start/status/retry, paginated transcript
  clip-detection.ts # Provider options, detection runs, candidates, decisions; stage labels
  clips.ts         # Generated clips: generate/status/retry/list, content and download URLs
  edits.ts         # Short-form edits: option allow-lists, create/list/status/retry, content and download URLs
  use-api.ts       # Loading/error/reload hook for API data
  format.ts        # Date, bytes, duration and frame-rate formatting
```

## Known dependency advisories

`npm audit` reports 5 high-severity findings. They are all one advisory, counted once per package in the chain:

- **[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)**: a stack-exhaustion DoS in `braces` (all versions up to 3.0.3, the latest release). No patched version exists.
- **Chain:** `eslint-config-next` (direct, dev) → `@next/eslint-plugin-next` → `fast-glob` → `micromatch` → `braces`. The other four findings are inherited from `braces`.
- **Exposure:** none at runtime. The chain is dev-only (lint-time); `npm ls braces --omit=dev` is empty, and none of it ships in the production build. Exploiting it requires attacker-controlled glob patterns, but ESLint only processes patterns from our own config.
- **Why it's not fixed:** `npm audit fix --force` would downgrade `eslint-config-next` from 16 to 14, which breaks compatibility with Next.js 16. Do not run it.
- **Action:** re-run `npm audit` when `braces` publishes a patched release or when upgrading `eslint-config-next`. A non-breaking fix (`npm update` or an `overrides` entry) should then be possible.
