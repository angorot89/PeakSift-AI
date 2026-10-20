# B-roll & visual enrichment (V1.1)

V1.1 lets a creator add their own pictures and footage to a short: **B-roll cutaways**,
**picture-in-picture** insets and **image overlays**, placed in the short-form editor and burned
into the rendered 9:16 short together with everything V0.6–V1.0 already does (layouts, Smart
Reframe, word-synced captions, the hook, music and sound effects). A local language model can
**suggest** where a visual would help and what it should show, and PeakSift points at matching
assets the creator has already uploaded.

Status: **implementation complete, pending CI/merge/release.** The work is on stacked pull
requests that wait for GitHub Actions; it is not released.

## What it does, and does not do

Does:

- A per-project **visual library**: JPEG, PNG and WebP images and MP4, MOV and WebM videos the
  creator uploads, validated from their contents, with thumbnails, a preview, a description and
  tags.
- **Suggestions**: for a clip, short moments (1–6 s) where a visual would illustrate what is
  being said, each with a search-style query ("toothpick bridge model") and a reason, from a
  local model with an honest deterministic fallback.
- **Matching**: each suggestion lists up to three of the project's own assets whose tags, name
  or description cover it. Nothing is placed automatically.
- Three **modes** per element — cutaway, picture-in-picture, overlay — with timing, fit, corner,
  size, opacity, video start, looping and a cut or fade transition, previewed live in the editor
  and rendered by FFmpeg.

Does not:

- Search, download or scrape anything. There is no stock provider, no internet image search,
  no generated imagery and no global asset library: every visual is a file the creator
  uploaded to the project.
- Understand images. Matching compares words (tags, file name, description); it does not look
  at pixels, and there are no embeddings.
- Use B-roll sound. B-roll videos always render muted; the short's audio is exactly what the
  edit's audio section says.
- Offer a timeline editor, keyframes, motion paths, zoom/pan (Ken Burns), masks, green screen,
  split screen, stickers, animated text or transitions other than a fade.

## Rights

Visuals are **creator-supplied only**. The upload area says so: upload only images and videos
you own or have permission to use. PeakSift never fetches media from the internet, ships no
stock or sample media, and never commits media files to the repository; test fixtures are
generated with Pillow or FFmpeg at test time. A suggestion's query describes what *could* be
shown; it is not a license to find it anywhere.

## Architecture

```
upload ─► visual_assets (validate · normalize · thumbnail · sha256) ─► StorageProvider
clip transcript / caption words ─► broll pipeline (Celery) ─► provider (ollama | keyword)
        └► validation ─► grounding ─► density/dedupe ─► broll_suggestions ─► matching (API)
editor: suggestion → asset → element ─► edit configuration `visuals` (visuals_v1)
render: clip → layout / smart reframe → [framed] → visual layers → [visual] → captions + hook
```

| Area | Code |
| --- | --- |
| Asset model | `app/models/visual_asset.py` (`VisualAsset`: kind, display size, duration, fps, codec, container, alpha, sound, sha256, thumbnail key, description, tags) |
| Upload, inspection, thumbnails | `app/services/visual_assets.py` |
| Asset API | `app/api/visual_assets.py` |
| Suggestion models | `app/models/broll.py` (`BrollAnalysis`, `BrollSuggestion`) |
| Suggestions | `app/services/broll/` — `contract.py`, `ollama.py`, `keyword.py`, `validation.py`, `grounding.py`, `suggest.py`, `config.py`, `pipeline.py`, `matching.py` |
| Suggestion API | `app/api/broll.py` |
| Edit visuals | `app/services/visuals/` — `config.py`, `assets.py`, `layout.py`, `transitions.py`, `compositor.py` |
| Rendering | `app/services/clip_edit/composition.py` (`compose_short`, `supports_visuals`) |
| Frontend | `components/app/visual-library.tsx`, `components/app/editor/visuals-panel.tsx`, `visuals-layer.tsx`, `asset-chooser.tsx`; `lib/visuals.ts`, `lib/visual-rules.ts`, `lib/visual-elements.ts`, `lib/broll.ts` |

Migrations: `4348b16893ab` (visual assets), `cb89be111f89` (B-roll analyses and suggestions),
`645acf546ce4` (asset description and tags).

## Visual assets

### Upload and validation

`POST /projects/{id}/visual-assets` (multipart). An upload is accepted only when its
contents are what its extension says:

| Kind | Extensions | Checked with | Stored |
| --- | --- | --- | --- |
| Image | `.jpg` `.jpeg` `.png` `.webp` | Pillow identifies the format from the bytes | A normalized rendition |
| Video | `.mp4` `.m4v` `.mov` `.webm` | ffprobe: container matches the extension, a real video stream with an allow-listed codec (H.264, HEVC, VP8, VP9, AV1, MPEG-4, ProRes), positive size and duration | The original file |

