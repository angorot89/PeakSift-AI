# Tighten: remove pauses, cut parts

Built 28 November 2026 at the creator's request, after the StreamLadder clip-editor study
([product-research/streamladder-live-benchmark.md](product-research/streamladder-live-benchmark.md),
"AI – Remove silences"). A Short can leave out parts of its clip: the pauses between words, and
segments the creator cuts by hand. The editor shows and plays the shorter Short; the render
produces exactly it.

## The edit's `cuts` section

```json
"cuts": {"version": "cuts_v1", "removed": [[0.0, 0.52], [6.76, 7.04]]}
```

- Removed ranges are in the **clip's own time** (seconds from the start of the generated clip).
- `services/clip_edit/cuts.py` (`CutsConfig`) validates and normalizes: finite numbers, start
  before end, rounded to a millisecond, sorted, merged (a kept sliver under 0.04 s is folded into
  the cut), cuts under 0.05 s dropped, at most 300. Against the clip (API and again at render):
  no cut past its end, at least one second kept. Nothing is clamped or repaired.
- The section appears in the snapshot only when something is removed, so every earlier edit keeps
  its fingerprint. `EditConfig.output_seconds` is the Short's length before an end card.

## Two timelines

Everything the creator places — the hook, visuals, sound effects, the music bed, the logo and the
end card — is on the **Short's timeline** (the kept parts back to back), which is what the editor
timeline and the preview controls show. Only data that comes from the source is moved onto it:

| From the source | How it follows the cuts |
| --- | --- |
| Word timings (`caption_words`) | Moved *before* cues are grouped (`dynamic_text.dynamic_cues(cuts=…)`): a word that was cut away is dropped, one a cut runs through keeps what remains |
| Transcript phrases (phrase captions) | Each cue's span is moved; a cue entirely cut away is dropped |
| The smart-reframe crop path | `remap_crop_points`: keyframes inside cuts are dropped, the rest move, and each kept piece starts with the framing the source had there (so the crop jumps with the picture at a join) |

The API checks sound-effect times and visuals against the Short's length, not the clip's.

## Rendering

`services/clip_edit/tighten.py` runs first in the attempt's workspace: `trim`/`atrim` of each
kept piece, a 12 ms audio fade at every join (no clicks), `concat`, written near-lossless
(x264 CRF 12, PCM in Matroska) because the composition encodes it once more. Its length is
checked against the kept total. The rest of the pipeline then works on that file unchanged:
captions, audio mix, visuals, brand, the final encode and its validation. The V0.5 clip file is
never modified. Only module-formatted numbers reach the filtergraph.

## The editor

The **Tighten** tool (after Style):

- **Remove pauses** — the gaps between words longer than a chosen length (0.2 · 0.3 · 0.5 ·
  0.75 · 1 · 1.5 s, default 0.5 s, StreamLadder's), from the clip's real word timing (the same
  track word-synced captions use; "Find word timing" starts it). Silence before the first word
  and after the last counts; 0.08 s is kept next to every word. A live count ("11 pauses longer
  than 0.2 s · 2.8 s shorter"), then **Remove N pauses** / **Put the pauses back**. Changing the
  length while pauses are removed follows it at once.
- **Cut by hand** — **Split at playhead** (marks only; a split alone changes nothing), then
  **Remove this part** removes the part the playhead is in. Removed parts are listed with their
  times and a **Restore** each; restoring a part that swallowed removed pauses keeps those pauses
  out. **Restore everything** undoes it all.
- "Clip 23 s → Short 20 s", and the output line says "2.8 s tightened". Versions say "Tightened".
  A reopened version's pauses are recognised from the words (`recognizePauses`).

`lib/cuts.ts` mirrors the server's rules and holds the time map (`toOutput` / `toSource`),
pause finding, segments and restoring (unit-tested). The preview plays only what is kept: a
removed part is skipped as playback reaches it (or a seek lands in it) and playback stops where
the Short ends. The timeline, the preview controls, the hook, visuals, logo and the audio preview
read the Short's time (`ShortTimeContext`); captions use the clip's cues in clip time. On the
timeline the video track shows the kept frames with each join (amber) and split (white) marked;
the captions track shows the cues where they now play.

## Checked

- Backend: `tests/test_clip_edit_cuts.py` (normalization, fingerprints, the time map, the framing
  path, the filtergraph, a real tightened clip, captions following the cuts, a real render 3 s →
  2 s, invalid cuts at render, the API) plus the edit, pipeline, reframe, brand, dynamic-caption
  and Auto Edit suites.
- Frontend: `lib/cuts.test.ts`, `edit-draft.test.ts`, `editor-tools.test.ts`.
- Real browser, local test stack, a synthetic spoken test video: word timing → 11 pauses at 0.2 s
  → timeline 23.0 s → 20.2 s with 10 joins; seeking into a pause lands at its end; render ready
  at 20.23 s (H.264 1080×1920 + AAC, audio as long as the video, no silence ≥ 0.25 s left) with
  captions on the new timing; reopening restores the pauses; split / remove / restore; 375 px
  without overflow, 44 px targets; no console errors.

## Limitations

- Pauses need word timing (no estimate from the waveform alone).
- Splits are editing marks, not saved with the version.
- No ripple of placed items: when parts are removed, the hook, visuals and sounds keep their
  times on the Short's timeline (they do not follow the words that moved under them).
- Auto Edit does not tighten (plans have no cuts).
