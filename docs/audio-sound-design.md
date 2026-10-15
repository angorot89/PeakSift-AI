# Audio & sound design (Milestone 9)

Shorts can be finished with their own audio levels, background music, timed sound effects,
automatic music ducking and final loudness normalization — without leaving PeakSift. Speech
comes first: the defaults are conservative, and music dips while the clip's own audio plays.

## What it does, and does not do

- **Does:** private, project-scoped uploads of music and sound effects (MP3, WAV, M4A, AAC,
  OGG, Opus), validated by their contents; compact waveforms; music with a start point, loop to
  fit, fades and volume; automatic ducking (Light / Medium / Strong); up to 12 sound-effect
  cues; a peak safety limiter and optional loudness normalization to PeakSift's −14 LUFS
  target; an Audio section in the editor with a lightweight timeline and an approximate
  browser preview; the final mix rendered into the short with any layout, Smart Reframe,
  captions and hook.
- **Does not:** provide a music or effect library, search or download audio from the
  internet, generate music or effects, separate vocals or stems, offer a multitrack timeline,
  automation curves, EQ, compressor or limiter controls, beat detection or beat-synced cuts,
  pitch or tempo changes, or publishing. Ducking reacts to the clip's overall audio energy —
  it is **not** voice isolation.

## Rights

PeakSift does not grant rights to uploaded music or sound effects. Creators upload audio they
own or have permission to use; the editor says so next to the Audio controls. PeakSift ships
no audio library, and tests use generated signals only.

## Architecture

```
upload ─► AudioAsset (validated, waveform)            edit request {audio: {...}}
                  │                                            │
                  └────────────── referenced by id ────────────┤
                                                               ▼
              EditConfig.audio (AudioMix, audio_mix_v1) ─► fingerprint / snapshot
                                                               │  Celery: run_clip_edit
                                                               ▼
   re-check assets ─► mix plan (FFmpeg) ─► mix WAV ─► limiter + loudnorm ─► final WAV
                                                               │
         layout / smart crop ─► captions + hook ─► H.264  +  AAC from the final WAV ─► MP4
                                                               │
                         validate (stereo 48 kHz, length) ─► measure loudness ─► ready
```