Images:

- the pixel count is checked from the header before decoding (decompression bombs); animated
  images are refused;
- the picture is rotated upright from its EXIF orientation, an embedded colour profile
  (Display P3, a print CMYK profile) is converted to sRGB, CMYK, palette and 16-bit images
  become RGB (RGBA when any pixel is transparent), a multi-picture JPEG (MPO) keeps its primary
  picture, and the result is bounded to 3840 px and re-encoded (PNG with alpha, otherwise JPEG);
- so EXIF metadata such as GPS positions is never stored, and every later step sees exactly
  the pixels the creator saw.

Videos: rotation and sample aspect ratio give the display size; a representative frame is
decoded for the thumbnail, which also proves the stream decodes. Its sound is recorded
(`has_audio`) but never used.

Limits are server configuration and are shown in the upload area
(`GET /visual-upload-limits`):

| Setting | Default |
| --- | --- |
| `VISUAL_ASSET_MAX_BYTES` | 500 MB |
| `VISUAL_ASSET_MAX_VIDEO_DURATION_SECONDS` | 600 |
| `VISUAL_ASSET_MAX_PIXEL_COUNT` (images) | 40 megapixels |
| `VISUAL_ASSET_MAX_VIDEO_PIXEL_COUNT` | 4096 × 2304 |

The upload is hashed while it is spooled: the same file uploaded again to the same project
returns the existing asset. Every refusal removes what was written. Uploads are rate limited
(`visual_upload`, 200 per hour per user).

### Storage and thumbnails

Files and thumbnails (JPEG, at most 480 px, PNG when the image has transparency) go through
the `StorageProvider` contract with generated keys, so they live in the local media directory
or the private S3-compatible bucket like every other file. The API streams them only to the
project's owner: `GET …/visual-assets/{id}/content` (HTTP Range, for video preview) and
`…/thumbnail`. There are no public or presigned URLs.

### Details, search and deletion

- `PATCH …/visual-assets/{id}` sets the display name, a description (≤ 500 characters) and up
  to 20 tags (≤ 32 characters each; lower-cased, letters, digits, spaces and hyphens,
  de-duplicated; longer or more are refused, never cut). Text is cleaned of control characters
  and stored as plain text.
