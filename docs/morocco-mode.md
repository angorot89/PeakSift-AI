# Morocco Mode (V1.8)

Morocco Mode is PeakSift **with Moroccan context, on top of everything in Global**. It is not a
separate app and it never hides a Global tool, template, visual or sound. What it adds comes from
three honest sources only: **the creator's own words** (Darija hooks), **the creator's own assets**
(Moroccan visuals and sounds they made, own or licensed) and **curated formats** built from settings
PeakSift already has. Nothing is called *trending*: PeakSift has no trend source, and no figure,
place, slang, sound or audience claim is invented.

## Market and language are separate

| Concept | Values | Where |
|---|---|---|
| **Market** — who a project is made for | `global`, `ma` (Morocco) | `User.default_market` (new projects start in it), `Project.market` |
| **Content language** — what the video is in | `auto`, `darija`, `arabic`, `french`, `english`, `mixed` | `Project.content_language` |

- A market is a profile (`app/services/markets.py`: name, local label, hook languages, a list of
  locations), never a code path. `markets.snapshot()` is `None` for Global, so Global provenance and
  fingerprints are unchanged.
- `GET /markets`: the markets and the label vocabularies. `PATCH /auth/me {default_market}` and
  `PATCH /projects/{id} {market, content_language}`.
- `GET /projects/{id}/language` returns `chosen`, `detected` and `effective`. Detection
  (`app/services/language.py`) is a **hedged guess** ("Likely Darija", "Possibly mixed (Darija,
  French)", "Not enough speech to tell"). It is built from small marker lists, Arabizi digits used as letters
  (3, 7, 9) and ka- verb forms ("kanqra"). The creator's choice always wins. `fold`/`tokens`
  normalize text for **matching only** (accents, Arabic letter variants, Arabizi). They never rewrite what was said.
- Every Short records the market it was made for (`ClipEdit.origin.market`, also frozen in Auto
  Edit plans). Changing the project later never rewrites it. The Short, the editor and the Auto Edit
  review show "Made for: Morocco Mode". Global Shorts show nothing new.

## Darija hooks: only the creator's words

`GET /projects/{p}/videos/{v}/clips/{c}/hooks?target=` (`app/services/hooks.py`):

- **From your clip** — the clip's own sentences, one per kind (question, story, lesson…), verbatim.
- **Darija in the other script** — a deterministic, letter-by-letter **transliteration**
  (`to_arabic` / `to_latin`) of a Darija line the creator said, labelled "your words in the other
  script — check the spelling". This is the only way PeakSift writes Darija. A clip that is not in
  Darija gets none (`unsupported`).
- **Other languages** — the local model rewrites one line at a time **only between reliable
  pairs** (French ↔ English, measured). Each result is checked (`check`: script, length, numbers,
  money, names) and must read as the target language; otherwise `none_grounded` / `unavailable`.
- Ask PeakSift answers "Give me 3 Darija hooks" and, in a local market's project, "Write an
  opening line" with the clip's own lines. It never uses a model's opening.

Why so strict: on the acceptance set, `llama3.2:3b` could not read Arabizi, its Arabic-script Darija
was not dependable, and free-form hooks invented content.

### Darija quality manual set

`python scripts/darija_quality.py` prints the manual set: 16 lines written for it (Arabizi,
Arabic-script Darija, code-switching with French and English, French, English, Modern Standard
Arabic, too-short lines), with the hedged guess, whether the line can open a Short, and the other
script. `--check` (and `tests/test_language.py`) enforce the automatic part: **16/16**.

Reviewer notes on the spelling column (why the UI says "check the spelling"):

