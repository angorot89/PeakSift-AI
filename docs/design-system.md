# PeakSift design system (V1.5)

One dark theme, refined rather than replaced. Tokens live in `frontend/app/globals.css`;
primitives in `frontend/components/ui/`. Use them instead of one-off values in JSX.

## Tokens

| Group | Tokens |
| --- | --- |
| Surfaces (page → raised) | `background` · `surface` · `surface-2` · `surface-3`; borders `border`, `border-strong` |
| Text | `foreground` (primary) · `muted` (secondary, ≥ 7:1 on panels) · `subtle` (metadata, ≥ 4.5:1) |
| Accent and status | `accent` / `accent-soft` (one brand accent, used sparingly) · `success` · `warning` · `danger` |
| Type scale | `text-page` 26 px (page title) · `text-section` 17 px · `text-title` 15 px semibold (card and dialog titles) · `text-lead` 15 px · `text-sm` 14 px (body) · `text-small` 13 px · `text-caption` 12 px |
| Radius | `rounded-lg` controls · `rounded-xl` inner blocks and media · `rounded-2xl` cards and dialogs · `rounded-full` pills and avatars |
| Spacing | Tailwind's 4 px scale only (no 13/17/23 px values) |
| Motion | `animate-dialog-in`, `animate-sheet-left`, `animate-sheet-up`, `animate-fade-in`; everything is reduced to an instant change under `prefers-reduced-motion` |

The only arbitrary sizes left are the 9–10 px labels inside the 9:16 preview miniatures, which
mirror the render's proportions.

## Primitives

| Primitive | Use |
| --- | --- |
| `Button` / `ButtonLink` | **primary** (one per region: the next step) · **secondary** · **ghost** · **danger**. 32/40/48 px; 40/44 px on touch screens |
| `IconButton` | icon-only; requires `aria-label`; 36 px (44 px on touch) |
| `Card` | the one content surface; `interactive` for a card that is a link |
| `SectionHeader` | a section's heading, one line of context, and its actions |
| `Dialog` | modal dialogs and sheets (`placement` center, left, bottom) on the native `<dialog>`: inert page, Escape closes, focus returns to the trigger, backdrop closes |
| `Menu` | a menu button: arrow keys, Home/End, Escape and Tab close, focus returns |
| `SegmentedControl` | a few mutually exclusive views or filters (pressed buttons) |
| `ToolTabs` | tool groups that swap one panel (WAI-ARIA tabs: Left/Right/Home/End; panels stay mounted; a dot marks "in use" or "needs attention") |
| `Tooltip` | hover/focus description for icon-only controls; never the only way to information |
| `useToast` | brief confirmation of a small completed action; problems stay inline |
| `StatusPill` / `StatusBadge` | state in words plus a shape (never colour alone) |
| `EmptyState`, `ErrorState`, `LoadingState`, `Skeleton`, `ProgressBar`, `WorkingState`, `InlineAlert` | intentional empty, failure and working states |
| `inputClasses`, `textareaClasses`, `selectClasses`, `Field` | one look for every input |

## Status language

`lib/status.ts` turns internal job states into creator words: **Waiting** (queued) ·
a recognisable working step (**Transcribing**, **Finding moments**, **Rendering**, otherwise
**Processing**) · **Ready** · **Needs attention** (failed, or a job that stopped reporting).
Unknown internal states read **Processing**, never their raw name.

## Hierarchy

Page → its primary purpose → important content → secondary controls → advanced controls.
Primary actions (Upload video, Create Short, Render Short, Publish) are visually dominant; technical
details and exact numbers sit behind a disclosure.
