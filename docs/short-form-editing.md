# Short-form editing (Milestone 6)

This page explains how PeakSift turns a generated clip into a 9:16 vertical short, with captions burned in from the transcript. It is the reference for operators and contributors. The end-user walkthrough is at the end.

> **V0.8:** word-synced dynamic captions — the Focus, Punch, Minimal and Boxed presets with the spoken word emphasised, the social safe area and the opening hook (renderer `caption_v2`) — are documented in [dynamic-captions.md](dynamic-captions.md). This page describes the V0.6 phrase renderer (`caption_v1`) used by the Clean, Bold and Creator styles; existing edits keep their original behaviour.

> **V0.9:** an edit can also carry an audio section — music, sound effects, ducking and loudness normalization — documented in [audio-sound-design.md](audio-sound-design.md). Without it the clip's own audio is kept exactly as described here.

## What it does, and does not do

When a clip is ready, its owner picks a **layout** and **caption** options and clicks **Render short**. A background worker composes the clip at 1080 × 1920 with FFmpeg. If captions are on, it burns in captions built from the persisted transcript. The worker validates the result with ffprobe and stores it as a private MP4, which the owner can preview and download.

Each combination of settings is a separate **edit variant** of the same clip. The V0.5 clip file is the read-only source. It is never modified, replaced or deleted by editing.

> **V0.7 update.** Milestone 7 added two framing layouts on top of this pipeline: **Smart reframe** (`smart_reframe`, a crop that follows tracked faces) and **Manual crop** (`manual_crop`, a fixed crop around a chosen focal point). They are described in [smart-reframing.md](smart-reframing.md); everything else on this page applies to them unchanged.

V0.6 does **not** include:

- AI subject or face tracking, or dynamic or automatic reframing.
- Manual crop positioning. Crops are always centred.
- Word-by-word captions, karaoke highlighting or caption animation.
- A timeline, trim handles or frame-by-frame editing.
- Music, sound effects, B-roll, transitions, stickers or overlays.
- Custom fonts, brand kits or watermarks.
- Publishing to TikTok, YouTube or Instagram.

## Pipeline

```
POST …/clips/{clip_id}/edits  {layout, captions_enabled, caption_style?, caption_position?}
  → validate against allow-lists, normalize, fingerprint the config
  → same fingerprint as an existing edit? → 200 + that edit   (failed one → 409: use retry)
  → ClipEdit row (queued, config snapshot, pre-chosen Celery task id = attempt token)
  → enqueue peaksift.render_clip_edit(edit_id)  →  201 at once

Worker (app/services/clip_edit/pipeline.py):
  claim (DB state + attempt token); discard leftovers from earlier attempts      (progress 5)
  → captions: transcript segments → clip-local cues → escaped ASS file            (15)
  → rendering   ffmpeg (layout filtergraph [+ subtitles]) → work-<attempt>/short.mp4
                heartbeat every CLIP_RENDER_HEARTBEAT_SECONDS                       (85)
  → validating  ffprobe: H.264, exactly 1080×1920, fps, duration, audio iff source  (90)
  → atomic rename to edits/<edit-id>/edited.mp4, then ONE commit: storage_key + metadata + ready (100)
  | failed      error_code + safe error_message; every file of the edit removed
```

`ready` always means that a validated file exists at the final location. If a ready edit's file goes missing, the API reconciles the row to `failed` / `artifact_missing`, and the edit can be retried.

## Layouts (9:16, 1080 × 1920)

Every layout keeps the source's aspect ratio. Nothing is stretched. Rotation metadata is applied while decoding, so phone footage is composed upright.