| Module | Role |
| --- | --- |
| `app/models/audio_asset.py` | `AudioAsset` (music / sfx), table `audio_assets` |
| `app/services/audio_assets.py` | upload validation, ffprobe checks, hashing, waveform peaks |
| `app/api/audio_assets.py` | upload, list, metadata, waveform, preview stream, limits |
| `app/services/audio_mix/config.py` | `AudioMix` — the edit's audio section (validated, normalized) |
| `app/services/audio_mix/plan.py` | the FFmpeg plan: inputs and filtergraph from validated numbers |
| `app/services/audio_mix/ducking.py` | ducking presets → `sidechaincompress` constants |
| `app/services/audio_mix/loudness.py` | safety limiter, two-pass `loudnorm`, report parsing |
| `app/services/audio_mix/mixer.py` | `render_mix`, `prepare_track` (in the attempt's workspace) |
| `app/services/clip_edit/pipeline.py` | `_prepare_audio`, `_check_final_audio` |
| `frontend/components/app/editor/audio-panel.tsx`, `audio-timeline.tsx` | the Audio section |
| `frontend/lib/audio-mix.ts`, `use-audio-preview.ts`, `audio.ts` | rules, preview, API |

## Audio assets

`AudioAsset` belongs to a project (User → Project → AudioAsset), so a track can be reused
across the project's clips. Fields: `kind` (`music` | `sfx`), sanitized `display_name`
(metadata only), generated `storage_key` (`audio/<uuid>.<ext>`), canonical `content_type`,
`file_size`, `sha256`, and the probed `container`, `codec`, `duration_seconds`,
`sample_rate`, `channels`, plus `waveform_peaks`. A row exists only for a validated upload;
assets are never modified, and edits reference them by id.

**Accepted uploads.** `.mp3 .wav .m4a .aac .ogg .opus`; a declared MIME type must match the
extension. The contents are probed with ffprobe — the extension is not trusted: the container
must match the extension, there must be an audio stream with a supported codec (mp3, aac,
alac, vorbis, opus, flac or linear PCM) and a positive duration, and a real video stream is
refused (embedded cover art is allowed). Any refusal removes the stored file; nothing corrupt
is kept.

**Limits** (server configuration, published to the editor by `GET /audio-upload-limits`):

| Setting | Default |
| --- | --- |
| `AUDIO_UPLOAD_MAX_BYTES` | 100 MiB (an announced oversize body is refused unread) |
| `AUDIO_UPLOAD_MAX_DURATION_SECONDS` | 1200 (20 minutes, music) |
| `AUDIO_SFX_MAX_DURATION_SECONDS` | 30 |

**Duplicates.** The upload is hashed while it is stored; the same file uploaded again for the
same purpose in the same project returns the existing asset (`200`). Other projects never
collide or learn about each other's files.

**Waveform.** FFmpeg decodes the file to 8 kHz mono through a pipe, and samples are folded into
20 buckets per second, between 200 and 1000 buckets, as they stream in. Each value is the peak
amplitude in that bucket, 0–100 % of full scale (integers). PCM is never stored or returned;
a watchdog stops a stuck decoder. It is a navigation aid, not a measurement.

## The edit's audio section

`EditConfig.audio` (`AudioMix`, snapshot `audio_mix_v1`). Levels are in dB — the canonical
unit — and times are seconds of the edited short (clip-local time).

| Setting | Range | Default |
| --- | --- | --- |
| `source_gain_db` (the clip's own audio) | −24 to +6 | 0 |
| `normalize` (final loudness) | on / off | on |
| `music.asset_id` | a `music` asset of the clip's project | — |
| `music.gain_db` | −40 to 0 | −16 |
| `music.source_start_seconds` | 0 to the track's end | 0 |
| `music.loop` | on / off | on |
| `music.fade_in_seconds` / `fade_out_seconds` | 0–10 | 0.5 / 1.0 |
| `music.ducking` | `off` / `light` / `medium` / `strong` | `medium` |
| `sfx[]` (≤ 12): `asset_id`, `at_seconds`, `gain_db` | an `sfx` asset; 0 to the clip's end; −30 to +6 | gain −6 |

Values are finite, bounded and rounded (0.1 dB, 10 ms); cues are ordered by time. Every audio
choice changes the edit's fingerprint, equivalent settings share it, and the exact asset ids
are stored — an edit is never switched to another asset. A section that changes nothing (no
music, no effects, original level, normalization off) is no section; the editor sends a
section only once music, effects or a level change are chosen, so **edits without audio
render exactly as before** (no mixing, no normalization) and keep their fingerprints.

The API checks the referenced assets (this project, the right kind — another project's asset
is indistinguishable from a missing one), that the music starts inside its track and that
every effect starts within the clip. The render pipeline checks the assets again.

## The mix

One FFmpeg run (`plan.build_mix_command`) writes the short's mix as a 48 kHz stereo float WAV.
The filtergraph contains only constants, allow-listed presets and fixed-precision finite
numbers; files are inputs, never text inside the graph, and asset ids never reach FFmpeg.

- **Bed and duration.** Everything is mixed (`amix=duration=first:normalize=0`) onto silence of
  exactly the short's duration: **the video's duration is authoritative**; music can never
  lengthen or shorten a short.
- **Source.** The clip's audio at `source_gain_db`, in the 48 kHz stereo working format (mono
  is duplicated to both channels).
- **Music.** Playback starts at `source_start_seconds` (e.g. a 180 s track started at 42 s
  under a 25 s short plays 42–67 s). When the rest of the track is shorter than the short and
  looping is on, an endlessly looping copy of the track (from its beginning) follows, then
  everything is trimmed exactly; without looping the music simply ends. Fades apply to the
  music that actually plays — clamped and scaled so they never exceed it; the fade-out ends
  where the music ends. Then the gain.
- **Sound effects.** Each cue plays its file from the start at its gain, delayed to its time in
  the short, trimmed so it never runs past the end; a cue at or after the end is left out.
  Effects are not ducked and do not duck the music.

### Automatic ducking

When there is source audio and music with ducking on, the source (after its gain) is the
control signal of `sidechaincompress` on the music: the music dips while the clip's audio is
active and recovers when it goes quiet. Users choose a strength; the parameters are server
constants, tuned by measurement (RMS detection, no make-up gain):

| Strength | Threshold | Ratio | Attack | Release | Dip with a −12 dBFS speech proxy |
| --- | --- | --- | --- | --- | --- |
| light | 0.05 | 2 | 20 ms | 400 ms | about 7 dB |
| medium | 0.03 | 4 | 20 ms | 500 ms | about 13 dB |
| strong | 0.02 | 8 | 20 ms | 600 ms | about 19 dB |

The release keeps the music steady between syllables (no flutter: ≤ 0.8 dB spread in 50 ms
windows during syllabic speech) and recovers within about a second. **Limitation:** ducking
follows the clip's overall audio energy — background noise or music in the clip also ducks,
and a quiet speaker ducks less. There is no voice isolation. Without source audio, or when no
music plays, nothing is ducked.

### Loudness

Profile `social_v1` — PeakSift's own target for shorts, not a promise of how any platform
normalizes playback:

- **Always:** a peak safety limiter at −1 dBFS (`alimiter`, acting only above that), so a hot
  mix can never clip, and one loud transient cannot dominate the measurement.
- **Normalize on (default):** two-pass `loudnorm` to **−14 LUFS integrated, true peak ≤ −1.5
  dBTP**, with a permissive 20 LU loudness-range target so speech keeps its dynamics under one
  linear gain. The analysis report is parsed defensively (bounded, finite numbers only);
  values are clamped into the ranges `loudnorm` accepts; a silent mix is not normalized (no
  NaN). Any failure is a safe `loudness_failed`.
- **Normalize off:** only the safety limiter.

### In the render pipeline

For an edit with an audio section, `run_clip_edit` probes the source clip, re-checks the
assets (`audio_asset_unavailable` otherwise), builds the plan, mixes and finishes the track in
**the attempt's workspace**, and composes the short with that track muxed as AAC (at
`CLIP_AUDIO_BITRATE`, 128 kbit/s by default) in place of the clip's own audio stream. A silent clip
with nothing to hear keeps no audio stream, as before. After rendering, the short's audio
must be **stereo, 48 kHz and as long as the video** (`invalid_output` otherwise); its
integrated loudness and true peak are measured and recorded on the edit
(`audio_loudness_lufs`, `audio_true_peak_dbtp`), and a result above 0 dBTP is refused
(`audio_clipped`).

