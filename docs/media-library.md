# The PeakSift starter library

Built 28 November 2026 at the creator's request, after the StreamLadder clip-editor study
([product-research/streamladder-live-benchmark.md](product-research/streamladder-live-benchmark.md):
their editor has sound-effect and music libraries and stickers). PeakSift now ships its own
starter library — only material that may be redistributed inside the app **and** used in
creators' published, commercial videos without a credit they must add.

| What | How many | Source | Licence |
| --- | --- | --- | --- |
| Sound effects: transitions, hits & booms, clicks & pops, alerts, funny, money, stings | 90 | [Kenney](https://kenney.nl) audio packs | CC0 1.0 |
| Music: calm, chill, cinematic, upbeat, energetic, suspense, playful (≤ 3 min, long ones faded) | 13 | Their authors on [OpenGameArt.org](https://opengameart.org) (each page in the manifest) | CC0 1.0 |
| Stickers: emoji reactions (256 px, transparent) | 46 | [Microsoft Fluent Emoji](https://github.com/microsoft/fluentui-emoji) | MIT |
| Animated overlays: confetti, sparkle burst, rising hearts, fire, explosion, speed lines, flash, smoke puff, magic swirl, twinkling stars | 10 | Made by PeakSift (`scripts/build_overlays.py`) from [Kenney's Particle Pack](https://kenney.nl/assets/particle-pack) and drawn shapes | CC0 1.0 |

Rejected sources and why are in the benchmark (YouTube Audio Library, Pixabay, Mixkit, Pexels,
ZapSplat, Sonniss, BBC, Freesound non-commercial, Kevin MacLeod / CC-BY, Twemoji, OpenMoji,
meme sounds such as the "Vine boom" or "bruh", anything from YouTube, Tenor or Giphy).

## How it is built and installed

1. Maintainers download the packs from their own pages (Kenney, OpenGameArt, the Fluent Emoji
   repository at a pinned commit) and run `backend/scripts/build_library_release.py`: it picks the
   set, converts sounds to Ogg Vorbis (nothing else changes), writes `manifest.json` (each file's
   sha256, licence, source page and credit) and the licence files, and packs an archive.
2. The archive is published as the GitHub release
   [`library-v1`](https://github.com/angorot89/PeakSift-AI/releases/tag/library-v1). Its manifest is
   committed as `backend/app/services/library_manifest.json`; the media never is.
3. Servers install it with `python scripts/fetch_library.py` (into `LIBRARY_DIR`, git-ignored): the
   archive must match its pinned sha256, only the listed regular files are extracted (no links, no
   paths outside the target), each must match its own sha256, and the manifest must equal the
   committed one before anything replaces an installed library. The production image does this at
   build time (`/app/library`). The app itself never downloads anything.

## Animated overlays (library v2)

`scripts/build_overlays.py` draws each effect frame by frame with Pillow (fixed seeds, so the
output is reproducible) from the particle sprites — tinted, or filled solid through their own
alpha for flames — and plain shapes (confetti, hearts, speed lines), then encodes **VP9 with an
alpha channel** in WebM (720 × 1280, 30 fps, 0.6–3 s, 22 MB for the whole library). Item ids
start with `fx-`.

The visuals pipeline gained **transparent videos**: a VP8/VP9 WebM whose stream carries the
`ALPHA_MODE` tag is recorded with `has_alpha` (a migration allows it for VP8/VP9 only); the render
decodes it with libvpx (FFmpeg's own VP9 decoder drops alpha); such a video may be an **overlay**
(any other video still may not), and overlays have a new size, **Full** — the whole frame,
centred (`VisualSize.FULL`, overlays only; snapshot and fingerprints change only when used). In
the editor, the Visuals panel's library has an **Animated** tab (looping previews); adding an
effect places it at the playhead, full frame, for its whole length. Chrome-based browsers show
the transparency in the preview; the render is authoritative everywhere.

## Using it

`GET /library` is the catalogue (titles, categories, durations, licence, credit — never paths or
digests) and whether this server has it installed. `GET /library/{id}/content` serves a verified
file to signed-in users (previews). `POST /projects/{project_id}/library/{id}` **imports** the item
into the project through the very same validation as an upload (`store_audio_upload` /
`store_visual_upload`: probing, limits, re-encoding, de-duplication) and labels it with its origin —
CC0, or licensed with its licence and source written down. From then on it is an ordinary project
asset: ownership checks, the editor, the mix and the render are unchanged. The same item again
returns the existing asset.

In the editor, the **Sound** panel's *PeakSift library* has Sound effects and Music (search,
categories, listen, **Add** / **Use**): music becomes the Short's music, a sound effect lands at the
playhead. The **Visuals** panel's library shows the stickers; adding one places it as an overlay at
the playhead. *Sources & licences* lists the sources and the MIT notice.

## Checked

- `tests/test_media_library.py`: the real catalogue (counts, licences, lengths, unique ids), labels,
  a tampered file never used, the installer (pinned digest, path traversal ignored, per-file
  digests), browsing without installation (no paths), previews only when installed, imports as
  labelled audio and visual assets (again = same asset), owner scoping, a missing file (409).
- Build checks: no silent file, every effect ≤ 30 s, stickers transparent at 256 px (the Kenney
  speech bubbles were left out: 32 px is too small for 1080 × 1920).
- Overlays: `tests/test_visual_render.py` (a transparent WebM is probed as such; a full-frame
  overlay renders with its transparency, decoded by libvpx; only overlays may fill the frame),
  the library import of an overlay as a transparent video, `visual-elements.test.ts`. Real
  browser: Confetti from the Animated tab → Overlay · Full · 5.0–8.0 s → a real render with the
  confetti over the clip and the captions on top.
- Real browser on a local test stack: search "whoosh" → add → a cue at the playhead; "8-bit
  Bossa" → the Short's music; Fire sticker → an overlay; a real render with all three (sticker
  transparent on top, mix at −14.2 LUFS), each asset labelled with its licence.

## Limitations

- A starter set, not a stock library: no internet search, no uploads by other creators.
- Two insets (overlays or picture-in-picture) still cannot overlap, so a sticker and an effect
  play one after the other.
- Safari's preview may show an effect's transparent areas as black (it lacks VP9 alpha); the
  rendered Short is correct.
- Music is game-music flavoured (what CC0 offers); creators can still upload what they own.