| Layout | What you get |
| --- | --- |
| `center_crop` (**Center crop**) | The source is scaled until it fills 1080 × 1920, then the centre is cropped. On a landscape source the sides are cut off. |
| `blur_background` (**Blur background**, the default) | The whole source frame is scaled to fit the width and centred. Behind it is a blurred, frame-filling copy of the same video, blurred at quarter resolution with `gblur=sigma=12`. Nothing is cropped from the foreground. |
| `fit` | The whole source frame on a plain dark background (`#111113`). |
| `smart_reframe` (**Smart reframe**, V0.7) | A fixed-size 9:16 crop whose position follows a completed face-tracking crop path, scaled to 1080 × 1920; captions are drawn after the crop, so they stay fixed on screen. Requires `reframe_analysis_id`. See [smart-reframing.md](smart-reframing.md). |
| `manual_crop` (**Manual crop**, V0.7) | A fixed 9:16 crop centred on `focus_x`/`focus_y` (0–1, clamped inside the frame). |

Filtergraphs are built only from constants, chosen by the validated layout enum. No request value or transcript text ever reaches a filtergraph.

## Captions

**Source.** Captions come only from the video's persisted transcript, the `TranscriptSegment` rows from V0.3. No LLM is involved, and the text is never rewritten, translated or "improved". A captioned render needs a completed transcript. Without one the API answers 409, and the pipeline fails with `transcript_unavailable` if the transcript disappeared meanwhile.

**Timing.** V0.3 stores segment-level timestamps, not word timings. Each word gets a share of its segment's duration, proportional to its length. That is a deterministic *approximation* of when the word was spoken, and PeakSift does not claim word-level sync:

- Cue boundaries inside a segment are approximate. Segment boundaries are the transcript's own.
- Timestamps are shifted to clip-local time, `local = absolute − clip.start`.
- A word is kept when its estimated midpoint falls inside the clip.
- Cues are clamped to `[0, clip duration]`. They never overlap, and a cue shorter than 0.2 s after clamping is not shown.

**Segmentation.** Cues are built greedily and deterministically:

- A cue holds at most `CAPTION_MAX_WORDS` words (7) and `CAPTION_MAX_CHARS` characters (32).
- A cue prefers to break after sentence punctuation (`. ! ? … 。 ؟`) or clause punctuation (`, ; : ،`).
- A single trailing word is merged back onto the previous cue.
- libass wraps only at spaces. An unspaced token wider than one line, such as a URL, CJK text or a long compound word, is split into balanced pieces that fit one line. Wide East Asian characters count double, and combining marks stay attached. Each piece is its own cue, so no space is inserted and no text is lost.

**Text safety.** Transcript text is untrusted:

- Control characters become spaces, and bidi override and isolate controls are dropped. Joiners and the LRM/RLM marks are kept.
- Emoji are left out, because the caption fonts have no emoji glyphs and libass cannot draw colour emoji. They would otherwise burn in as empty boxes.
- Every backslash is followed by an invisible WORD JOINER, so `\N`, `\n`, `\h` and override tags can never form. Braces become `\{` / `\}`, so no `{…}` override block can open.
- This was verified against real libass output.

Users choose only a preset name and a position. They can never submit ASS syntax, colours, fonts or sizes.

**Styles** (`caption_style`), on the 1080 × 1920 canvas:

| Preset | Look |
| --- | --- |
| `bold` (default) | 80 px bold white text, 6 px black outline, soft shadow |
| `clean` | 62 px regular white text, 3 px black outline |
| `creator` | 72 px bold yellow text on a dark translucent box |

**Positions** (`caption_position`):

- `bottom` (default) sits 320 px above the bottom edge, clear of platform UI.
- `center` is vertically centred.
- `top` sits 260 px below the top edge.

Side margins are 90 px. Turning captions off drops style and position from the configuration.

**Fonts.** Captions use `CAPTION_FONT_FAMILY`, default **Noto Sans**, through fontconfig.

- **Fallback.** Scripts the family lacks fall back to other installed fonts. Noto Sans Arabic covers Arabic, which libass shapes and lays out right to left.
- **Arabic scope.** Arabic was checked visually on sample text. That is not a claim of typographic quality for every Arabic text or dialect.
- **Licensing.** No font file is committed. Install the fonts from your OS packages. The Noto fonts are OFL.
- **Probe.** Before a captioned render, the worker burns a probe caption onto a black frame. If no text pixels appear, which means no usable font, the render fails with `caption_font_unavailable` rather than producing a short without captions.

If no transcript speech falls inside the clip, the short is rendered without a caption layer and reports `caption_cue_count = 0`. The UI says so.

