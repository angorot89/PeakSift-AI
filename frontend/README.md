# PeakSift AI — Frontend

Next.js (App Router) + TypeScript + Tailwind CSS. Contains the landing page, login / register, and the creator workspace: Home, projects (Overview, Source, Clips, Assets, Analytics), guided Short creation (Start → Style → Review → Render), the editor, analytics and settings — all backed by the FastAPI API. See [../docs/creator-experience.md](../docs/creator-experience.md) and [../docs/design-system.md](../docs/design-system.md).

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
npm test         # Unit tests (node --test: status sync, caption timing, audio mix)
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
| `/home` | **Home**: first visit — what PeakSift does and *Create your first project*; afterwards *Continue working* (each project's next step from `GET /workspace/home`), *Recent Shorts*, *Recent projects*, and a dismissible *Getting started* checklist until the first Short is ready. `/dashboard` redirects here |
| `/projects` | The signed-in user's projects |
| `/projects/new` | Create a project (name only) |
| `/projects/[id]` | **Overview**: the next best action (upload and *Start transcription* in place), progress *Source → Clips → Edit → Publish → Learn*, best moments, recent Shorts and facts, from `GET /projects/{id}/summary` |
| `/projects/[id]/source` | The source video (upload, details, preview) and the transcript |
| `/projects/[id]/clips` | **Moments** (find, filter All / Top picks / Saved / Dismissed, preview, save, dismiss, **Create Short**) and **Your clips** |
| `/projects/[id]/assets` | **Visuals**: search first, upload (button or drop, one batch summary), grid, details dialog |
| `/projects/[id]/analytics` | How this project's Shorts are doing |
| `/projects/[id]/clips/[clipId]/create` | **Create a Short — Start**: Auto Edit (recommended) or start manually; follows the clip being cut |
| `/projects/[id]/clips/[clipId]/auto-edit` | **Create a Short — Style and Review**: recipe cards (Clean, Punchy, Story, Minimal) with traits, an explicit music choice, the real preparing stages, the review (Framing, Captions, Opening, Visuals, Sound with reasons and Edit links), **Use this edit** / **Continue to editor** / **Try another**, all drafts. `?new=1` starts a new draft |
| `/projects/[id]/clips/[clipId]` | **Edit Short**: the preview (play, seek, mute, full screen) beside five tool groups (Style, Captions, Opening, Visuals, Sound) and the render action; versions below. `?edit=` opens a version, `?plan=` a draft, `?tool=` a tool group |
| `/analytics` | **How are my Shorts doing?**: freshness, totals of reported figures ("—" when none), *What seems to be working* (your usual Short, patterns with evidence), your Shorts; access states and the simulated-data label |
| `/analytics/[id]` | One Short: stat tiles, early windows, small daily charts and table, how it was made |
| `/settings` | **YouTube**: connect (upload access only), disconnect (confirmed), analytics access (read-only) and deleting collected metrics |

`/home`, `/projects*`, `/analytics*` and `/settings` require a signed-in user; visitors are redirected to `/login`. That redirect is a convenience — the API enforces authorization on every request. Signed-in visitors to `/login` or `/register` are sent to `/home`.

## How authentication works in the browser

- The API sets an **HttpOnly** cookie on login/register; the frontend never sees or stores the token (nothing in `localStorage`/`sessionStorage`), and every API call uses `credentials: "include"`.
- On page load `AuthProvider` calls `GET /auth/session` (the user or `null`, never a 401) to find out who is signed in; the backend is the source of truth. The header shows **Log in / Get Started** or the user's email with **Log out**.
- Logout calls `POST /auth/logout`, which clears the cookie.
- The video preview is a plain `<video src="…/videos/{id}/content">`; the browser attaches the cookie because the frontend and API are same-site (`localhost` in development), and the API checks ownership on every byte-range request. Candidate previews ("Preview source") reuse the same stream with a media fragment (`#t=start,end`) and stop at the end of the range. Rendered clips play from `<video src="…/clips/{id}/content">` with the same cookie mechanism, and **Download MP4** is a plain link to `…/clips/{id}/download` (an attachment), so nothing is buffered in JavaScript. Edited shorts work the same way through `…/edits/{id}/content` and `…/edits/{id}/download`.

## Security headers

`next.config.ts` sends, on every page, a Content-Security-Policy built by `lib/security-headers.ts` from `NEXT_PUBLIC_API_URL`: scripts, styles and fonts only from the app itself (Next's inline hydration scripts and React inline styles need `'unsafe-inline'`; `eval` is allowed only by the development server), data and media (`<video>`/`<audio>`) only from the app and the API origin, no plugins, no framing, forms only to the app, `upgrade-insecure-requests` when everything is HTTPS. Also `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, a restrictive `Permissions-Policy`, `Cross-Origin-Opener-Policy: same-origin`; the `X-Powered-By` header is off.

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
    home/, dashboard/ (redirect), projects/, projects/new/, analytics/, settings/,
    projects/[id]/ (layout = ProjectFrame; overview, source/, clips/, assets/, analytics/,
      clips/[clipId]/ = editor, clips/[clipId]/create/, clips/[clipId]/auto-edit/)
  globals.css      # Tailwind import, theme tokens, base styles
  icon.svg         # Favicon
components/
  app/             # App shell (sidebar, mobile sheet), route guard, home view, projects views,
                   # project/ (ProjectFrame + tabs, overview, sections), create/ (Start step, step
                   # indicator), auto-edit view (Style + Review), states, source video,
                   # transcription panel + viewer, clip detection panel + moments review,
                   # clip actions (Create Short),
                   # generated clips panel, short-editor view; editor/ = stage (+ reframed preview),
                   # controls, caption controls + caption layer (live dynamic captions),
                   # audio panel + audio timeline (music, effects, waveforms),
                   # smart-reframe panel + focal-point picker, visuals panel + visuals layer
                   # (live preview) + asset chooser, versions; visual-library (project page: Search your visuals, states, retry); use-visual-search (debounced search hook)
  auth/            # AuthProvider/useAuth, login & register forms, header auth state
  landing/         # Landing page sections
  ui/              # Design system: Button/ButtonLink (one shape; primary/secondary/ghost/danger,
                   # sm/md/lg), Card, Panel, SectionHeader, StatusPill, InlineAlert, Skeleton,
                   # ProgressBar/Spinner/WorkingState, MediaFrame, Field, FormError, Dialog, Menu,
                   # SegmentedControl, ToolTabs, Tooltip, IconButton, Toast
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
  audio.ts         # Audio assets: list, waveform, limits, XHR upload with progress, content URLs
  audio-mix.ts     # The edit's audio section: normalization, timing rules shared with the renderer (unit-tested)
  use-audio-preview.ts # Browser audio preview with the video as master clock; asset "Listen" player
  captions.ts      # Dynamic captions: caption styles, word timing start/status/retry, caption preview
  caption-timing.ts # Pure cue / active-word lookup for the preview (unit-tested)
  status-sync.ts   # Status ordering and polling that never moves backwards (unit-tested)
  reframe.ts       # Smart reframing: analysis start/status/path/retry, plain-language copy, crop geometry
                   # and the renderer's path interpolation (used by the live preview)
  visuals.ts       # Visual assets: list, details, limits, XHR upload with progress, content/thumbnail URLs, visual search and retry
  visual-search.ts # Visual search rules: states, strength tiers and reasons, scene labels and offsets (unit-tested)
  visual-rules.ts  # The edit's visuals section: rules shared with the renderer (unit-tested)
  visual-elements.ts # Inset geometry, asset time and fade opacity for the live preview (unit-tested)
  broll.ts         # B-roll suggestions: start/status/retry, decisions, method labels
  auto-edit.ts     # Auto Edit API calls; auto-edit-rules.ts the pure display rules (unit-tested)
  edit-draft.ts    # Editor settings from a stored configuration (version or plan), unit-tested
  project-clip.ts  # Loads a project and one of its clips (editor and Auto Edit)
  navigation.ts    # Routes, global and project navigation, which item is current (unit-tested)
  workspace.ts     # Home and project summaries (the next best action is decided by the server);
                   # workspace-rules.ts stages, moment labels and the getting-started checklist (unit-tested)
  copilot.ts       # Ask PeakSift API calls; copilot-rules.ts the page scope, conversation keys,
                   # suggested questions and waiting text (unit-tested)
  brand.ts         # Brand Studio API calls and types; brand-rules.ts colours, contrast and logo
                   # placement for previews (unit-tested)
  template-rules.ts # Template settings: starters, summaries, settings from an editor draft (unit-tested)
  morocco.ts       # Morocco Mode preview: the flag, capabilities (all unavailable until real data), Kit tabs (unit-tested)
  command-menu.ts  # The command menu's commands, filtering, question detection and shortcut (unit-tested)
  status.ts        # Waiting / Processing / Ready / Needs attention status language (unit-tested)
  moments.ts       # Moment filters, their queries, counts and empty states (unit-tested)
  editor-tools.ts  # The editor's tool groups, ?tool= links and their marks (unit-tested)
  upload-batch.ts  # One summary for a batch of uploads (unit-tested)
  menu-keys.ts     # Keyboard movement for menus and tab lists (unit-tested)
  use-stored-flag.ts # Small per-browser preferences (sidebar, dismissed tips)
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
