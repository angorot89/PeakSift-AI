# PeakSift design system

One dark, warm theme (V1.5, refined by the visual overhaul that followed V1.7), evolved rather
than replaced. Tokens live in `frontend/app/globals.css`;
primitives in `frontend/components/ui/`. Use them instead of one-off values in JSX.

## Tokens

| Group | Tokens |
| --- | --- |
| Surfaces (page → raised) | a warm near-black `background` · `surface` · `surface-2` · `surface-3`; borders `border`, `border-strong`; a faint fixed warm light behind the workspace (`.app-atmosphere`) |
| Text | `foreground` (primary) · `muted` (secondary, ≥ 7:1 on panels) · `subtle` (metadata, ≥ 4.5:1) |
| Accent | `accent` (marks, focus) · `accent-soft` (accent text on dark) · `accent-fill` / `accent-fill-hover` with dark `accent-ink` text (≥ 8:1) — the primary action |
| Semantic accents | `success` (done, published) · `info` (facts, drafts, links) · `violet` (working, rendering, AI) · `warning` · `danger` — only where they mean something |
| Type scale | `text-display` 40 px (a destination's hero title) · `text-page` 32 px · `text-section` 20 px · `text-title` 15 px semibold · `text-lead` 15 px · `text-sm` 14 px (body) · `text-small` 13 px · `text-caption` 12 px |
| Radius | `rounded-control` 10 px (buttons, inputs, menus) · `rounded-block` 14 px (inner blocks, media, tiles) · `rounded-card` 18 px (cards, panels, dialogs) · `rounded-full` pills and avatars |
| Elevation | `shadow-card` (hairline highlight + soft drop) · `shadow-raised` (menus, panels) · `shadow-glow` (the primary action only) |
| Spacing | Tailwind's 4 px scale only (no 13/17/23 px values) |
| Motion | one easing (`ease-out-soft`); `animate-dialog-in`, `animate-sheet-left`/`-right`/`-up`, `animate-fade-in`; interactive cards lift 1 px; everything is reduced to an instant change under `prefers-reduced-motion` |

The only arbitrary sizes left are the 9–10 px labels inside the 9:16 preview miniatures, which
mirror the render's proportions.

## Primitives

| Primitive | Use |
| --- | --- |
| `Button` / `ButtonLink` | **primary** (the warm orange action, one per region: the next step) · **secondary** · **ghost** · **danger**. 32/40/48 px; 44 px on touch screens |
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
| `PeakArt` | decorative SVG ridges behind a hero header (never a photograph) |
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
the current one in a warm highlight — then **Ask PeakSift** low in the sidebar and the account
chip (Settings, Log out) at its foot. Phones get a top bar (menu, search, Ask PeakSift) and the
same sidebar as a sheet. No notification bell, plan label or counts: PeakSift has no data for
them.

## Imagery

Previews are the creator's own media: a source frame on project cards and the source card, a frame
at each moment's start on moment cards and Continue cards, the rendered Short on Short tiles and
analytics rows. Ratios are fixed (16:9 projects and moments, 9:16 Shorts); frames load only when
scrolled into view. No stock or generated photos are committed to imitate the reference pack.