Attempt ownership is the existing fencing: a superseded attempt writes nothing and removes only
its own workspace (temporary audio included); success and terminal failure remove the
workspace. A worker that crashes leaves its attempt's workspace until the retry, which starts
from a fresh one.

## Editor

The Audio section follows the hook in the settings panel (Preview → Layout → Captions → Hook →
**Audio** → Render):

- the rights notice; **Original audio** (dB);
- **Background music**: *No music* or a project track (name, duration, small waveform,
  **Listen**), **Upload music**; then **Music volume**, **Start from** (with a waveform marker
  and "Plays 0:04.0–0:21.1 of the track"), **Loop to fit**, **Fade in/out**, and **Automatic
  ducking** with Light / Medium / Strong — its state is written as text;
- **Sound effects**: numbered cues (effect, time, volume, remove), **Add sound effect** (at the
  preview's current time), **Upload sound effect**;
- an **Audio timeline** strip: the music actually heard (through start point and loops), the
  playhead and numbered effect markers. The strip and each marker are sliders: click or arrow
  keys seek; drag a marker with a pointer or move it with the arrow keys (±0.1 s, Shift ±1 s) —
  dragging is never required;
- **Normalize final mix**.

### Preview

The browser preview plays the music and effects with the preview video, which is the **master
clock**: the music follows `video.currentTime` (re-seeked only when it drifts more than
0.25 s), loops and fades as the render does, and pauses with the video; effects fire only
when forward playback crosses their time (a seek never fires them — it re-arms them); pause,
the end, unmount, navigation and logout stop everything; listening to an asset pauses the
video and playing the video stops the listener. In background tabs `timeupdate` keeps it in
step at a coarser rate.

**Limits:** ducking and loudness normalization are not imitated, and boosts above the
original level are not heard (browsers cannot play louder than the source). The rendered MP4
is the final result; the editor says so.

## API

| Method | Path | |
| --- | --- | --- |
| `POST` | `/projects/{id}/audio-assets` | multipart `file` + `kind` (`music`/`sfx`); `201` new, `200` existing duplicate |
| `GET` | `/projects/{id}/audio-assets[?kind=]` | the project's audio, newest first |
| `GET` | `/projects/{id}/audio-assets/{asset_id}` | metadata (no keys, paths or hashes) |
| `GET` | `/projects/{id}/audio-assets/{asset_id}/waveform` | `{buckets, peaks}` |
| `GET` | `/projects/{id}/audio-assets/{asset_id}/content` | owner-only stream, HTTP Range, `private, no-store` |
| `GET` | `/audio-upload-limits` | size and duration limits, accepted extensions |

Edits accept `audio: {source_gain_db, normalize, music: {asset_id, gain_db,
source_start_seconds, loop, fade_in_seconds, fade_out_seconds, ducking}, sfx: [{asset_id,
at_seconds, gain_db}]}`; unknown fields are refused. Another user gets `404`, anonymous
requests `401`.

## Security

- Uploads are validated by content; names are display metadata; storage keys are generated
  and resolved only through `LocalMediaStorage.path_for` (symlinks that leave the media root
  are refused).
- No user string reaches FFmpeg: only allow-listed presets and validated numbers, with files
  as inputs; commands are argument lists with timeouts. FFmpeg errors are logged with every
  path redacted and never shown.
- Responses and error messages contain no paths, storage keys, hashes, task ids or commands.
- Asset references are checked for project ownership and kind at the API and again at render;
  knowing an asset's id is not enough.

## Testing

- Real-FFmpeg tests measuring rendered audio: music start/loop/fades/gain, ducking per preset
  (dip, recovery, no flutter), effect onsets (±2 ms), loudness (quiet, clipping, silent,
  dynamics preserved, normalize off), end-to-end edits (including Smart Reframe + captions +
  hook + music + effects), hardening (symlinks, degenerate uploads, unusual sample rates,
  clipping and output validation, log redaction).
- Upload and API tests for formats, refusals, limits, duplicates, names, ownership and Range.
- Frontend unit tests for normalization, timing rules and cue crossing; browser tests on the
  real stack for the Audio section and preview synchronization.
- CI probe `scripts/audio_mix_probe.py` (matrix, ducking, loudness, full short).

## Using it

1. Open a generated clip in the editor.
2. Configure the layout (or Smart reframe).
3. Configure captions.
4. Add a hook if you like.
5. Open **Audio**.
6. Upload or select music.
7. Adjust **Music volume**.
8. Keep **Automatic ducking** on (or choose its strength).
9. Set **Start from**, **Loop to fit** and the fades.
10. Add sound effects and place them (time field, or drag/arrow-key the markers).
11. Play the preview.
12. **Render short**.
13. Download the MP4.

## Known limitations (V0.9)

- Ducking follows the clip's overall audio energy, not an isolated voice; no stem separation.
- No waveform zoom, multitrack timeline, automation curves, EQ, compressor or limiter controls,
  beat detection, pitch or tempo changes.
- No music or effect library; audio is user-supplied.
- The browser preview does not imitate ducking or loudness, and cannot play boosts.
- Processing is on the CPU; media is on the local filesystem; renders cannot be cancelled.
- No publishing.
