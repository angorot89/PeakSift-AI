# Creator experience (V1.5)

V1.5 turns PeakSift's features into one coherent creator workspace. No pipeline, model or
render changed: every screen was reorganised around three questions — **Where am I? What is
happening? What should I do next?** — and the words on it describe the creator's work, never
the system's (no "worker", "provider", "candidate", "pipeline", "fingerprint" or "embedding").

## Information architecture

| Route | What it is |
| --- | --- |
| `/home` | **Home**: first visit — what PeakSift does and *Create your first project*; afterwards — *Continue working* (one card per project with its next step), *Recent Shorts*, *Recent projects*, and a dismissible *Getting started* checklist until the first Short is ready. `/dashboard` redirects here. |
| `/projects`, `/projects/new` | All projects; a new project. |
| `/projects/[id]` | **Overview**: the next best action (upload and *Start transcription* happen in place), project progress *Source → Clips → Edit → Publish → Learn*, best moments, recent Shorts, facts. |
| `/projects/[id]/source` | The source video, its details and the transcript. |
| `/projects/[id]/clips` | **Moments** (find, filter, preview, save, dismiss, Create Short) and **Your clips**. |
| `/projects/[id]/assets` | **Visuals**: search, upload, browse, details. |
| `/projects/[id]/analytics` | How this project's Shorts are doing. |
| `/projects/[id]/clips/[clipId]/create` | **Create a Short — Start**: Auto Edit (recommended) or start manually; shows the clip being cut when needed. |
| `/projects/[id]/clips/[clipId]/auto-edit` | **Create a Short — Style and Review**: recipe cards, preparing, the reviewed draft. `?new=1` starts a new draft. |
| `/projects/[id]/clips/[clipId]` | **Edit Short**: the editor. `?edit=` opens a version, `?plan=` a draft, `?tool=` a tool group. |
| `/analytics`, `/analytics/[id]` | How are my Shorts doing?; one Short. |
| `/settings` | YouTube publishing and analytics access. |

The app shell (`components/app/app-shell.tsx`) has a collapsible sidebar on large screens and a
top bar with a navigation sheet on phones; `lib/navigation.ts` (unit-tested) owns routes and
which item is current. Project pages share `ProjectFrame` (name, actions menu, tabs).

## Next best action

`GET /workspace/home` and `GET /projects/{id}/summary` (`app/services/workspace_summary.py`)
summarise existing rows — source, transcript, moment search, clips, Shorts, drafts, uploads and
analytics — owner-scoped and without internals. The pure rules in `lib/workspace-rules.ts`
(`nextAction`, `projectStage`, `continueItems`, `gettingStarted`, `momentLabel`) turn them into
one action per project, in the order a creator needs: problems first, then waiting, then the
next creative step. Nothing is predicted and nothing is invented: a step is shown only when the
data for it exists.

## Making a Short

`Start → Style → Review → Render` (`components/app/create/`, `auto-edit-view.tsx`):

- **Start** offers Auto Edit (recommended) or the editor, and follows the clip being cut with
  its real progress. A moment's **Create Short** cuts the clip and lands here.
- **Style**: recipe cards with a caption miniature, the feel and three traits
  (`RECIPE_TRAITS`); the music choice stays explicit.
- **Preparing** shows only the plan's real stages; there are no percentages.
- **Review**: Framing · Captions · Opening · Visuals · Sound, each with the choice, its reason
  and an **Edit** link into that editor tool; **Use this edit**, **Continue to editor**,
  **Try another**.

## Editor

The preview is dominant and has its own controls (play, seek, time, mute — music and effects
included — and full screen of the whole 9:16 frame). Settings are five tool groups in an
accessible tab list (`ToolTabs`, `lib/editor-tools.ts`); a dot marks a group that adds something
or blocks rendering. The render action is always reachable (panel footer; a compact bar on
phones), and the copy is exact about saving: *nothing is saved until you render; each render is
a new version and earlier versions are kept*.

## Moments, visuals and analytics

- **Moments**: a still, a label grounded in the run's rank and editorial score (*Top pick* =
  rank 1, *Strong moment* = score ≥ 75, *Worth reviewing*), times, hook and why; filters **All
  · Top picks · Saved · Dismissed** with counts from the additive `view` / `counts` of the
  candidate listing; dismissed moments collapse to one line with Restore.
- **Visuals**: search first (its hint follows what search can really do), results in **Best
  matches** then **More results**, uploads as one batch with one progress and each failure
  explained.
- **Analytics**: *How are my Shorts doing?* with plain freshness ("updated through Oct 20"),
  totals of only what YouTube reported ("—" otherwise), *What seems to be working*, then the
  Shorts; simulated data is labelled once for the page.

## Feedback and safety

- Status language everywhere: *Waiting*, a specific step (*Transcribing*, *Finding moments*,
  *Rendering*…), *Ready*, *Needs attention* (`lib/status.ts`).
- Toasts confirm small completed actions only (moment saved or dismissed, visual deleted,
  insight hidden, project deleted); problems stay inline where they happened.
- Confirmation only for destructive actions: deleting a project (type its name), a visual,
  collected metrics, and disconnecting YouTube.
- Loading shows skeletons shaped like the content; short checks keep a spinner.

## Accessibility and responsive behaviour

Checked in a real browser on a production build at 1440, 1280, 1024, 768, 430, 390 and 375 px
for every key screen (16 screens × 7 widths): no horizontal overflow, no axe-core WCAG 2.1 A/AA
violation, touch targets of at least 44 px on touch screens (24 px minimum with a pointer), and
no console errors — including signed-out pages, whose session check uses `GET /auth/session`
(always 200) instead of a 401. Dialogs move focus in, close with Escape and return focus;
menus and tabs follow the WAI-ARIA keyboard patterns; `prefers-reduced-motion` turns animation
off. The product keeps one polished dark theme.

