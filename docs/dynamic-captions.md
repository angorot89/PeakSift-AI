# Dynamic captions (Milestone 8)

Word-synced creator captions for vertical shorts: the spoken word is emphasised as it is said,
in one of four creator presets, kept inside a social-platform safe area, with an optional
opening hook. Word timing is generated from the clip's own audio by a local speech model.

## What it does, and does not do

- **Does:** time every word of a ready clip with faster-whisper word timestamps (a background
  job); group words into short, readable cues; render them with libass, highlighting the
  active word; four presets (Focus, Punch, Minimal, Boxed); Top / Center / Bottom placement
  inside the General Social safe area; an opening hook (1–60 characters, 0.5–5 s); a live
  editor preview drawn from the renderer's own cues; French, Arabic (right to left) and mixed
  scripts; monochrome emoji when a font for them is installed.
- **Does not:** promise perfect speech synchronization — word timing is as good as the speech
  recognizer's word timestamps; edit word timing by hand (no keyframe or timeline editor);
  position words individually; accept custom fonts, ASS markup, FFmpeg filters or arbitrary
  animations; add music, sound effects, B-roll or publishing.
- **Phrase timed** captions (the fallback) follow transcript phrases and never emphasise single
  words. They are never described as word-synced.

## Architecture

```
ready clip ─► POST caption-tracks ─► Celery peaksift.generate_caption_track (ids only)
               │                       ├─ decode the clip's audio (16 kHz mono PCM, no temp file)
               │                       ├─ faster-whisper transcribe(word_timestamps=True)
               │                       ├─ validate_words (refuse / drop / clamp, see below)
               │                       └─ one transaction: caption_words + track completed
               ▼
edit with caption_v2 ─► dynamic_text.dynamic_cues (track words, re-validated)
                         ├─ dynamic_cues.build_word_cues (grouping, lines, active word)
                         ├─ caption_v2.build_dynamic_ass (+ hook events, emoji policy)
                         └─ compose_short (layout / smart crop → 1080 × 1920 → libass)
```

| Module | Role |
| --- | --- |
| `app/models/caption_track.py` | `CaptionTrack`, `CaptionWord`, statuses |
| `app/services/caption_timing/` | config snapshot, provider contract, faster-whisper provider, pipeline |
| `app/workers/caption_tasks.py` | `peaksift.generate_caption_track` |
| `app/api/caption_tracks.py` | track API, timing options, caption preview |
| `app/api/caption_styles.py` | `/caption-styles`: the renderer's numbers for the preview |
| `app/services/clip_edit/dynamic_cues.py` | cue grouping, line layout, active-word timing (pure) |
| `app/services/clip_edit/caption_v2.py` | presets and the dynamic ASS document |
| `app/services/clip_edit/caption_metrics.py` | Noto Sans advance widths measured with libass |
| `app/services/clip_edit/safe_area.py` | General Social safe area and placements |
| `app/services/clip_edit/hook.py` | hook validation, line layout and ASS |
| `app/services/clip_edit/emoji.py` | emoji detection, emoji font probe and policy |
| `app/services/clip_edit/dynamic_text.py` | cues for the render and the preview (shared) |

## CaptionTrack and CaptionWord

A `CaptionTrack` is the word timing of one clip under one server configuration:

- `config_snapshot` (`caption_alignment_v1`: provider, model, compute type, beam size,
  language hint) and its fingerprint — unique per clip, so a repeated request returns the same
  track and a configuration change creates a new one;
- status `queued → preparing_audio → aligning → validating → completed | failed`, progress
  5 / 10 / 20 / 85 / 100, attempt number, heartbeat and stale detection, safe `error_code` /
  `error_message`;
- `language`, `word_count`, `rejected_word_count`, `average_confidence`.

A track is always real provider word timing (`timing_mode: "aligned_word"` in the API).
Proportional or generated timing is never stored or labelled as aligned. Phrase timing is
an edit-level choice, not a track.

`CaptionWord` rows hold clip-local `start_time` / `end_time`, the exact recognized `text`
(never paraphrased) and the provider's confidence, ordered by `sequence_index`.