- Latin → Arabic is letter by letter. Short vowels are written, so "l9hwa" gives لقهوا, not
  لقهوة. Feminine endings (zwina → زوينا, not زوينة) and doubled letters are not inferred. French or
  English words inside a mixed line are transliterated too ("c'est" → ك'ست).
- Arabic → Latin follows Arabizi conventions (ع 3, ح 7, ق 9). The article ال gives "al" where
  Darija speakers usually write "l".
- Numbers stay numbers ("part 2?" → … 2؟); digits inside a word spell letters ("3lach" → علاش).

Darija **speech recognition** accuracy has not been measured. This machine has no Darija voice, and
the review stack used a controlled, written transcript.

## Morocco content styles (curated formats)

`app/services/branding/market_starters.py`: seven formats are **curated, not trends**:
- Morocco Vox Pop
- Darija Reaction
- Local Storytime
- Lesson / Explainer
- Morocco Product Showcase
- Food & Place Review
- Clean Talking Head

Each is a `TemplateConfig` on one of the four recipes, made only of settings the editor already
supports (framing, captions, the opening hook, B-roll amount, music level and ducking, sound
effects, logo and end card). Picking one (`/brand/templates/new?start=<key>`) creates the
**creator's own** versioned template with `market = "ma"`. Plans freeze it like any other template.

- `GET /brand/template-starters?market=ma` lists Morocco formats first, then every Global starter.
- Without `?market` the list is exactly the Global one.

The release gate renders the same clip with Global **Punchy** and **Morocco Vox Pop**. Each version
follows its own template. They differ in:
- hook style (headline vs boxed);
- hook length (2.0 s vs 2.5 s);
- B-roll (recipe vs none);
- sound effects;
- ducking.

## Local assets and sounds

Every visual and sound carries the creator's labels (`app/services/asset_labels.py`):

| Label | Values |
|---|---|
| `origin` | Made by you · Owned by your company · Licensed (**licence note required**) · Public domain · CC0 — there is no "from the internet" |
| `market` | Global or Moroccan |
| `category` | visuals: city, street, café, food, travel, coast, mountains, architecture, beauty, fashion, business, campus, sports atmosphere, family & lifestyle · sounds: café / street / market / crowd / celebration ambience, transition, percussion, voice reaction (organizational only, never popularity) |
| `location` | only for a local asset, only from the market's list (Casablanca, Marrakech, Rabat, Tangier, Agadir, Fez, Chefchaouen, Atlas, Sahara) — PeakSift never guesses a place from an image |

- `PATCH /projects/{p}/visual-assets/{id}` and `…/audio-assets/{id}` are owner-scoped (404
  otherwise). A 422 never echoes the submitted value.
- `GET /markets/{code}/assets?kind=` lists the creator's own local assets (the Creator Kit).
- **Search**: `rank_assets(…, local_market)` sorts local first **within a strength tier**. A strong
  Global match is never buried under a possible local one. Responses mark hits `local`, and the
  library groups "Local matches" and "Global alternatives". The category and place the creator
  chose count like tags ("Casablanca café" finds a photo labelled Café · Casablanca).
- **Auto Edit**: local assets are a weak hint inside the matcher (`match_queries(local_market)`). Only
  strong matches are placed. A note says what happened ("Morocco Mode put your Moroccan visuals
  first…" or "No strong Moroccan visual matched…, so PeakSift used one from your Global library").
  Plan facts include the market only when set, so Global fingerprints are unchanged.

## Ask PeakSift in Morocco Mode

`app/services/copilot/market.py` adds a small `market` section to the bounded view (a local
market's project, or a question about one). PeakSift answers these questions itself, without
the model:

- "Do I have any Moroccan visuals?" — names and counts.
- "Which Morocco template fits this clip?" — an editorial pairing, "not a prediction".
- "Can I keep this in French?" — yes, and why.
- "Give me 3 Darija hooks" / "Write an opening line" — the clip's own lines.
- "What can I use from the Global library?"
- "Use local assets if they fit."
- "Is this good for Moroccans?" / "Will Moroccans like this?" — PeakSift never predicts how an
  audience reacts or speaks for a group; it says so, with the project's facts.

Whatever the model writes, the safety screen (`safety.drop_generalizations`) removes sentences that
generalize about a people, culture, religion or audience. This covers English, French and Arabic
script: "Moroccans love…", "may appeal to Moroccans", "les Marocains préfèrent…", "المغاربة كيحبو…".
PeakSift's own answers are in English, like its other own answers.

## The interface

- **Global / Morocco Mode switch** (Home, including a fresh creator's welcome, and `/morocco`). It
  shows "New projects: …", saves the default from either page and never changes existing projects.
  "Global library included" is always visible.
- **`/morocco`**:
  - what Morocco Mode adds (Darija hooks, content styles, local visuals, local sounds, Ask PeakSift);
  - the curated formats;
  - the creator's Moroccan visuals and sounds;
  - Browse the Global library.
  - Empty states are honest: "No Moroccan sound assets have been added yet." with Upload sound /
    Browse Global sounds.
- **`/morocco/kit`**: Visuals · Sounds · Hooks · Templates, with search and filters built only from
  the creator's own metadata.
- **Projects**:
  - "Made for" when creating one;
  - a Market and language card on the overview (detection as a hint);
  - Source and market labels on visuals and sounds.
- **Right-to-left**: transcript lines, moment titles and excerpts, hook ideas, the hook field and
  the caption/hook preview use `dir="auto"`. libass renders Arabic script in the Short.
- No flags, zellige or national colours. The mode is said in words; the design system is unchanged.

## Global stays the same

- Old projects and users are Global.
- Fingerprints, starters, search order, Copilot views and provenance only change when a market is
  set.
- The Global creator regression (fresh journey, audit, gates) runs on the same build.

## Acceptance

| Gate | Result |
|---|---|
| `scripts/morocco_acceptance.py` (real model, real renders): language, grounded hooks (Arabic-script transliterations of real lines; English refused for Darija), "Casablanca café" → local café first, "software dashboard" → Global dashboard first, Global Punchy vs Morocco Vox Pop, audio (local café ambience + transition at 3.0 s: −14.1 LUFS, −1.4 dBTP, cue +23 dB above the high-band median, provenance), 10 Ask PeakSift questions (5 own answers, 5 through `llama3.2:3b` or PeakSift: no stereotype, no claimed action, nothing quoted that isn't in the data), snapshot safety | **31/31** |
| Fresh Morocco creator journey (browser): sign up → Morocco Mode → project → upload → transcript → moments → Vox Pop template → local visual → Create Short → Auto Edit → Darija hook (Arabic script) → timeline → render → "Made for Morocco Mode" → simulated publish → library, no console errors | **23/23** |
| `scripts/darija_quality.py --check` | **16/16** |
| Browser audit, seven widths (axe WCAG 2.1 AA, overflow, console, 44 px targets) | Morocco creator 133/133 · Global creator 42/42 |

Acceptance found and fixed:
- plan explanations describing a planner's hook style the template had replaced;
- "word-synced" said of phrase-timed captions;
- a model answer "may appeal to Moroccans";
- a model-extended opening line;
- labelled assets not found by their place;
- no mode switch for a fresh creator;
- Darija verb forms read as French;
- a number transliterated as a letter.

## Licensing report (acceptance and review)

Every asset used was **generated locally for this milestone**; nothing was downloaded, scraped or
copied:

| Asset | Kind | Made with | Origin label | Market · category · place |
|---|---|---|---|---|
| `casablanca-cafe-voxpop.mp4` | source video | FFmpeg gradients + macOS `say` (Thomas, French) | — (source) | — |
| `dashboard-review.mp4` | source video | FFmpeg gradients + macOS `say` (Samantha) | — (source) | — |
| `speedrun-fails-ep7.mp4`, `morning-mindset-guest.mp4` | source videos (regression) | FFmpeg + `say` | — | — |
| `casa-cafe-morning.jpg` | image | Pillow shapes (no people, no text) | Made by you | Moroccan · Café · Casablanca |
| `medina-street.jpg` | image | Pillow shapes | Made by you | Moroccan · Street · Fez |
| `atlantic-coast.jpg` | image | Pillow shapes | Made by you | Moroccan · Coast · Agadir |
| `software-dashboard.png` | image | Pillow shapes | Made by you | Global · Business |
| `cafe-ambience.wav` | music bed | FFmpeg brown noise + sine clinks | Made by you | Moroccan · Café ambience |
| `transition-whoosh.wav` | sound effect | FFmpeg filtered white noise | Made by you | Moroccan · Transition effect |
| `soft-pad.wav` | music bed | FFmpeg sines | Made by you | Global |
| `amine-plays-logo.png` | logo (regression) | Pillow | Made by you | Global |

- The Darija/French transcript lines were written for the review and are labelled as a controlled
  transcript.
- No football footage, celebrity faces, copyrighted music or real people appear. Tests generate
  their fixtures at run time.

## Not built (by design)

- Trends of any kind.
- Scraping, Google Trends or news monitoring.
- Virality or performance predictions.
- Autonomous posting.
- Generated media.
- Darija written by a model.
- Audience or cultural claims.
- Political content.

### Future: `MarketTrendProvider` (documentation only — not implemented)

If a licensed, auditable trend source is ever approved, it would sit behind a provider contract like
the others. **Nothing below exists in code.**

```python
class MarketTrendProvider(Protocol):
    """Read-only, licensed market signals for one market. Never scraped."""

    source: str           # the licensed source's name, shown with every signal
    market: str           # "ma"

    def signals(self, *, since: date) -> list[MarketSignal]:
        """Topics or formats with their observation window and source; never a prediction.
        Raises ProviderUnavailable; never returns invented or default signals."""
```

Rules it would have to follow:
- The UI says "observed in <source>, <window>", never "trending".
- Nothing is fabricated when the source is down.
- No per-person data.
- Signals are hints inside the recipe, like the V1.4 performance hints, never a score.
