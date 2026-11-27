# Editor timeline

The Short editor's timeline is the **visual map of the Short**: what happens and when, what is
selected, and what can change. It is creator-first visual editing, not a professional NLE: no
ripple edits, keyframes, nested timelines or arbitrary tracks. Parts of the clip can be left out
with **Tighten** (remove pauses, split and remove a part; see [tighten.md](tighten.md)); the
timeline then shows the shorter Short, with each join marked on the video track.

## Source of truth

The timeline has **no state of its own**. `timelineItems` (`frontend/lib/timeline.ts`) derives
every item from the editor's settings — the hook, the visual elements, the sound effects, the
music — and each item carries a reference back into that state (`hook`, a visual's key, a sound
effect's index, `music`). Every change made on the timeline goes through **the same setters the
forms use**, so a drag and a typed number produce the same request, and the server validates it
again when rendering. The only timeline state is *what is selected* (one id, shared with the
panels).

## Scale, ruler and playhead

- **Scale:** the canvas fits the whole Short, or scrolls horizontally when a second would be
  narrower than 28 px (44 px on touch screens). Track names stay sticky on the left.
- **Ruler:** a step from 0.5 s to 60 s that keeps labels apart ("0:02.5", "1:05").
- **Playhead:** follows the preview video through `requestAnimationFrame` while it plays and on
  seeks and pauses — DOM updates only, never a React render per frame. The same clock marks what
  is playing (`data-active`).
- **Seeking:** press or drag on empty canvas, drag the playhead, or use the playhead as a
  **slider** (arrow keys ±1 s, Shift ±5 s, Home, End).

## Tracks

| Track | Shows | Edits on the timeline |
| --- | --- | --- |
| Video | the clip as a film strip (≤ 12 frames drawn once from one hidden video) | — |
| Opening | the hook, from 0 s for its duration | drag its end (the server's hook limits) |
| Visuals | B-roll cutaways (lane 1), picture-in-picture and overlays (lane 2) | move, resize both ends |
| Captions | caption lines as segments, word timing as ticks on one canvas | — (click shows that line) |
| Sound | sound effects as markers, with each file's length | move |
| Music | the span heard, with the existing waveform (`heardPeaks`) | — |

Empty tracks say so with the one action that opens the right tool ("No visuals added · Add
visual", "No music · Add music"). The brand end card is noted under the timeline: it is in the
rendered Short, not in the preview.

## Interactions

- **Select** an item: it is highlighted, its tool opens (hook → Opening, visual → Visuals, effect or
  music → Sound, captions → Captions) and the preview shows it (`representativeTime`: a visual's
  middle, 0.5 s before an effect, the hook's start). The selected visual opens as one compact
  editor card; the selected effect is highlighted. Revealing a card scrolls **only inside the
  settings panel** (`revealInPanel`), never the page.
- **Drag / resize** (`editableEdges`, `dragTimes`): only timing the edit supports — visuals move and
  resize, effects move, the hook's end changes; music and captions do not drag. Times are stored
  to 0.05 s.
- **Snap** (`snapDelta`): the nearest dragged edge snaps within 8 px to the playhead, the ends or
  other items' edges, with a guide line. Hold **Alt** to place freely.
- **Feedback:** a timing bubble while dragging; an invalid position (e.g. two insets overlapping,
  from the editor's own `overlapProblems` / `elementProblems`) turns red and **goes back** on
  release, with the reason in a polite live message.
- **Keyboard:** ← → move a focused item (0.1 s; Shift 1 s), Alt + ← → change its end, Delete
  removes a visual or an effect. Dragging is never the only way; every item's accessible name
  says how it can be edited.
- **Tooltips** on hover or focus: "B-roll · 0:12.4–0:15.2", "Whoosh · 0:03.0", "Music · Full Short".
- **Render state** in the header: Rendered · Rendering… · Needs attention · Needs a fix to render ·
  Not rendered yet. A version is saved when it is rendered — there is no autosave, and nothing
  says "Saved" before that.

## Preview synchronisation

Both the timeline and the preview read one clock (the preview video) and the same rules: the
caption line lit on the timeline is found with the preview's own `cueAt` (a half-open interval),
so they cannot disagree; clicking the captions track shows the line under the pointer from its
start. B-roll videos keep following the main preview's time (no independent clock).

## Phones and touch screens

Preview → tool tabs → settings → timeline. The canvas scrolls inside its card (the page never
scrolls sideways), track names stay sticky (88 px column), seconds are at least 44 px wide on touch
and rows grow so every block is at least 44 px high; the playhead handle and markers have 44 px hit
areas and edge handles are 20 px wide. A selection bar under the timeline names the selected item
and jumps to its settings.

## Performance

Measured on a rich edit (hook, three visuals, word-synced captions, two effects, music): 162 DOM
nodes in the timeline (17 timed), **no long tasks** during playback. Word timing is drawn on a
canvas and caption lines are segments, so long Shorts do not create a node per word.

## Acceptance

**Release gate** — `backend/scripts/timeline_acceptance.py`: given a rendered version, reads its
saved configuration (the timing the timeline showed), downloads the render and checks every
cutaway's frames just before, inside (start, middle, end, past any fade) and just after; every
sound effect's onset (the effect file's own high-frequency envelope cross-correlated with the
render above 10 kHz, where speech is quieter; an effect starting in the last 0.3 s is cut and
skipped); and, for word-synced captions, two lines read back with Tesseract at their middle.

```bash
TIMELINE_ACCEPTANCE_EMAIL=… TIMELINE_ACCEPTANCE_PASSWORD=… \
  python scripts/timeline_acceptance.py --api http://localhost:8000 \
  --project ID --video ID --clip ID --edit ID
```

**Local results** (review stack, real renders):

- **Journey in a real browser** — Project → Moments → Create a Short → Auto Edit → editor → play →
  seek the timeline (6.0 s) → add B-roll at the playhead → drag it 0:06.0–0:09.0 → 0:07.0–0:10.0 →
  resize to 0:10.5 → add a sound effect and move it +1 s by keyboard (0:08.8 → 0:09.8) → select
  captions, choose Boxed → render → play the rendered Short → download (3,173,998 bytes); no
  console errors.
- **Gate on that render:** the saved configuration is exactly what the timeline showed (B-roll
  7.0–10.5 s, effect 9.8 s, Boxed captions); the cutaway is on screen from 7.00 to 10.50 s (colour
  distance 1 inside, 116+ outside); the effect is heard at 9.8 s; two caption lines read back 4/4
  and 5/5 words.
- **Gate on the seeded rich edit:** cutaway 4.00–6.50 s exact; effect at 3.00 s heard at 3.03 s; an
  effect placed at the very end is cut (skipped); captions 2/2 and 3/3.

## Limitations

- Splitting and removing parts happen in the Tighten tool (not by dragging on the video track);
  no ripple edits, keyframes, transitions beyond a fade, or extra tracks; music always starts with the Short (its start point and loop are set in Sound).
- Captions and music do not drag; caption timing comes from word sync or the transcript.
- The preview's sizes are close, not pixel-exact; the rendered Short is the final result.
- Timeline edits are saved as a version only when rendered (no autosave).
