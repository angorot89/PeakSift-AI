# PeakSift design system

One dark theme, the **edit bay** (November 2026): neutral graphite like a video editor, so the
creator's own frames carry the colour, and one signal colour — cue yellow — for what to do next
and for marked moments. No glows, gradients or decorative art in the workspace. Tokens live in `frontend/app/globals.css`;
primitives in `frontend/components/ui/`. Use them instead of one-off values in JSX.

## Tokens

| Group | Tokens |
| --- | --- |
| Surfaces (chrome → raised) | `chrome` (sidebar, phone top bar, darkest) · graphite `background` · `surface` · `surface-2` · `surface-3`; solid borders `border`, `border-strong` |
| Text | `foreground` (primary) · `muted` (secondary, ≥ 7:1 on panels) · `subtle` (metadata, ≥ 4.5:1 on every surface) |
| Signal | `accent` cue yellow (marks, focus, the step that is up next, selected track) · `accent-soft` (signal text on dark, slightly paler) · `accent-fill` / `accent-fill-hover` with dark `accent-ink` text (≥ 14:1) — the primary action. Never decoration |
| Semantic colours | `success` (done, published) · `info` (facts, drafts, links) · `violet` (working, rendering, AI) · `warning` (amber, so it never reads as the signal) · `danger` — only where they mean something |
| Type | Instrument Sans (`--font-ui`); display, page and section titles and every `h1`/`h2` are set narrow (`font-stretch: 86%`, the slate voice), body text at normal width; Geist Mono only for hex values and transcript timestamps |
| Type scale | `text-display` 44 px (a destination's hero title) · `text-page` 34 px · `text-section` 20 px · `text-title` 15 px semibold · `text-lead` 15 px · `text-sm` 14 px (body) · `text-small` 13 px · `text-caption` 12 px |
| Radius | tight, like hardware: `rounded-control` 6 px (buttons, inputs, menus) · `rounded-block` 8 px (inner blocks, media, tiles) · `rounded-card` 12 px (cards, panels, dialogs) · `rounded-full` pills and avatars. Tailwind's `rounded-lg/xl/2xl` are not used in the app |
| Elevation | panels sit flat on their line (`shadow-card` is a 1 px floor); only floating things cast a shadow (`shadow-raised`: menus, dialogs, sheets); `shadow-glow` is kept as a no-op |
| Marks | `.nav-active` (raised row + 2 px signal bar: the current destination) · `.next-up` (3 px signal bar: the one next step on a page) |
| Spacing | Tailwind's 4 px scale only (no 13/17/23 px values) |
| Motion | one easing (`ease-out-soft`); `animate-dialog-in`, `animate-sheet-left`/`-right`/`-up`, `animate-fade-in`; interactive cards lift 1 px; everything is reduced to an instant change under `prefers-reduced-motion` |

The only arbitrary sizes left are the 9–10 px labels inside the 9:16 preview miniatures, which
mirror the render's proportions.

## Primitives

| Primitive | Use |
| --- | --- |
| `Button` / `ButtonLink` | **primary** (the cue-yellow action, one per region: the next step) · **secondary** · **ghost** · **danger**. 32/40/48 px; 44 px on touch screens |
| `IconButton` | icon-only; requires `aria-label`; 36 px (44 px on touch) |
| `Card` | the one content surface; `interactive` for a card that is a link |
| `SectionHeader` | a section's heading, one line of context, and its actions |
| `Dialog` | modal dialogs and sheets (`placement` center, left, bottom) on the native `<dialog>`: inert page, Escape closes, focus returns to the trigger, backdrop closes |
| `Menu` | a menu button: arrow keys, Home/End, Escape and Tab close, focus returns |
| `SegmentedControl` | a few mutually exclusive views or filters (pressed buttons); `wrap` when every option must stay visible on phones (the Shorts library) |
| `ToolTabs` | tool groups that swap one panel (WAI-ARIA tabs: Left/Right/Home/End; panels stay mounted; a dot marks "in use" or "needs attention") |
| `Tooltip` | hover/focus description for icon-only controls; never the only way to information |
| `useToast` | brief confirmation of a small completed action; problems stay inline |
| `StatusPill` / `StatusBadge` | state in words plus a shape (never colour alone), tinted per state; `overlay` for a chip on a thumbnail |
| `VideoFrame` / `FrameTag` | a real still from the creator's own source, clip or Short at a given second (lazy, owner-checked media URL, fixed ratio so nothing shifts) and a small label on it (length, time range) |
| `PageHeader` | a page's title, back link and one primary action; `size="hero"` for a destination's front page; on large screens the search field (command menu) sits beside the action |
| `EmptyState`, `ErrorState`, `LoadingState`, `Skeleton`, `ProgressBar`, `WorkingState`, `InlineAlert` | intentional empty, failure and working states |
| `inputClasses`, `textareaClasses`, `selectClasses`, `Field` | one look for every input |

## Status language

`lib/status.ts` turns internal job states into creator words: **Waiting** (queued) ·
a recognisable working step (**Transcribing**, **Finding moments**, **Rendering**, otherwise
**Processing**) · **Ready** · **Needs attention** (failed, or a job that stopped reporting).
Unknown internal states read **Processing**, never their raw name. A **Short**'s status has its own
words, derived once on the server (`services/shorts_library.py`) and worded once in
`lib/shorts-rules.ts`: Draft · Rendering · Ready · Publishing · On YouTube · Published · Failed ·
Needs attention ([shorts-library.md](shorts-library.md)).

## Hierarchy

Page → its primary purpose → important content → secondary controls → advanced controls.
Primary actions (Upload video, Create Short, Render Short, Publish) are visually dominant; technical
details and exact numbers sit behind a disclosure.

## The app shell

A sidebar with Home, Projects (and the recent projects), Shorts, Analytics, Brand Studio and Settings —
the current one raised, with the signal bar at its edge — then **Ask PeakSift** low in the sidebar and the account
chip (Settings, Log out) at its foot. Phones get a top bar (menu, search, Ask PeakSift) and the
same sidebar as a sheet. No notification bell, plan label or counts: PeakSift has no data for
them.

## Imagery

Previews are the creator's own media: a source frame on project cards and the source card, a frame
at each moment's start on moment cards and Continue cards, the rendered Short on Short tiles and
analytics rows. Ratios are fixed (16:9 projects and moments, 9:16 Shorts); frames load only when
scrolled into view. No stock or generated photos are committed to imitate the reference pack.

## Markets and right-to-left text

Morocco Mode (V1.8) uses the same tokens and primitives — no flags, zellige, national colours or a
second theme. The mode is said in words ("Morocco Mode", "Made for: Morocco Mode", "Global library
included"), local items carry a plain "Local" / "Curated" pill, and Global alternatives are always
listed right after local ones. Creator text may be Arabic script: transcript lines, moment titles
and excerpts, hook ideas, the hook field and the caption/hook preview set `dir="auto"` so each line
takes its own direction (and punctuation) while the layout stays left-to-right.