## Acceptance

Run in a real browser against a production build on an isolated stack with the real pipeline
(upload, faster-whisper transcription, local-AI moments, FFmpeg clip and render, Auto Edit with
the local planner) and the fake publishing and metrics providers (labelled simulated):

- **First-time journey**: create an account → Home (welcome) → *Create your first project* →
  upload in place → *Start transcription* → *Find moments* → the top moment → **Create Short**
  → Start → Auto Edit → **Punchy** → review (Framing, Captions, Opening, Visuals, Sound) →
  *Continue to editor* → change the caption style → **Render Short** → play → download → connect
  a (simulated) channel → **Publish** → *Simulated upload*. No console errors, no failed
  requests.
- **Returning journey**: Home's *Continue working* shows each project's real next step (*Add
  your long video*, *Find the best moments*, *Your Short is on YouTube → View performance*) and
  each action lands on the right page.
- **Visual QA**: every key surface at 1440, 1024, 768 and 390 px.

Defects found this way were fixed in the same release: "nothing yet" checks logged as failed
requests, simulated video ids repeating after a worker restart, Home pointing back at a used
draft, and the editor offering to view the version already on screen.

### Heuristic review (Nielsen)

| Heuristic | How V1.5 meets it |
| --- | --- |
| Visibility of system status | One status language; real progress only (no invented percentages); pages that wait say they update themselves |
| Match with the real world | Creator words — moments, Shorts, drafts, versions, opening — never system terms |
| User control and freedom | Dismiss/Restore, Try another, Reset, Escape closes dialogs, earlier versions and drafts are kept |
| Consistency and standards | One button shape and hierarchy, one card, one dialog, WAI-ARIA tabs and menus |
| Error prevention | Blocked renders name the tool to fix; destructive actions are confirmed |
| Recognition rather than recall | Next step on Home and Overview; step indicator; dots on tool groups that need attention |
| Flexibility and efficiency | Auto Edit for speed, the editor for control, `?tool=` deep links from the review, keyboard everywhere |
| Aesthetic and minimalist design | One primary action per view; details behind disclosures; summaries only with data |
| Recover from errors | Inline errors in plain words with Try again where it is safe; nothing internal is shown |
| Help and documentation | Hints at the point of need and the [user guide](user-guide.md) |

## API additions (all additive)

`GET /workspace/home` · `GET /projects/{id}/summary` · `view=active|top` and `counts` on
`GET …/clip-detection/{run_id}/candidates` · `GET /auth/session`. Existing endpoints, security
boundaries, rendering, publishing and analytics behaviour are unchanged.

## Visual overhaul (after V1.7)

A visual-first pass toward the reference pack (warm, dark, preview-first), on the same data and
behaviour (PRs #239–#246):

- **Home** — *Welcome back*, **Continue working** cards from the next-best-action engine (tone,
  one action, real frames of the moments or Short in question), **Recent projects** (source frame,
  five-step progress, next step) and vertical **Recent Shorts** (Ready / Published).
- **Project** — the creator workflow **Upload → Transcribe → Find moments → Create Short → Edit &
  publish** (done / next / in progress / needs attention, from the summary; one compact row on
  phones), one **next best action**, the source, **moment cards** with a frame at the moment, the
  generated Shorts and a transcript peek. The *Clips* tab is now **Moments** (same route).
- **Editor** — a header with the clip, **Template / Brand chips**, Auto Edit and (large screens)
  the one **Render Short**; a sixth tool, **Brand** (this Short's template and brand, its brand
  elements, Save as / Update template — explicit only).
- **Brand Studio** — brand library cards (swatch or logo, default, template count), an *Edit brand*
  card with unsaved state and Reset, the live preview in its own column.
- **Ask PeakSift** — a context card ("Answers from your own data"), suggested-question tiles,
  numbered idea cards with fact chips, the warm composer and "PeakSift can get things wrong".
- **Analytics** — "How are my Shorts doing?", freshness, figure tiles ("—" when unreported) and
  each Short with its real thumbnail. No deltas or predictions.
- **Morocco Mode (preview)** — see below.

Browser audit: **330/330** (19 surfaces × 1440/1280/1024/768/430/390/375: axe WCAG 2.1 AA, overflow,
44 px touch targets on phones, console errors). Functional regression on the redesigned build: the
fresh-creator journey (sign-up → brand → template → upload → Create a Short → Auto Edit → render →
download), the brand release gate (13/13) and the Copilot acceptance with the local model (17/17).

### Morocco Mode (preview)

Morocco Mode **extends** Global — it never replaces it. Its UI architecture exists behind
`NEXT_PUBLIC_MOROCCO_MODE_PREVIEW` (off by default; the routes return 404 without it):

- `/morocco` — *Create Shorts for Morocco*, the **Global / Morocco Mode** switch with **Global library
  included**, and what Morocco Mode adds;
- `/morocco/kit` — the **Creator Kit**: a local library (Images, B-roll, Sounds, Hooks, Templates),
  suggestions for a clip, and **local + global match** (Moroccan matches first, then global).

No Moroccan data source exists yet — no Darija hooks, sound library, audience trends or local
assets — so every capability reads **Not available yet** and links to what works in Global today.
Nothing is generated, curated as if real, or invented; no place or topic filters ship without a
library behind them. The capabilities live in `lib/morocco.ts` (unit-tested); a real source flips
its capability to available. Darija transcription accuracy has not been measured.