## Timing provider

`CaptionTimingProvider` (contract in `caption_timing/contract.py`) returns `TimedWord`s or
raises `TimingUnavailable` / `TimingOutputError`. The default provider runs faster-whisper with
`word_timestamps=True`, reusing the `FASTER_WHISPER_*` model settings so captions and
transcripts share one lazily loaded model; it is never loaded at import, at API startup or in
normal tests. Provider SDK objects never leave the provider module, and persistence does not
depend on faster-whisper classes. A provider without word timestamps is refused.

The transcript's detected language is passed as a hint when it is known.

### Validation (`validate_words`)

- **Refuse the whole result:** NaN or infinite times, a start before −0.01 s, starts out of
  order, or a word ending past the audio plus `CAPTION_TIMING_TOLERANCE_SECONDS` (0.25 s).
- **Drop and count** (`rejected_word_count`): words shorter than 0.02 s, empty text, text over
  128 characters, duplicate starts.
- **Clamp** small irregularities: a word overlapping the next ends where the next starts; an
  end within the tolerance is clamped to the audio duration.

Persisted words are validated again before every render or preview.

A clip without an audio stream has no speech: its track completes honestly with zero words,
and the editor says "No spoken words found".

## Cue grouping and the active word

`build_word_cues` (pure and deterministic; no LLM, no paraphrase):

- a cue closes at sentence or clause punctuation once it has at least two words **and** has been
  on screen for `min_duration` (0.7 s) — so fast speech does not flash cues; at a pause of
  0.45 s or more; or when the next word would exceed 7 words, two lines of the preset's width,
  or 3.2 s;
- a lone trailing word joins the previous cue, or takes its last word with it (no orphans);
- lines are balanced across at most two lines, preferring a break after punctuation; line
  widths use Noto Sans advance widths measured with libass, so lines never overflow;
- a token too long for a line is split on grapheme boundaries; its pieces share the word's real
  interval and always stay in one cue;
- the active word is active from its start until the next word starts (gaps up to 0.35 s are
  bridged); the last word stays active until the cue ends; cues are held 0.25 s after the last
  word when there is room and last at least 0.7 s when possible; cues never overlap and never
  leave the clip.

## Renderers: caption_v1 and caption_v2

Edits record their renderer, and old edits keep their behaviour:

| | `caption_v1` (V0.6) | `caption_v2` (V0.8) |
| --- | --- | --- |
| Styles | Clean, Bold, Creator | Focus, Punch, Minimal, Boxed |
| Timing | transcript phrases | word timing (`aligned_word`) or phrases (`phrase_fallback`) |
| Emphasis | none | the active word |
| Emoji | removed | monochrome, or removed (see below) |

caption_v2 writes one `Dialogue` event per active-word interval, back to back, each holding the
whole cue with the active word recoloured (`\1c`). The words never move while the emphasis
moves (no per-word scaling, no karaoke `\k`, which would leave earlier words highlighted).
Each cue enters with a short fade and grow; every event continues that entrance, so a very
short first word does not make the text pop.

### Presets

| Preset | Size | Weight | Text | Active word | Outline / box |
| --- | --- | --- | --- | --- | --- |
| Focus | 112 | bold | white | yellow `#FFD43B` | dark outline |
| Punch | 120 | bold, uppercase | white | green `#7CFC5A` | dark outline |
| Minimal | 78 | regular | grey `#9DA5B0` | white | thin outline |
| Boxed | 100 | bold | white | yellow | dark box |

Sizes are libass font sizes on the 1080 × 1920 canvas. libass sizes Noto Sans by its OS/2
Windows metrics (one em ≈ 0.66 × the size); the editor preview uses the same ratio.

## Safe area

General Social Safe Area v1 (`general_social_v1`): 10 % top, 22 % bottom, 9 % left and right
of the 1080 × 1920 frame (192 / 422 / 97 px), where platform buttons and captions usually sit.
Top, Center and Bottom place captions inside it (bottom = 422 px above the frame edge). It is
a general guide, not any one platform's exact layout. The editor can show it as a dashed,
labelled outline.

