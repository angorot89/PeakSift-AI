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
- Real browser on a local test stack: search "whoosh" → add → a cue at the playhead; "8-bit
  Bossa" → the Short's music; Fire sticker → an overlay; a real render with all three (sticker
  transparent on top, mix at −14.2 LUFS), each asset labelled with its licence.

## Limitations

- A starter set, not a stock library: no internet search, no uploads by other creators.
- No animated overlays yet (fire, confetti, flash as video with transparency); the Kenney
  Particle Pack (CC0) is the planned source.
- Music is game-music flavoured (what CC0 offers); creators can still upload what they own.