## Output and validation

Profile `vertical_1080x1920_v1`:

- Fast-start MP4 (`+faststart`).
- H.264 (libx264, `yuv420p`) with `CLIP_RENDER_PRESET` / `CLIP_RENDER_CRF`.
- AAC at `CLIP_AUDIO_BITRATE` when the clip has audio. A video-only clip gives a video-only short.

ffprobe must confirm:

- H.264 video at exactly 1080 × 1920 with a frame rate.
- A duration within `CLIP_RENDER_DURATION_TOLERANCE_SECONDS` of the source clip.
- AAC audio if and only if the source had audio.

Anything else is rejected and deleted.

FFmpeg runs as an argument list, never a shell, with a timeout. Its working directory is the attempt's workspace, so the caption file is referenced as the fixed relative name `captions.ass`. No path appears in a filtergraph. FFmpeg stderr is never stored or returned, and the log tail replaces paths with placeholders.

## Reliability

- **Attempt ownership.** The Celery task id is generated and committed on the row before enqueueing. Every pipeline commit and the failure path re-read it. A worker that a retry has taken over stops at its next heartbeat, never writes the row and removes only its own `work-<attempt>` directory.
- **Deleted rows.** An edit whose row was deleted mid-render stops, writes nothing and removes its own files.
- **Idempotent.** A ready edit is never re-rendered, and a live one (fresh heartbeat) is never started twice. Duplicate deliveries are no-ops.
- **Deduplication.** Equivalent requests normalize to one fingerprint, and `(clip_id, config_fingerprint)` is unique. A double click, a network retry or two tabs get the same edit.
- **Stale jobs.** A `rendering`/`validating` edit whose heartbeat is older than `CLIP_RENDER_STALE_AFTER_SECONDS` is reported `is_stale` and can be retried.
- **Retry.** Only failed or stalled edits can be retried. A retry keeps the same edit id and gets a new attempt and token, up to `CLIP_RENDER_MAX_ATTEMPTS` attempts. The row is locked during a retry, so concurrent retries serialize and the second gets 409.
- **Failure codes:**
  - Source and transcript: `clip_not_ready`, `clip_missing`, `source_missing`, `source_unreadable`, `transcript_unavailable`, `captions_missing`.
  - Renderer and fonts: `captions_unavailable` (no libass), `caption_font_unavailable`, `ffmpeg_missing`, `ffmpeg_failed`, `render_timeout`, `invalid_output`.
  - Storage, queue and limits: `storage_failure`, `artifact_missing`, `queue_unavailable`, `time_limit`, `internal_error`.

## Storage

Edited shorts are private derived files under `MEDIA_ROOT`:

```
edits/<edit-uuid>/work-<attempt>/captions.ass   this attempt's caption file
edits/<edit-uuid>/work-<attempt>/short.mp4      this attempt's render, being validated
edits/<edit-uuid>/edited.mp4                    the validated short
```

Keys are generated from UUIDs only, and every path goes through `LocalMediaStorage.path_for`, which refuses traversal and symlink escapes. The workspace is removed after success or failure. Nothing under `MEDIA_ROOT` is served statically.

## API

All routes need the session cookie and are scoped to the owner along the chain user → project → video → clip → edit. Anything else is `404`, or `401` without a session. Responses never include storage keys, paths, task ids, worker hosts, caption files or FFmpeg commands.

| Method | Path | Description |
| --- | --- | --- |
| POST | `/projects/{id}/videos/{video_id}/clips/{clip_id}/edits` | Create a variant. The body is described below. `201` returns a new edit. `200` returns the existing edit with the same settings. `409` covers a failed variant (use retry), a clip that is not ready, captions without a completed transcript, and captions without libass. `422` means unknown fields or values. `503` means the queue is down. |
| GET | `…/clips/{clip_id}/edits?offset&limit(1–50)` | The clip's variants, newest first. |
| GET | `…/clips/{clip_id}/edits/{edit_id}` | One variant's state. |
| POST | `…/edits/{edit_id}/retry` | Re-queue a failed or stalled variant. Otherwise, or after the attempt limit, it returns `409`. |
| GET | `/edits/{edit_id}/content` | Inline `video/mp4` with `Accept-Ranges: bytes`. A byte range returns `206` with `Content-Range`, and an unsatisfiable one returns `416`. Returns `404` unless the edit is ready. |
| GET | `/edits/{edit_id}/download` | Sent as an attachment named `that-was-crazy-vertical-3f2c9a1e.mp4`: an ASCII slug of the clip title, `vertical`, and a short id. |

