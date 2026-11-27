# Creator caption styles

Built 28 November 2026 at the creator's request, after the StreamLadder clip-editor study
([product-research/streamladder-live-benchmark.md](product-research/streamladder-live-benchmark.md):
about 40 caption styles and a style designer). PeakSift goes from 4 dynamic caption presets to
14, in its own words and looks. Every style is still a **preset**: creators pick a name, never a
font, colour, size or ASS syntax.

| Style | Font | How the spoken word stands out |
| --- | --- | --- |
| Focus · Punch · Minimal · Boxed | Noto Sans (server font) | colour — unchanged, exactly as before |
| Pop | Anton, uppercase | yellow, grows to 116 % as it is spoken |
| Comic | Bangers, uppercase | pink, grows to 110 % |
| Bubble | Luckiest Guy, thick violet outline | yellow |
| One word | Anton, very large | one word at a time (single-word cues) — needs word sync |
| Neon | Titan One, soft pink glow (`\blur`) | pink |
| Underline | Noto Sans bold | yellow and underlined |
| Reveal | Noto Sans bold | words appear as they are spoken (unspoken words transparent, so nothing moves) — needs word sync |
| Headline | Bebas Neue, uppercase, soft shadow | orange |
| Marker | Noto Sans bold | a thick violet marker outline behind the word |
| Bold Arabic | Lalezar (Arabic and Latin) | yellow |

## Fonts

Six open-licence display fonts, an allow-list in `backend/app/services/clip_edit/caption_fonts.py`:
Anton, Bangers, Bebas Neue, Titan One, Lalezar (SIL OFL 1.1) and Luckiest Guy (Apache 2.0). Each
is pinned to one file of the google/fonts repository (commit and sha256) and installed with its
licence file by

```bash
cd backend && python scripts/fetch_caption_fonts.py      # into CAPTION_FONTS_DIR (./fonts)
```

Never committed (`backend/fonts/` is ignored), never downloaded by the app itself. The production
image runs the script at build time (`/app/fonts`); CI runs it before the tests. A file that does
not match its pin is never used. A style whose font is missing is **unavailable**: the styles API
says so, the editor's card is disabled, the API refuses the edit (409) and a render fails with a
plain message — no silent fallback to another font.

At render, the style's font file is copied into the attempt workspace (`fonts/`) and libass finds
it there (`subtitles=…:fontsdir=fonts`, a fixed relative name; no path reaches the filtergraph).
Characters a display font lacks fall back to Noto Sans / Noto Sans Arabic through fontconfig, as
before.

**Line fitting.** libass sizes a font by its OS/2 Windows line height, so one em is
`unitsPerEm / (winAscent + winDescent)` of the font size; widths are measured with FreeType
(Pillow) at that em, uncovered characters with the Noto tables, plus 3 %. Measured against real
libass renders: within 1 % for the Latin fonts, conservative for Arabic (lines come out shorter,
never overflowing). A popping word keeps room for its growth.

## The renderer

`caption_v2.py`: `V2Style` gains `font`, `one_word`, `highlight` (colour / marker / underline),
`marker`, `marker_outline`, `pop`, `reveal`, `glow` and `scripts`. Their defaults are the original
behaviour, so Focus, Punch, Minimal and Boxed render byte-for-byte as before (a test pins this).
The spoken word's tags come only from the preset (`_spoken`); text still goes through
`escape_ass_text_v2`. One word uses cue rules of one word per cue (the "lonely word" merge is off
for it). One word and Reveal need real word timing: `EditConfig` refuses them with phrase timing,
the caption preview answers 409, and Auto Edit with a template that asks for them on a clip
without word sync uses Focus with a note.

The edit snapshot is unchanged (`captions.style` names the preset); the `clip_edits` check accepts
the new names (migration `67c10e35281d`).

## The editor

`GET /caption-styles` now describes each preset fully (font family, its em ratio, availability,
the emphasis kind, pop, reveal, glow, whether it needs word sync, scripts). The caption style
cards show each style in its own font with a hint, a **Word sync** tag where needed, and are
disabled when unavailable; choosing One word or Reveal switches timing to word sync. The live
preview draws the same fonts (self-hosted by Next from Google Fonts), the marker, underline, pop
(the word scales like the render), glow and reveal. Template builder cards use the same samples.

## Checked

- `tests/test_caption_v2.py` (every style: colours, line fitting in its own font, real libass
  frames — the emphasis follows the speech, the marker colour moves, Reveal draws one, two, three
  words, long lines inside the margins), `tests/test_creator_caption_styles.py` (pins, a tampered
  file, line metrics, word-timed styles, the styles API, a missing font refused, a real pipeline
  render with Bangers copied into the workspace, the template fallback), plus the caption,
  edit, Auto Edit and template suites. Frontend: `caption-timing.test.ts` (Reveal's counter).
- A contact sheet of all 14 styles rendered by libass, and in the browser: 14 cards in their fonts,
  the Pop preview in Anton with the spoken word at 116 %, a real worker render of Pop on a
  tightened Short; 375 px without overflow.

## Limitations

- Still presets: no style designer, custom colours, uploaded fonts or per-word positioning.
- Display fonts other than Lalezar are Latin; Arabic words in them use Noto Sans Arabic.
- The preview's fonts come from Google Fonts via Next (same families, possibly a newer revision
  than the pinned files): close, not pixel-exact.
