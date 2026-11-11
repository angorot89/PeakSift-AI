# Shorts library & publishing center

PeakSift is strong at *making* Shorts (moments → Auto Edit → brand/template → timeline editor →
render). The Shorts library makes what happens **after** creation just as clear: one place to see
every Short, open it, preview, download, edit again, publish to YouTube and see how it is doing.
It organizes existing features; there is no new AI, no scheduling and no other platform.

## What a Short is

- A **Short** is one rendered **version** of a clip (`ClipEdit`). Publishing, analytics and the
  template/brand provenance already belong to the version, and Home's *Recent Shorts* already
  showed versions. A moment with several versions shows each one (labelled "v2", with the other
  versions listed on its page).
- A **draft** is a clip the creator cut from a moment but has not made a version of yet (its id
  is the clip's). Once it has a version, its link opens that version.
- A failed version of a clip that has a newer version is **history**, not a problem to fix: it
  is left out of the library (and its *Needs attention* count) but listed among the newer
  version's versions, and its own link still opens.

## One status system

`backend/app/services/shorts_library.py` is the **only** place a creator-level status is derived
from domain state (the version, its publish jobs, its published content); the frontend's
`lib/shorts-rules.ts` is the only place it is put into words. Home, the project overview, the
library and the Short's page all use them.

| Status | When | Words | Filter |
| --- | --- | --- | --- |
| `draft` | a cut moment, no version yet | Draft | Drafts |
| `rendering` | the version (or the cut) is being made | Rendering | All |
| `ready` | rendered, not on YouTube | Ready | Ready |
| `publishing` | an upload runs, or YouTube's processing is still checked | Publishing | All |
| `on_youtube` | uploaded; YouTube has not confirmed it (upload-only access cannot see processing) — **never** called published | On YouTube | Published |
| `published` | YouTube confirmed it | Published | Published |
| `failed` | the render (or the cut) failed | Failed | Needs attention |
| `needs_attention` | a render or an upload stopped reporting, or an upload failed (`reason` says which) | Needs attention | Needs attention |

A video YouTube already has outranks a later failed attempt. Publishing stages are the job's real
ones — Preparing upload… · Uploading… (with YouTube's confirmed bytes) · Processing on YouTube… ·
On YouTube · Published · Stalled · Failed — never a guessed percentage. Status is words plus a
shape, never colour alone.

## API (additive)

| Endpoint | |
| --- | --- |
| `GET /shorts` | the creator's Shorts and drafts, most recently updated first (≤ 500; `truncated` says when more exist): project, source, title, duration, what can be previewed (`short` / `clip` / none), version number, the template version and brand **recorded with the version** (`origin`), publishing state and dates, a YouTube link only for real uploads, the latest reported figures (`null` = not reported) |
| `GET /shorts/{id}` | one Short or draft, plus the moment (time, rank, kind), the clip's versions, render facts and the creator's analytics access |
| `GET /workspace/home`, `GET /projects/{id}/summary` | their Shorts now carry `short_status` (the library's status); `published` keeps its meaning |

Owner-scoped (another creator's Short is `404`), read-only, and a fixed number of queries
whatever the library's size (window functions and batched jobs, contents and counters; a test
asserts 1 and 8 Shorts cost the same statements). Responses never contain storage keys, task
ids, fingerprints, configuration snapshots or provider payloads.

## The library (`/shorts`)

**Shorts** sits in the sidebar between Projects and Analytics (and in the ⌘K menu). The page:
title, "Everything you've created, ready to edit, publish or review.", **Create a Short** (the
moments of the most recently active project). Filters with counts (they wrap on phones), a search
over titles, projects and source names (case- and accent-insensitive, 200 ms after typing), four
sorts (Recently updated · Newest · Oldest · Recently published); the view lives in the address.

Cards: a real 9:16 frame (the render, or the moment's cut until then), the status, length, "v2",
title, project and one context line ("YouTube · Published Oct 18", "(simulated)" for test
uploads). The card opens the Short; its menu, beside the title and always visible, lists only what
is valid now (Edit / Continue editing, Download, Publish, View analytics, Open project). Empty:
"No Shorts yet" with **Open projects** / **Create project**; no match: **Show all Shorts**; loading:
skeletons with the same proportions.

## A Short's page (`/shorts/{id}`)

The output workspace (the project stays the source workspace). A large 9:16 player (or the
moment's cut, captioned, until it is rendered); the status with one sentence and **one** primary
action — Draft → Continue editing (the waiting Auto Edit, or the guided creation), Ready →
Publish, On YouTube / Published → View performance, Failed / Needs attention → Fix issue — plus
Edit, Download and Open project. **Details**: created from (project, source), the moment (time,
rank, kind), the template name and version and the brand **as recorded with the Short** (a later
template change never rewrites it), how it was made, dates, file size. **Versions of this moment.**

### Publishing panel

The YouTube connection (Connected · channel, Needs reconnecting, Not connected, or not enabled),
the real publishing state, the reviewed title and visibility, and the one action that fits:
**Connect YouTube** (Google's consent, then back to this Short), **Publish** (review the metadata
and confirm in the existing dialog), **Retry** / **Resume** (the same upload — never a second
video), **Publish again**, **Open on YouTube** (real uploads only). Failures are a plain title with
the safe server message behind *Details*. Nothing publishes without the creator's click; the
Copilot cannot publish. The return address after Google is kept in the tab's session storage and
must be a Short or an editor of this app (`safeReturnPath`).

### Performance

Only for a Short on YouTube, from the existing V1.4 analytics: views (live counter), watch time
and subscribers gained (summed over processed days), average % viewed, likes, comments — "—"
whenever YouTube did not report a figure. Always one freshness line ("Updated through Nov 9",
"Waiting for YouTube data", "Analytics not connected. Showing what was collected through …").
Engaged views over the first week (one chart), "Too early to compare" until the creator's own
comparisons are reliable, and an observed pattern only when the insights engine's evidence
includes this Short. Simulated figures are labelled.

## Integration

Home's Recent Shorts, the project's Generated Shorts, Analytics rows and a video's analytics page,
and the editor after a render (**View Short**) open the Short's page. The next-action engine's
"Your Short is ready", "Uploading to YouTube" and "A YouTube upload needs attention", and the
Copilot's **Open the Short**, now open it too.

## Phones and accessibility

Two-column cards at 375–430 px (the menu sits beside the title, not over the status); the
detail page puts the preview first (a still stays small so the next step stays in view), then
status and action, publishing, details, performance. 44 px targets on touch screens; menus work
without hover (arrow keys, Escape returns focus); cards and the player have accessible names;
skeletons are one labelled status; card lift and transitions are off under reduced motion.

## Acceptance (local, review stack)

**Release gate** — `backend/scripts/shorts_acceptance.py` (read-only, against a running PeakSift,
credentials from the environment): every Short and draft in the library opens, its page, Home and
the project agree on its status, "published" only with YouTube's confirmation and "on YouTube"
never called published, a YouTube link only for real uploads, its version listed with its number,
a rendered Short streams as MP4 and an unrendered one has nothing to download, no internals, no
figures before it is on YouTube.

```bash
SHORTS_ACCEPTANCE_EMAIL=… SHORTS_ACCEPTANCE_PASSWORD=… \
  python scripts/shorts_acceptance.py --api http://localhost:8000
```

Local results:

- **Release gate** on the seeded creator: 50/50.

- **Fresh creator, real browser**: register → project → upload → transcribe (tiny Whisper) → find
  moments (local model) → Create Short → Auto Edit → editor → timeline seek → render → View Short
  → download (3.9 MB) → Connect YouTube offered → publish (fake provider, simulated connection)
  → Published (simulated) → "Waiting for YouTube data" → the library lists it on YouTube; no
  console errors.
- **Returning creator** (seeded Draft, Ready, Published with simulated analytics, Failed render,
  Failed upload): filters and counts, search, no match, each state's primary action, no Download
  or Publish on a failed render, menus with valid actions only — 19/19.
- **Publishing**: Ready → Publish → review → confirm → Published (simulated); a failed upload →
  Fix issue → Retry → finished; connect-and-return, a failure staying on Settings, a foreign
  return address ignored.
- **Browser audit**: 14 surfaces × 1440/1280/1024/768/430/390/375 (98/98) plus the publish
  dialog, the keyboard card menu and the empty library (21/21) and the analytics-not-granted and
  reconnect states: axe WCAG 2.1 AA, no horizontal overflow, no console errors, 44 px targets.
- **State matrix** (`lib/shorts.test.ts`, `tests/test_shorts_library.py`): unrendered, rendering,
  render failed, rendered, not published, publishing, publish failed, published, analytics
  unavailable, pending and reported — no contradictory status or action.

The review stack's moments were partly **controlled** (provider `controlled`, real transcript
lines): the local `llama3.2:3b` proposes only sub-15 s spans for the generated narration, which
validation rightly refuses. Seeded failures (a failed render, a failed upload) are written to the
review database directly. Real YouTube was not used for this pass (the fake provider; the
publishing architecture passed real YouTube acceptance in V1.0).

## Limitations

- One card per version: a moment rendered three times shows three Shorts (labelled v1–v3).
- The library loads whole (≤ 500, filtered in the browser); there is no project or template
  filter yet (search finds a project by name).
- Ask PeakSift does not know which Short a `/shorts/{id}` page shows (it answers as on Home).
- No scheduling, multi-platform publishing, thumbnails, editing published videos or deleting
  Shorts from the library.