## Hook overlay

An optional opening line: 1–60 characters after whitespace normalization, laid out in 1–3
balanced lines (refused when it cannot fit), shown from 0 s for 0.5–5 s (default 2 s) with a
150 ms fade in and 200 ms fade out. Styles: Headline (96, bold white), Boxed (84, dark text on
a yellow box), Minimal (72). Positions: Top or Center, inside the safe area; the hook and the
captions cannot share a position. The text is shown exactly as typed (escaped, never markup).

## Multilingual text and emoji

- Text is kept as recognized, escaped for ASS (`{`, `}` and `\` are made inert).
- Right-to-left scripts: styles use `Encoding -1` so libass shapes Arabic and mixed RTL/LTR
  lines with the Unicode bidi algorithm; the word order does not change with the highlight.
- Noto Sans covers Latin, Greek and Cyrillic; Arabic falls back to Noto Sans Arabic through
  fontconfig. Arabic typography has had limited QA.
- **Emoji:** libass cannot draw colour emoji. At render time a probe looks for a monochrome
  emoji font libass can draw ("Noto Emoji", then "Symbola"); emoji are drawn with it, or left
  out of the burned-in text when none renders. `/caption-styles` reports `emoji:
  "monochrome" | "omitted"` so the editor can say so. Skin-tone modifiers are not drawn by the
  monochrome fonts.

## Font requirements

Install from the system or distribution (OFL), never commit font files:

- **Noto Sans** (caption font, `CAPTION_FONT_FAMILY`),
- **Noto Sans Arabic** (fallback for Arabic),
- a monochrome emoji font: **Symbola** (`fonts-symbola`) or **Noto Emoji**.

On Debian/Ubuntu: `apt install fontconfig fonts-noto-core fonts-symbola`. On macOS with
Homebrew: `brew install --cask font-noto-sans font-noto-sans-arabic font-noto-emoji`.
`python scripts/caption_font_probe.py` checks that each family resolves by name and really
draws through libass.

## Editor workflow

The short-form editor (`components/app/short-editor-view.tsx`):

- **Caption timing:** "Word synced" / "Phrase timed". The state is written as text —
  "Word synced · 59 words timed from the clip's audio", the current stage while timing runs,
  or a plain-language error with Retry and "Use phrase timing instead".
- **Caption style:** four preset cards with live samples; **Caption position** (the position
  taken by the hook is disabled and explained).
- **Opening hook:** switch, text with a 60-character counter (prefilled from the candidate's
  hook or title), style, position and duration.
- **Preview:** `CaptionLayer` draws the cues returned by the caption-preview endpoint — built by
  the same code as the render — in output-frame units over the playing video, following its
  clock (`requestVideoFrameCallback`), including the Smart Reframe preview. It re-renders only
  when the visible cue or active word changes. The entrance animation is disabled under
  `prefers-reduced-motion`. Sizes are close to the render, not pixel-exact; the rendered MP4 is
  the final result.
- **Safe area** checkbox shows the labelled guide.

## Render pipeline

An edit with a dynamic preset stores `caption_renderer = caption_v2`, `caption_timing` and, for
word timing, `caption_track_id`; the edit's config snapshot (and fingerprint) includes the
renderer, timing, safe-area version and track id, plus the hook when it is on. The worker
builds cues with `dynamic_text.dynamic_cues` (the track must belong to the clip and be
completed; its words are re-validated), writes the ASS document into the attempt's workspace,
and renders through the same `compose_short` path as V0.6/V0.7 (layout or smart crop first,
then 1080 × 1920, then captions fixed on screen). V0.6 fingerprints are unchanged.

## API

All under `/projects/{project_id}/videos/{video_id}/clips/{clip_id}`; owner-scoped (other users
get 404, anonymous requests 401).

| Method | Path | |
| --- | --- | --- |
| `POST` | `/caption-tracks` | start word timing (idempotent per configuration) |
| `GET` | `/caption-tracks` | list tracks |
| `GET` | `/caption-tracks/current` | the current configuration's track |
| `GET` | `/caption-tracks/{id}` | status (poll) |
| `GET` | `/caption-tracks/{id}/words` | words of a completed track, in order |
| `POST` | `/caption-tracks/{id}/retry` | retry a failed or stalled track (new attempt) |
| `GET` | `/caption-timing` | word timing state and whether phrase timing is available |
| `GET` | `/caption-preview?style=&position=&timing=&track_id=` | the renderer's cues for the preview (409 when they cannot be built yet) |

`GET /caption-styles` (authenticated) returns the presets, placements, safe area, hook limits,
font ratio and emoji policy. Edit requests (`POST …/edits`) accept `caption_style` (a V0.6
style or a dynamic preset), `caption_position`, `caption_timing`, `caption_track_id` and
`hook_enabled`, `hook_text`, `hook_style`, `hook_position`, `hook_duration_seconds`.

Responses never contain task ids, fingerprints, file paths, model locations (a configured model
directory is shown as `custom`), temporary audio or ASS files, FFmpeg commands or credentials.

## Retry and failure

Failures are stored with a safe code and plain message, e.g. `clip_missing`, `clip_not_ready`,
`audio_decode_failed`, `provider_capability`, `timing_output_invalid`, `time_limit`,
`queue_unavailable`, `internal_error`. The editor maps them to plain language and offers
Retry (up to `CAPTION_TIMING_MAX_ATTEMPTS`, default 5) or phrase timing. A track whose worker
stops reporting for `CAPTION_TIMING_STALE_AFTER_SECONDS` (15 min) is shown as stalled and can
be retried. Attempts are fenced by their task id: a superseded worker can never overwrite a
newer attempt. An edit whose track is no longer usable fails with
`caption_track_unavailable`.

## Security

- Celery tasks receive database ids only.
- Transcript and hook text reach captions only through the ASS escapers; options are
  allow-listed enums (no user ASS, fonts, filters or paths).
- Every route checks ownership; another user's clip or track is 404.
- Model weights are never committed or downloaded in CI; error messages never include paths
  or internals.

## Testing

- Mocked timed-word output for provider, pipeline and API tests (no model, network or API key);
  an opt-in real faster-whisper test (`PEAKSIFT_REAL_WHISPER=1` on macOS; needs the `tiny`
  model and `say`).
- Pure tests for validation, cue grouping, line layout, hook layout and emoji splitting.
- Real libass frame tests: the active word moves left to right for every preset, lines stay
  inside the margins, the entrance continues across a short first word, French / Arabic /
  mixed-script and emoji rendering, safe-area placement, 8 end-to-end dynamic edit renders.
- CI probes: `scripts/caption_font_probe.py` and `scripts/dynamic_caption_probe.py`.
- Frontend unit tests for the preview's cue and active-word lookup (`npm test`).

## Using it

1. Generate a clip from a candidate.
2. Open the short-form editor.
3. Turn on **Captions**.
4. Choose **Word synced** and **Generate word sync**; watch the stage and progress.
5. Pick a caption style (Focus, Punch, Minimal or Boxed).
6. Pick a position (Top, Center or Bottom).
7. Optionally turn on the **Opening hook** and edit its text, style, position and duration.
8. Select a layout, or Smart reframe.
9. Preview: play the clip and watch the active word; turn on **Safe area** to check placement.
10. **Render short**.
11. Play and **Download** the MP4.

## Known limitations (V0.8)

- Word timing depends on the speech recognizer's accuracy; it is word-timed, not phoneme
  aligned, and can lead or lag slightly on fast or noisy speech.
- No manual word timing editor or timeline; no per-word positioning.
- No custom fonts, arbitrary animations or brand kits.
- Emoji are monochrome (or omitted); skin tones are not shown; caption_v1 removes emoji.
- Arabic and other right-to-left typography has had limited QA.
- The default model runs locally on the CPU; long clips take time.
- Media is on the local filesystem (development storage).
- No music, sound effects, B-roll or publishing.