- `GET …/visual-assets?q=…&kind=image|video` searches names, descriptions and tags.
- `DELETE …/visual-assets/{id}` is refused with `409` while any edit references the asset —
  rendered and future edits never lose an input — and otherwise removes the row, then its
  files (leftovers are cleanup's job). Deleting a project removes its visuals.

## B-roll suggestions

### Flow

`POST …/clips/{clip_id}/broll/analyses` queues a job (`peaksift.suggest_broll`; the task id is
generated and committed first and every commit checks it). The job reads what was said in
the clip, in clip-local seconds: the word timing of the clip's latest caption track when there
is one, otherwise the transcript segments overlapping the clip. No media is read. Progress is
stage-based (5 claimed, 20 analyzing, 80 validating, 100 completed) because a language model
exposes no real progress. Suggestions, counts and `completed` are written in one commit.
`GET …/broll` returns the current analysis, its suggestions and their matches; `retry`
re-runs a failed or stalled analysis; `PATCH …/broll/suggestions/{id}` marks one used or
dismissed (`accepted` / `dismissed`). Starting is rate limited (`broll_suggest`, 60 per hour per user). A failed
suggestion job never blocks editing or rendering.

### Providers

The provider is server configuration (`BROLL_SUGGESTION_PROVIDER`); clients never choose it.

- `ollama` (default): the local model `BROLL_OLLAMA_MODEL` (empty: the first
  `OLLAMA_CLIP_MODELS` entry) answers a JSON schema at temperature 0 with moments, queries,
  reasons and a 0–100 editorial score.
- `keyword`: deterministic — each proper name in the transcript ("NASA", "the Eiffel Tower")
  becomes a short suggestion starting just before it is said. Without word timing the moment
  is estimated from the name's position in its line, so check its timing.
- When the model cannot answer (unreachable, timed out, not installed, malformed reply) and
  `BROLL_FALLBACK_ENABLED` is on, the keyword provider stands in and the analysis says so
  (`method`: `local_ai`, `keyword` or `keyword_fallback`). The editor adds a note to keyword
  suggestions — *Based on names mentioned in the clip*, or *The local AI was unavailable, so
  these are based on names mentioned in the clip*.

### Review

Everything a model returns is untrusted. Each proposal is checked and either kept or counted
as rejected (never clamped or rewritten):

1. **Validation**: 1–6 s inside the clip, a non-empty concrete query (filler words removed), a
   reason, a score on the 0–100 scale.
2. **Grounding**: at least one subject word of the query was said within 2 s of the moment;
   no invented names (every capitalised name in the query occurs in the transcript); not made
   only of abstract words ("success", "an important thing").
3. **Density**: duplicates within 2 s and overlaps are removed, at most one suggestion per 7 s
   of clip and at most 8, best score first.

Grounding is a guard, not proof of good taste: the creator decides what to use.

The snapshot (`broll_suggest_v1`) records the provider, model and rules for each analysis;
`BROLL_STALE_AFTER_SECONDS` and `BROLL_MAX_ATTEMPTS` bound stalled jobs.

## Matching

Each suggestion is compared with the project's assets — no internet, no embeddings. An
asset's words are its file name (split on `-`, `_`, `.` and spaces), description and tags;
words match on the same short stems grounding uses ("bridge" ↔ "bridges").

```
score = Σ weight(matched subject word) / number of subject words
weights: tag 1.0 · name 0.9 · description 0.7
```

An asset is a likely match at a score of at least 0.5; at most three are shown, strongest
first. The editor offers them as one-click choices on the suggestion and in the asset chooser
("Likely matches"); the creator can always pick any other asset or upload one. Tagging assets
with what they show is the best way to get matches.

## Visual elements

An edit's configuration gains an optional `visuals` section (`visuals_v1`), present only when
used: edits without visuals keep exactly their earlier snapshot and fingerprint.

| Field | Values |
| --- | --- |
| `asset_id` | one of the project's visual assets |
| `mode` | `cutaway` · `pip` · `overlay` (overlays use images) |
| `start_seconds`, `end_seconds` | clip-local, at least 0.5 s long, inside the clip (10 ms steps) |
| `fit` (cutaway) | `fill` (crop to fill) · `fit` (whole picture over a blurred copy) |
| `position`, `size` (pip/overlay) | `top_left` · `top_right` · `bottom_left` · `bottom_right` · `center`; `small` · `medium` · `large` |
| `opacity` | 0.2–1 (1 % steps) |
| `asset_offset_seconds`, `loop` (video) | where the video starts; whether it repeats when shorter than the element |
| `transition`, `transition_seconds` | `none` (cut) · `fade`, 0.1–0.5 s and never more than half the element |

Rules: at most 12 elements; at any instant at most one cutaway and one inset (pip or overlay);
options that do not apply to a mode are dropped and values are rounded, so equivalent requests
share a fingerprint. The API checks — and the render job checks again — that every asset
belongs to the edit's project, overlays are images, images take no video start or loop, a
video's start lies inside it and (without loop) it lasts the element, and no element ends
after the clip. Messages never echo values.

### Layout

Inset boxes are 34 / 44 / 56 % of the frame width (small / medium / large) with a height of at
most 1.25 × the width, placed inside the general social safe area (192 px top, 422 px bottom,
97 px sides), so platform buttons do not cover them. Captions and the hook are drawn above
insets, so text stays readable, but a bottom-corner inset can sit behind bottom captions —
choose a top corner or move the captions when that matters. Picture-in-picture gets a 6 px
white frame. `GET /visual-layout` returns these numbers, and the editor preview uses
the same ones.

## Rendering

`compose_short` builds the picture in this order:

```
clip → layout / smart reframe → [framed] → visual elements → [visual] → captions + hook
```

- Captions and the hook are burned in after every visual: they stay on top and readable.
- The main video drives the timeline: each element is a layer enabled only during its
  interval and released when it ends, so the short keeps the clip's duration and frame rate
  whatever the assets are (a 15 or 60 fps B-roll does not change a 25 fps short).
- Each element is its own FFmpeg input trimmed at the input (`-ss`/`-t`), so nothing outside
  its interval is decoded. Images are looped at the short's frame rate; videos start at their
  offset (`-stream_loop -1` only when looping) and are never decoded for sound (`-an`).
- Per layer: square pixels, the short's frame rate, transparency flattened onto `#111113` for
  cutaways and picture-in-picture (overlays keep it), fill/fit or a bounded box — never
  stretched — then the optional alpha fade.
- Only module-formatted numbers and allow-listed values reach the filtergraph; asset files are
  argument-list inputs, never part of a filter. `supports_visuals` checks that the installed
  FFmpeg has every filter used; without it, edits with visuals are refused rather than
  rendered wrong.
- Assets are fetched from storage into the attempt's scratch directory; the result is
  validated with ffprobe like every short (1080 × 1920, H.264, AAC).

## Editor

- **Project page → Visual assets**: drag-and-drop or choose files, per-file progress and
  errors, an images/videos filter, search, thumbnails, a preview dialog (image or playable
  video) with description, tags and delete.
- **Short editor → Visuals** (between Hook and Audio):
  - *Suggest B-roll* / *Suggest again*: stage-based progress, then each suggestion's moment,
    query and reason, a note when the keyword provider made them, likely matches as one-click
    buttons, *Use asset* and *Dismiss*.
  - *Add visual*: the asset chooser (images/videos, search, likely matches, upload in place).
  - One card per element with the mode picker, start/end, *Start at playhead*, fit, position,
    size, opacity, video start, loop and transition, plus a small timeline of all elements;
    problems are shown on the card before rendering.
  - The stage previews visuals live over the video (cutaway, inset frame, overlay opacity,
    fades, video time with offset and loop). The preview is approximate; the rendered short
    is the reference.

## API summary

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/visual-upload-limits` | formats and limits |
| `GET` | `/visual-layout` | inset sizes and safe margins |
| `POST` | `/projects/{p}/visual-assets` | upload (rate limited) |
| `GET` | `/projects/{p}/visual-assets` | list, `q`, `kind` |
| `GET` / `PATCH` / `DELETE` | `/projects/{p}/visual-assets/{a}` | details; delete `409` while used |
| `GET` | `/projects/{p}/visual-assets/{a}/content`, `/thumbnail` | owner-only streams, Range |
| `GET` | `/projects/{p}/videos/{v}/clips/{c}/broll` | analysis, suggestions, matches |
| `POST` | `…/broll/analyses`, `…/broll/analyses/{id}/retry` | start / retry (rate limited) |
| `GET` | `…/broll/analyses/{id}`, `…/broll/analyses/{id}/suggestions` | |
| `PATCH` | `…/broll/suggestions/{id}` | `accepted` (used) / `dismissed` / `suggested` |

Every endpoint is scoped to the current user and returns `404` for other users' resources.

## Security

- Contents decide the type (Pillow, ffprobe); browser filenames and MIME types are never
  trusted and never become paths; storage keys are generated.
- Pixel and duration limits are checked before decoding; images are re-encoded, removing
  metadata.
- External tools run with argument lists and timeouts; stderr is never stored or returned.
- Descriptions and tags are plain text, length-limited, control characters removed, rendered
  by React (no HTML).
- Suggestion text from a model is untrusted: it is validated and grounded, never reaches a
  filtergraph, shell or path, and is shown as text.
- Media is private: owner-checked streaming only, no public or presigned URLs.
- Ownership is checked at the API and again at render; error messages never contain paths,
  keys, ids or submitted values.

## Testing

- Unit and API suites: asset validation (formats, spoofed extensions, bombs, animation, EXIF,
  colour profiles, CMYK, 16-bit, MPO, transparency), details and search, deletion and
  references, suggestion validation, grounding, providers (fake Ollama), the pipeline (eager
  Celery, fencing, fallback), matching, the visuals configuration, layout, transitions and
  the edit API.
- Render suites on real FFmpeg: every mode, fit and corner; fades that ramp; exact video
  offsets with no flashed frames; looping; no stretching; insets inside the safe area; hooks
  and captions over cutaways; 15/60 fps B-roll; Smart Reframe, audio and the full V1 stack
  with visuals; S3 (moto and a live MinIO).
- `python scripts/visual_render_probe.py`: ten generated cases through the real compositor
  (used by CI and the acceptance checklist).
- CI (`.github/workflows/ci.yml`) runs the probe and the V1.1 suites with live S3 required;
  the container smoke test uploads, thumbnails, streams and deletes a visual asset.
- Frontend: rules, keys, inset geometry and preview timing (`npm test`).

No test downloads media or a model; fixtures are generated at test time.

## Known limitations (V1.1)

- Matching is word-based: an untagged `IMG_4021.jpg` will not match anything. Tag assets.
- A small local model can return few or no suggestions for a clip, and suggestions that fail
  grounding are dropped, not repaired; the keyword fallback finds only proper names.
- Keyword timing without word timestamps is estimated from text position.
- The editor preview approximates the render (browser scaling and decoding); fades and video
  seeking can differ by a frame.
- No zoom/pan on images, no per-element keyframes, one fade style, one cutaway and one inset
  at a time.
- B-roll sound is never used.
- Insets are not moved out of the caption band automatically; the editor preview shows any
  overlap.
- Very long or very high-bitrate B-roll increases render time; only the used interval is
  decoded, but each element is a separate input.
