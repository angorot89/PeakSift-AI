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
| `/shorts` | **Shorts**: every Short and draft the creator made, with one status each, filters, search and sort ([shorts-library.md](shorts-library.md)). |
| `/shorts/[id]` | **One Short**: preview, status and its one next action, details as made, versions, publishing in place and performance. |
| `/analytics`, `/analytics/[id]` | How are my Shorts doing?; one Short's figures (with **Open Short**). |
| `/settings` | YouTube publishing and analytics access. |

The app shell (`components/app/app-shell.tsx`) has a collapsible sidebar on large screens and a
top bar with a navigation sheet on phones; `lib/navigation.ts` (unit-tested) owns routes and
which item is current. Project pages share `ProjectFrame` (name, actions menu, tabs).

## Quick start

Home's one step (`components/app/quick-start.tsx`, `POST /quick-start`): the creator drops a long
video and presses **Find my moments**. PeakSift names the project from the file (editable before
the upload; `services/quick_start.py` and `lib/quick-start.ts` apply the same rule), stores and
checks the video, starts the transcription and marks it `auto_find_moments`. When the transcript
completes, the worker starts one moment-detection run with the first configured provider that is
reachable at that moment (`services/clip_detection/autostart.py`) — never a second run, and never
on a provider that is switched off. The creator lands on the ordinary project page, which says
that moments follow by themselves.

It degrades to the normal steps, never to a dead end: a refused upload leaves no project, an
unreadable file leaves the project with its "upload a different file" step, and a busy queue or
no reachable provider leaves the usual **Start transcription** / **Find moments** step.
`/projects/new` stays for creators who want an empty project first.

## Find Clips

On the Moments tab, above the detected moments (`components/app/find-clips.tsx`): the creator
describes a moment in plain language — "the part where I explain pricing" — and gets the places
where it was said. Every result is real lines of their own transcript with real timestamps; it
says which of their words were heard, and which related words if the local model offered any.

- `GET /projects/{id}/videos/{id}/find-clips?q=` — `services/find_clips.py`, pure and
  deterministic: the request is reduced to its spoken words (folded for case, accents and Arabic
  letter forms, lightly stemmed, without function words and words of asking), transcript lines
  are scored BM25-style, nearby hits are pulled into one span and context is added until the
  span is a valid clip length. Results never overlap and are ranked by how much of the request
  they cover.
- Related words (`services/find_clips_model.py`) are optional: the local model suggests single
  words likely to be *said* in such a moment. They only widen the search, count for half, and
  are reported apart. No model, a slow model or a strange answer mean none.
- `POST …/find-clips/keep` turns a result into a saved moment (`clip_candidates.origin =
  "search"`, with the request in `query`), so Create Short, Auto Edit and the editor work on it
  unchanged. It joins the newest completed analysis of the current transcript, or a completed
  run of its own when there is none. It carries no editorial scores (0, not shown), is labelled
  "You asked for this" and is never a top pick. Keeping the same span twice is one moment.

A search match is not a rating: nothing here predicts how a clip will perform.

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

## Workspace redesign (November 2026)

At the creator's request ("the whole design of the system is bad") the workspace was rebuilt
around the layout pattern of StreamLadder's app — structure only, nothing copied: pages on a
rounded canvas beside a grouped sidebar with a **Create new** menu, Home opening on one creation
box with tool tiles, status tabs with coloured dots and counts, heavy display titles, and one
brand colour, PeakSift blue. The login and sign-up pages became a split screen. The public website follows the section order
of StreamLadder's site in PeakSift's own words and colours: a light page with a floating
navigation bar, a blue hero with the platforms, headline, "Start clipping" and a dark product
frame (labelled as an illustration), four alternating feature rows (AI moments, Editing,
Publishing, Analytics) with built-in illustrations, the toolkit grid, a "Built to explain itself"
bento of plain statements (no invented user numbers or testimonials), a FAQ and a closing call to
action. Details: an announcement strip; a floating bar that turns solid on scroll with **Product**
and **Made for** mega menus (hover, click or keyboard, Escape closes; one panel on phones); an
animated demo carousel in the hero (AI moments, Smart reframe, Captions, Auto Edit & publish —
drawn scenes that advance by themselves, with the next one peeking, a pause button and synced
tabs); an endless row of drawn example Shorts per kind of video ("Made for"); feature
illustrations that play when scrolled into view; count-up product facts (3 platforms, 12 tools,
1080×1920, −14 LUFS); pressable buttons; and a large wordmark in the footer. Everything is drawn
with CSS (no other creators' footage), labelled as an illustration, and still under reduced
motion.

The website's other pages follow StreamLadder's page set where PeakSift has a real equivalent,
from one shared template and one content file (`components/landing/content.ts`): **All tools**
(`/features`) and a page per tool (`/features/[slug]`, 12: hero and drawn demo, what it does, how
it works, why, more tools, works well with, example Shorts, questions); **Made for** pages
(`/made-for/[slug]`: podcasters, streamers, educators, interviews); **Pricing** (free while in
development — one honest card, no invented tiers); **About**; **Guides** (`/guides`, six
step-by-step guides with a table of contents); and **Your data** (`/privacy`: how PeakSift is
built to handle data — explicitly not a legal policy). Deliberately not made: montage, emote and
schedule makers, a clip downloader, a mobile app, workspaces, careers, competitor comparisons and
legal terms or refund pages — PeakSift has no such product, and legal text needs a lawyer. Tokens and rules:
[design-system.md](design-system.md). Behaviour, copy rules and data are unchanged; the look
described in the next section is superseded.

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
- **Morocco Mode** — see below.

Browser audit: **330/330** (19 surfaces × 1440/1280/1024/768/430/390/375: axe WCAG 2.1 AA, overflow,
44 px touch targets on phones, console errors). Functional regression on the redesigned build: the
fresh-creator journey (sign-up → brand → template → upload → Create a Short → Auto Edit → render →
download), the brand release gate (13/13) and the Copilot acceptance with the local model (17/17).

### Morocco Mode

Morocco Mode **extends** Global — it never replaces it. Since V1.8 it is live (no flag):

- the **Global / Morocco Mode** switch on Home (also for a fresh creator) and `/morocco` shows
  "New projects: …" and saves the creator's default for new projects only; **Global library
  included** is always shown;
- `/morocco` — what Morocco Mode adds (Darija hooks, content styles, local visuals, local sounds, Ask
  PeakSift), the curated formats ("Curated by PeakSift … — not trends"), the creator's Moroccan
  visuals and sounds with honest empty states, and Browse the Global library;
- `/morocco/kit` — the **Creator Kit**: Visuals · Sounds · Hooks · Templates, search and filters
  only from the creator's own metadata;
- projects: "Made for" on creation, a Market and language card on the overview, Source and market
  labels on visuals and sounds, "Local matches" / "Global alternatives" in search, Hook ideas in
  the editor's Opening tool, and "Made for: Morocco Mode" on Shorts made there.

Nothing is called trending; there are no flags or national colours (the mode is said in words).
Right-to-left creator text uses `dir="auto"`. Browser audit (V1.8): Morocco creator 133/133 and
Global creator 42/42 at all seven widths. See [morocco-mode.md](morocco-mode.md).