Request body:

```json
{
  "aspect_ratio": "9:16",
  "layout": "blur_background",
  "captions_enabled": true,
  "caption_style": "bold",
  "caption_position": "bottom"
}
```

- `aspect_ratio` defaults to `9:16`, the only value.
- `layout` is required.
- `captions_enabled` must be a real boolean.
- Style and position default to `bold` / `bottom` when captions are on, and are dropped when captions are off.
- Unknown fields, filter strings, font names, paths and URLs are rejected.
- V0.7: `smart_reframe` also needs `reframe_analysis_id` (a completed analysis of this clip, otherwise `409`); `manual_crop` needs `focus_x` and `focus_y` (finite, 0–1, rounded to 3 decimals). Other layouts refuse both.

An edit has these fields: `id`, `clip_id`, `video_id`, `status`, `progress_percent`, `attempt`, `is_stale`, `configuration`, `aspect_ratio`, `layout`, `captions_enabled`, `caption_style`, `caption_position`, `output_width`, `output_height`, `render_profile`, `caption_cue_count`, `duration_seconds`, `width`, `height`, `fps`, `file_size`, `video_codec`, `audio_codec`, `error_code`, `error_message`, `created_at`, `started_at` and `completed_at`.

## Requirements and configuration

The FFmpeg build needs:

- The `libx264` and `aac` encoders.
- **libass**, which provides the `subtitles` filter.
- The `scale`, `crop`, `pad`, `overlay`, `gblur`, `split`, `setsar` and `color` filters.

Builds differ:

- Ubuntu's `ffmpeg` package has all of these.
- Homebrew's default `ffmpeg` has **no libass**. On macOS, install `ffmpeg-full` and point `FFMPEG_PATH` / `FFPROBE_PATH` at `/opt/homebrew/opt/ffmpeg-full/bin/`.

Without libass, uncaptioned shorts still render, and captioned requests are refused.

Install fonts:

- Ubuntu: `fonts-noto-core` and `fontconfig`.
- macOS: `brew install --cask font-noto-sans font-noto-sans-arabic`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAPTION_FONT_FAMILY` | `Noto Sans` | Caption font family (plain name only) |
| `CAPTION_MAX_WORDS` | `7` | Words per cue |
| `CAPTION_MAX_CHARS` | `32` | Characters per cue |
| `CLIP_RENDER_*` | as in V0.5 | Preset, CRF, audio bitrate, timeout, duration tolerance, heartbeat, stale threshold and attempt limit are shared with clip rendering |

## Frontend

The editor is its own page, `/projects/[id]/clips/[clipId]`. It opens from **Create vertical short** on a ready clip, or from **Create short** / **Open editor** under *Generated clips*.

- **Stage.** A 9:16 frame is the focal point, with a **Preview** / **Rendered short** switch.
  - **Preview** plays the generated clip composed for the chosen layout. Center crop fills the frame, blur background uses a blurred copy kept in sync behind the full frame, and fit uses a dark background.
  - The preview caption shows real words from the transcript, styled with each preset's size ratio (corrected for libass's line-height sizing), weight, colour, outline or box, and margins.
  - It is labelled *"Preview only — layout and caption placement are approximate. The rendered MP4 is the final result."*
  - **Rendered short** plays the actual output file from `/edits/{id}/content`.
- **Edit settings.**
  - Layout cards with miniature diagrams.
  - A **Captions** switch.
  - Caption-style cards with typographic samples: Clean, Bold, and Creator (yellow on a box).
  - A visual Top / Center / Bottom position picker.
  - Style and position are disabled while captions are off.
  - All controls are real radio inputs or a `role="switch"`, so arrow keys, focus rings and labels work. The selection is also marked with a check, never by colour alone.
- **Primary action.** **Render short** comes with a subtle summary of the output.
  - While a render runs, the button is replaced by the real Queued, Rendering or Validating state with backend progress, so a second submission is impossible.
  - Settings that were already rendered offer **View this version**.
  - A failed or stalled render shows *"Render failed — We couldn't generate this version of your short."* with **Retry render**. Error codes are explained in creator language, without infrastructure detail.
- **Result.** When the render finishes, the stage switches to the rendered short and shows "Your short is ready.", with **Download short**, **Create another version** and **Back to clip**.
- **Versions.** Every variant is listed by its settings, for example "Blur background · Bold captions · Bottom", never by id. Each shows its status, a real frame thumbnail, **Play** and download. The list polls every 4 s only while something renders.
- **Project page.** *Generated clips* shows each clip's number of shorts. The project's workflow stepper reports **Edit · Done** once a short is ready.

## Testing

All tests use tiny sources generated with FFmpeg at test time, and nothing is committed. Coverage includes:

- **Layouts.** Real frame pixels on red | green | blue sources check each layout: center crop keeps only the centre, and blur background keeps all three thirds over a blurred backdrop. Portrait, square, odd-sized, rotated, variable-frame-rate and no-audio sources are covered too.
- **Captions.**
  - Caption bands change only while a cue is active, at the chosen position, for every preset.
  - French, Arabic and hostile ASS text render without breaking anything.
  - A long URL caption stays inside the frame, and the unsplit control does not.
  - The cue builder handles clip-local timing and segmentation, and is checked for escaping, Unicode and emoji.
- **Pipeline.** Stages, idempotency, attempt fencing and zombie isolation, deleted rows, DB failure after finalize, disk errors, and timeouts.
- **API.** Ownership, deduplication, validation, retry, Range delivery and download names.
- **CI gates.**
  - CI installs `fonts-noto-core` and fails unless FFmpeg has libx264, aac, libass and the layout filters.
  - Fontconfig must resolve Noto Sans and Noto Sans Arabic, and the caption probe must draw text.
  - `REQUIRE_LIBASS=1` makes caption tests fail instead of skipping.
  - The worker smoke requires `peaksift.render_clip_edit` to be registered.
- **No external services.** No API key, Ollama or model download is needed.

## Known limitations (V0.6)

- **Framing.** In V0.6 crops were always centred; V0.7 adds face-following and manual focal-point crops ([smart-reframing.md](smart-reframing.md)). Only 9:16 at 1080 × 1920 is offered.
- **Captions.** Captions are phrase-level, built from segment timestamps with proportional word timing. There are no word-by-word captions, highlighting or animation in `caption_v1`; V0.8 adds word-synced captions ([dynamic-captions.md](dynamic-captions.md)).
- **Fixed options.** There are three fixed presets, three positions and one font family. Custom fonts, brand kits and watermarks are not supported.
- **Scripts.** Emoji are not shown in `caption_v1` captions (V0.8 dynamic captions draw them in monochrome when a font is installed). Other scripts depend on installed fallback fonts. Arabic shaping was verified visually on samples only.
- **Editing scope.** There is no timeline, trim, music, sound effects, B-roll, transitions or publishing.
- **Platform.** Rendering is CPU-only on local filesystem storage. Edit deletion, retention and render cancellation are not supported.
- **Progress.** Progress is stage-based, so very short renders can finish between two polls.

## Using it

1. Upload a video and wait for **Ready**.
2. **Transcribe video**.
3. **Find clip moments** in *AI clip detection*.
4. **Generate clip** on a candidate and wait for **Rendered clip**.
5. Click **Create vertical short** to open the short-form editor.
6. Choose a layout: **Blur background**, **Center crop** or **Fit**.
7. Configure captions: on or off, then a style and a position.
8. Click **Render short** and wait for *Queued → Rendering → Validating*.
9. Preview the result: the editor switches to the rendered 9:16 short.
10. Click **Download short**.
