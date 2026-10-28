# Brand Studio & reusable templates (V1.7)

A creator sets up **how their Shorts look** (a *brand*) and **how their Shorts are edited** (a
*template*) once, and every new Short can start from them. Nothing is locked: each Short can
still be changed on its own.

| Creator word | What it is | Model |
|---|---|---|
| **Brand** — how your Shorts look | colours, logo, end-card line | `BrandProfile` |
| **Template** — how your Shorts are edited | framing, captions, opening hook, visuals, sound, brand use | `ShortTemplate` |
| **This Short** | the exact settings of one version | `ClipEdit` snapshot |

## Brands (`BrandProfile`)

`app/models/brand.py`, `app/services/branding/`, `app/api/brand.py`.

- **Fields**: a name (1–60 characters, unique per creator), a primary colour, optional secondary
  and accent colours, an optional *caption emphasis* colour (the spoken word), an optional logo
  with its corner (top-left, top-right, bottom-left, bottom-right) and size (small, medium,
  large), and an optional end-card line the creator writes (≤ 40 characters, e.g. "Follow for
  more" — PeakSift never writes marketing text).
- **Colours** are hex only (`#RGB` or `#RRGGBB`, any case) and stored as `#RRGGBB` uppercase —
  never CSS names, functions, alpha or anything a browser or FFmpeg would parse. A database
  check enforces the stored form.
- **Readability** (`colors.py`, WCAG 2.1 contrast): a caption emphasis colour is used as caption
  text only when it reaches 4.5:1 on the darkest-but-lightest surround of every caption preset
  (`#101014`); otherwise captions keep their own colour and the brand colour stays an accent.
  `GET /brand/profiles` reports `caption_emphasis_readable` so Brand Studio can say so.
- **Logo**: one of the creator's own **image** visual assets, from any of their projects
  (`GET /brand/logo-candidates`). It reuses the private visual library — no other upload or
  storage. Uploads are already normalized there (PNG when transparent, otherwise JPEG; CMYK and
  palette images converted), so every image is a usable logo. Another creator's image is a 404,
  a video a 422.
- **One default** per creator (a partial unique index; making a brand the default clears the
  previous one in the same transaction, and a race ends in a 409, never two defaults). A
  creator's first brand becomes the default. At most 10 brands.
- **Deleting**: deleting a brand never changes a Short made with it (see *Historical
  snapshots*). An image that is a brand's logo cannot be deleted from Assets (409 naming the
  brand); deleting the image's whole project clears the logo (`ON DELETE SET NULL`).

Endpoints: `GET/POST /brand/profiles`, `GET/PATCH/DELETE /brand/profiles/{id}` (`PATCH` changes
only the fields sent; `null` clears an optional one; `is_default` true/false), `GET
/brand/logo-candidates`.

## Templates (`ShortTemplate`)

`app/models/short_template.py`, `app/services/branding/template_config.py`,
`app/services/branding/templates.py`.

A template is **preferences, not a finished edit**. Its settings (`TemplateConfig`) reuse the
editor's own types — `Layout`, `DynamicPreset`, `CaptionPosition`, `HookStyle`,
`HookPosition`, Auto Edit's `MusicLevel` and `DuckingStrength` — and every setting either names
one of those values or is empty ("let the recipe decide"):

| Section | Settings |
|---|---|
| Style | framing: `auto` (Auto Edit decides), `smart_reframe` (preferred — used only when a completed framing analysis exists, otherwise Auto Edit's own choice), `blur_background`, `center_crop`, `fit` |
| Captions | on/off, preset (Focus, Punch, Minimal, Boxed), position |
| Opening | hook on/off, style, position, seconds (0.5–5). The words always come from the clip. |
| Visuals | B-roll amount: `none`, `light` (at most one), `recipe` (the recipe's limit) |
| Sound | music level and ducking *when the creator picks music* (a template never picks music), sound effects allowed, loudness normalization |
| Brand | show the brand's logo, append an end card (1–3 s) |

- Settings are validated and normalized (unknown keys, values outside the allow-lists, hook and
  captions in the same place are refused; settings that do not apply are dropped), and stored
  with `version: template_v1`.
- A template may start from a recipe (`GET /brand/template-starters`: Clean, Punchy, Story,
  Minimal with each recipe's own defaults) and may use one of the creator's brands (deleting the
  brand leaves the template without one).
- **Versions**: `version` goes up when the settings, the recipe or the brand change — not when
  the template is renamed or described, and not when the same settings are sent again.
- One default per creator (as for brands); at most 30 templates; names unique per creator.
  **Duplicate** makes "Punchy Gaming copy" (then "copy 2"…), version 1, never the default.
- Deleting a template never changes a plan or a Short made with it.

Endpoints: `GET/POST /brand/templates`, `GET/PATCH/DELETE /brand/templates/{id}`, `POST
/brand/templates/{id}/duplicate`, `GET /brand/template-starters`.

## Historical snapshots

Brands and templates are **preferences**; no render ever reads them. When a Short uses a brand,
the exact values are copied into its edit's configuration snapshot (`clip_edit/brand.py`, a
`brand` section with `version: brand_v1`) — the logo's asset id, corner and size, the caption
emphasis colour, the hook accent and the end card (seconds, background, line, logo). The
renderer reads only that snapshot (`EditConfig.from_snapshot`), so **changing or deleting a
brand, a template or the default never changes an earlier Short**, and re-rendering an old
version renders it the way it was made. The section exists only when it changes something:
every edit made before V1.7 keeps exactly its snapshot and fingerprint.

## Rendering the brand

One renderer (`clip_edit/brand_render.py` inside `composition.py`), no separate brand renderer:

```
clip → framing → [framed] → visual elements → corner logo → (+ end card) → captions + hook
```

- **Logo**: the image is one more FFmpeg input, fitted inside a square box — small 16 %, medium
  22 %, large 28 % of the frame width — with `force_original_aspect_ratio=decrease` (never
  stretched: a 4:1 wordmark becomes 172×43 in the small box) and RGBA kept (transparent PNGs stay
  transparent). It is drawn above visuals and under captions and the hook.
- **Caption emphasis**: the dynamic presets' spoken-word colour is replaced by the brand colour
  only when it is readable as text (WCAG AA 4.5:1 on `#101014`, the lightest caption surround).
  An unreadable colour is dropped from the snapshot, so captions keep the preset's colour. Phrase
  captions (Clean / Bold / Creator) have no spoken word, so no emphasis applies.
- **Hook accent**: the *Boxed* hook's label takes the brand accent, with dark or white text —
  whichever reads better — and only if that text reaches AA. Headline and Minimal hooks keep
  their white text (branding never costs readability).
- **End card** (*appended*, a deliberate choice): when a template turns it on, a 1–3 s card is
  added **after** the clip, so the Short is exactly that much longer and the editor says so.
  - The card has the brand's primary colour, the logo centred (if there is one and it is shown),
    the brand name, and the creator's own line. Text is drawn by libass from the same subtitle
    file, escaped like captions, and sized down to fit one line.
  - Nothing covers the clip itself.
  - The card is **silent** (`apad`): the clip's sound is never repeated or stretched; music and
    effects end with the clip.
- **Checks**: the API and the render job both require the logo to be one of the Short owner's
  image assets (any project), and the render fetches it into the attempt workspace. A logo
  deleted or missing before a re-render fails it as `brand_logo_unavailable`, with nothing
  rendered. An image used as the logo of any Short (or brand) cannot be deleted.

### Safe areas and collisions (deterministic)

The logo sits in its corner **inside the General Social Safe Area** (the same margins as captions,
the hook and insets), and `logo_plan` resolves every conflict the same way in the renderer and
the preview:

| Conflict | What happens |
|---|---|
| captions at the bottom, logo in a bottom corner | the logo moves to the top corner on the same side (captions at the top → bottom corner) |
| captions in the centre or off | no move |
| the hook at the top, logo in a top corner | the logo appears once the hook has ended |
| a picture-in-picture or overlay in the logo's corner | the logo is hidden while that inset shows |
| a cutaway | the logo stays on top (branding continues over B-roll) |

`GET /brand/layout` publishes the box fractions, safe-area margins and end-card geometry for
previews.

## Auto Edit with templates

`app/services/auto_edit/template.py`. `POST …/auto-edits` takes an optional `template_id` (one
of the creator's templates; another creator's is a 404) and then `recipe` becomes optional:
the creator's recipe choice, else the template's starting style, else Clean. A request must
name one or the other.

**Precedence**, strongest first:

1. hard product constraints — a completed, confident framing analysis for Smart Reframe;
   transcript timing for captions; hook words grounded in the clip; every visual and audio check;
2. the creator's explicit per-Short choices (in the editor, on the new version);
3. the **template**'s settings;
4. the template's **brand** (logo, colours, end card);
5. the **recipe**;
6. performance hints (opt-in, weak, inside the recipe);
7. the planner's preferences.

The planner (local model or rules) proposes inside the recipe; `validate_plan` makes it a valid
edit; **then** the template is applied, so a model can never undo a template setting (Minimal
captions stay Minimal, the logo stays on). What a template cannot force falls back with a note:

- Smart Reframe without a confident analysis keeps Auto Edit's framing;
- an opening hook needs a grounded line from the clip;
- a template never adds music — it only sets the level and ducking of the track the creator
  chose;
- hook and captions never share a position (the hook takes the other place);
- a combination that cannot form a valid edit keeps Auto Edit's choices.

**Frozen**: the plan stores the template — its id, name, version, settings and the brand section
— in its request snapshot when it is asked for, so editing or deleting the template or brand
later never changes the plan; *Try another plan* keeps the same frozen template. The plan's
explanations say "Started from your Punchy Gaming template. Used your Amine Clips brand." — never
colour codes or internals. Applying the plan records an **origin** on the new version
(`ClipEdit.origin`: template id, name and version, brand name, plan id) — for display only; the
render reads the snapshot.

## Brand Studio (UI)

`/brand` (sidebar **Brand Studio**), `components/app/brand/`, `lib/brand.ts`,
`lib/brand-rules.ts` (pure, unit-tested; mirrors the server's colour and placement rules).

- **Words**: the page opens with the three ideas — *Brand: how your Shorts look*, *Template:
  how your Shorts are edited*, *Each Short: starts from them, you can still change anything*.
- **Brand form** (left) and a **live preview** (right; stacked under the form on phones): name,
  primary colour, optional accent (falls back to the primary colour) and caption emphasis
  colours, logo, corner and size, end-card line, and *Use as my default brand*. *Saved* /
  *Unsaved changes* are always shown; leaving with unsaved changes asks the browser to confirm;
  deleting is confirmed ("Shorts you already made keep their look").
- **Colour fields**: the system colour picker (keyboard accessible, labelled "… picker") and a
  labelled hex field validated as you type ("Use a hex colour like #FF3A72"); optional colours
  can be cleared. The emphasis field says whether the colour is readable as caption text, or
  that captions will keep their own colour.
- **Logo picker**: a dialog listing the creator's images from every project (thumbnails on a
  checkerboard so transparency shows), as a radio group — arrow keys move, the choice is marked
  by a check and text, not colour alone — with *No logo*. With no images yet it points to a
  project's Assets.
- **Preview** (`BrandPreview`): a 9:16 still on a sample background drawn with the renderer's
  numbers (`GET /caption-styles`, `GET /brand/layout`) and the editor's caption CSS
  (`CaptionSampleLayer`). *Opening* shows the hook (with the brand accent on a Boxed hook);
  *During* shows captions with the emphasis colour and the logo where the renderer will put it
  — the note explains a move ("Shown top right so it stays clear of the captions (you chose
  bottom right)") or that the logo waits for the hook; *End card* shows the card and how much
  longer the Short gets. The preview is decorative (`aria-hidden`) with a text summary for
  assistive technology.

## Template builder and library (UI)

`components/app/brand/template-builder-view.tsx`, `template-library.tsx`, `lib/template-rules.ts`
(pure, unit-tested).

- **Library** (Brand Studio, *Your templates*): cards with a short summary in creator words
  ("Boxed captions · Boxed hook · Light B-roll · Logo · End card +2s"), the brand, the starting
  style and when it was last changed; the default first (a *Default* badge with a star — not
  colour alone), then the most recently changed. Each card's menu: **Edit**, **Use for new
  Shorts** (makes it the default — what "Use" means outside a Short), **Duplicate** ("… copy"),
  **Rename** (a dialog), **Delete** (confirmed: "Shorts and plans made with it keep their
  settings"). Empty state: *No templates yet — Save the styles you use repeatedly so every
  Short starts closer to finished.* — **Create one**.
- **New template**: start from **Clean, Punchy, Story, Minimal** (each recipe's defaults) or
  **Blank**; `/brand/templates/new?start=punchy` skips the choice.
- **Builder**: the preview is dominant (left on desktop, first on phones) and uses the same
  `BrandPreview` as Brand Studio; the tools reuse the editor's patterns — the same tool tabs
  (**Style, Captions, Opening, Visuals, Sound, Brand**), option cards with caption samples,
  segmented choices and switches. Primary choices are visual (caption cards, framing cards,
  B-roll *None / Light / As the style suggests*); technical values are under **Advanced** (hook
  seconds, ducking, loudness). Empty choices are labelled as the style's ("Using the style's
  choice"). The hook position the captions use is disabled. *Sound* says plainly that templates
  never add music. *Brand* picks one of the creator's brands, shows the logo or not, and turns on
  the end card with its length ("+2.0 s to every Short").
- A **name is required** (focus moves to the field with "Give the template a name."); the
  description is optional. *Saved* / *Unsaved changes* are always shown; leaving with unsaved
  changes asks the browser to confirm; saving a new template moves to its own address.
- *Start new Shorts from this template* makes it the default.

## Creating Shorts with templates

- **Create a Short** shows *Using: Punchy Gaming* (the default template) with its summary and
  **Change** (any template, or *No template*). Auto Edit's card says "Starts from your “Punchy
  Gaming” template". A creator without templates sees exactly the V1.6 flow — nothing asks for
  Brand Studio.
- **Auto Edit** opens with that template selected (`?template=…`; otherwise the default); the
  recipe choice disappears — the template brings its starting style — and *No template —
  choose a recipe* brings it back. The plan's review starts with "Started from your Punchy
  Gaming template. Used your Amine Clips brand."
- **Measured** (real browser, real local model): a returning creator with a default template
  goes from *Create a Short* to a rendering, branded Short in **3 clicks** (Auto Edit → Prepare
  my edit → Use this edit), against 4 in V1.6 (with a recipe to choose and no branding at all).
- **Editor**: a strip above the tools says where the settings came from — "Template: Punchy
  Gaming · Brand: Amine Clips · end card +2s" (from the version's or the draft's origin) — and
  "Changes here apply to this Short only." **Remove branding** / **Add my brand** change this
  Short only (`GET /brand/edit-section` gives the section from the template, the default
  template or the default brand; the server validates it again). A branded version opened in the
  editor keeps its brand section through every change and re-render.
- **Save as template** (a dialog with a name) and **Update “Punchy Gaming”** (a confirmation:
  "Shorts you already made keep theirs") are the only ways the editor changes templates —
  never silently. They save how the Short is edited (`settingsFromEditor`: framing, captions,
  hook look, B-roll amount, sound levels, brand use) — never its words, music or visuals.
- Edits record a display-only `origin` (`origin_template_id` on `POST …/edits`, kept only if the
  template is the creator's own).

## Ask PeakSift about brands and templates

`app/services/copilot/branding.py`. The Copilot's context gains a small `branding` section on
every page: the creator's brands (name, default, logo or not), up to eight templates by handle
(`template_N`: name, default, starting style, brand, a few creator words — never ids), how many
Shorts they have published, and — in the editor — where this version came from (its template
and brand, the template version it was made with, the template's version now, and how it
differs from the template now). Brand Studio pages are their own Copilot page (`brand`).

PeakSift answers the exact questions itself (never the model):

| Question | Answer | Button |
|---|---|---|
| "What template am I using?" | in the editor: this version's template and brand; elsewhere: the default template and its settings; none: how to make one | *Open “…”* / *Open Brand Studio* |
| "Do I have a default brand?" | the default brand and whether it has a logo, or how to make one | *Open Brand Studio* |
| "Use my Punchy Gaming template" | with a clip on the page: Auto Edit for this clip with that template; elsewhere: open it | *Use “Punchy Gaming”* / *Open “…”* |
| "Why does this Short look different from my template?" | the template changed after the Short was made (version 1 → 2; Shorts keep their settings), was deleted, or the remaining differences ("captions are Focus here (template: Minimal)") | — |
| "Which template fits this clip?" | a **suggestion** from the clip's kind and each template's starting style ("“Punchy Gaming” is a reasonable fit because this is a 12s funny moment and it starts from the Punchy style. This is a suggestion, not a prediction.") and, with fewer than 10 published Shorts, "Your performance history isn't large enough to prefer one statistically." | *Use “…”* |

The real-model review showed `llama3.2:3b` inventing a reason for a template choice, which is
why that answer is PeakSift's own. For anything else about templates the model is told to
suggest by name, say it is a suggestion, and never claim one will perform better.

**Actions**: the model may offer *Open Brand Studio* and *Open the template*; only PeakSift
offers *Use this template* (Auto Edit for this clip with the template — the clip travels with the
action and is checked again). Every action is re-checked on click ("This template is no longer
available."). No Copilot action creates, changes or deletes a brand or a template.

## Hardening

| Case | Behaviour |
|---|---|
| brand deleted | templates lose their brand; Shorts and plans keep theirs (snapshots) |
| template deleted | plans and Shorts keep their settings; the editor and Copilot say it was deleted |
| default template deleted | Create a Short and Auto Edit fall back to no template; `edit-section` falls back to the default brand |
| logo deleted from Assets | refused while a brand or any Short uses it (409, naming the brand) |
| logo's project deleted | the brand's logo is cleared; applying a plan with that logo says "The brand logo is no longer one of your images…" (409); re-rendering fails as `brand_logo_unavailable` |
| logo storage missing | the render fails clearly (`brand_logo_unavailable`), nothing rendered |
| another creator's logo / template / brand | 404 for brands and templates; 409 for a logo in an edit; never recorded as an origin |
| invalid colour / malformed settings | 422 with the reason (hex only; allow-listed values; unknown keys refused) |
| a template saved in a format this server cannot read | 409 "open it in Brand Studio and save it again" — never planned with half its settings |
| template changed after a plan or a render | the plan and the Short keep their frozen settings; the Copilot explains "changed after this Short was made (version 1 → 2)" |
| two defaults at once | the partial unique index refuses it (409) |
| transparent / CMYK / palette / very wide / very tall logo | normalized on upload; fitted inside the square box by its longer side (172×43, 43×172), transparency kept |
| an end card with no logo / no music / longer than the clip | exact extra length; silent; card colour and text only |
| captions, hook, picture-in-picture or overlay near the logo | the placement policy (moves, waits, hides) |
| Smart Reframe | the logo stays fixed while the crop moves |
| Arabic and emoji captions | the brand emphasis colour applies to the spoken word; text unchanged |
| unsaved changes / rapid switching | Brand Studio and the builder show *Unsaved changes* and ask before leaving the page; a template switch in Create a Short or Auto Edit only changes what the next plan uses |

The editor's live preview now draws the brand logo too, placed by the same rules (and hidden while
a top hook shows). Every V1.7 screen passes the browser audit at 1440, 1280, 1024, 768, 430, 390
and 375: axe WCAG 2.1 AA, no horizontal overflow, 44 px touch targets on phones, and no console
errors.

The audit found that Playwright's full-page screenshots turn off coarse-pointer emulation for the
rest of a phone session, so touch targets measured after one looked too small. The audit now
measures before any screenshot and takes phone screenshots at viewport size.

## Acceptance

**Journeys** (`tests/test_brand_acceptance.py`, deterministic planner, run in CI):

- a fresh creator: nothing forced at sign-up → a brand with a logo and an emphasis colour → a
  default Punchy template with an end card → Auto Edit with the template → a version whose
  snapshot has the logo, the emphasis colour, the end card (brand colour, line, logo) and whose
  origin names the template version;
- historical safety: after the template (Minimal captions, no end card) and the brand colour
  change, the earlier version's configuration is exactly as it was and still names version 1,
  while a new plan uses version 2's values;
- two templates (Punchy Gaming and Clean Professional) on one clip make two different versions.

**Release gate** (`scripts/brand_acceptance.py`, against a running PeakSift with the real planner
and renderer, as a dedicated acceptance creator): renders a branded Short from a template
through Auto Edit and checks the file (1080×1920 H.264 + AAC, the duration = clip + end card,
−14 LUFS ± 1, a silent end card, the brand section the template asks for), then changes the
template and checks that the rendered version's settings and **file bytes** are unchanged and
its origin still names the old version (and puts the template back).

```bash
BRAND_ACCEPTANCE_EMAIL=… BRAND_ACCEPTANCE_PASSWORD=… \
  python scripts/brand_acceptance.py --api http://localhost:8000 \
  --project ID --video ID --clip ID --template ID [--music ID]
```

**Local results** (isolated review stack, `llama3.2:3b`, FFmpeg with libass; generated footage
and audio — nothing downloaded):

- **Final branded Short** ("Speedrun Fails — Episode 7", template *Punchy Gaming*, brand *Amine
  Clips*):
  - **file**: 14.0 s (12.0 s clip + 2.0 s end card), 1080 × 1920, 30 fps, H.264 + AAC,
    3,818,286 bytes; −14.0 LUFS integrated, −2.5 dBFS peak; the end card measured −70 LUFS
    (silent);
  - **what the frames show**: word-synced Punch captions with the spoken word in the brand's
    yellow; a Boxed hook ("It feels wrong") on a brand-pink label, the logo waiting for it; the
    logo moved from bottom right to top right (captions at the bottom); a faded lava cutaway
    with the logo and captions on top; a picture-in-picture in the logo's corner with the logo
    hidden meanwhile; the end card in brand pink with the logo, "Amine Clips" and "Follow for
    more"; music and a whoosh at the cutaway (the visuals and the effect were the creator's own
    per-Short additions in the editor, on top of the template);
  - **the plan**: "Started from your Punchy Gaming template. Used your Amine Clips brand." The
    template's Smart Reframe preference fell back with a note, because the generated footage has
    no faces ("…isn't analyzed confidently yet, so blur background was kept"). Smart Reframe
    with a logo is verified by the render tests with a moving crop path. The B-roll analysis
    found no suggestions on this narration, so Auto Edit placed none.
- **Historical safety**: after the template went from version 2 to 3 (Minimal captions, no end
  card) and the brand's primary colour changed, the version made with version 2 had exactly
  the same configuration and a **byte-identical file** (sha256), and still named version 2; a
  new plan used Minimal captions and no end card (12.0 s).
- **Two templates on one clip**: Punchy Gaming → Punch captions, logo, 14.0 s; Clean
  Professional → Minimal captions, no logo, no B-roll, 12.0 s.
- **Fresh creator in the browser**: sign-up → the logo uploaded in a project's Assets → a brand
  ("Nova Plays", violet, yellow emphasis, logo, "More runs every Friday") and a default template
  ("Nova Punchy", end card) made in Brand Studio → video upload → *Create a Short* already
  *Using: Nova Punchy* → Auto Edit's review "Started from your Nova Punchy template. Used your
  Nova Plays brand." → *Use this edit* → the editor "Template: Nova Punchy · Brand: Nova Plays" →
  render → **Download**: 10.0 s, 1080 × 1920, H.264 + AAC, 2,555,293 bytes. (Transcription,
  moment detection and the clip — V1.0–V1.5 journeys — were driven through the API to save
  time.)
- **Returning creator**: 3 clicks from *Create a Short* to a rendering, branded Short (V1.6: 4,
  unbranded).
- **Release gate run** (`scripts/brand_acceptance.py`, review stack): **13/13 PASS** — the plan used
  the template; 1080 × 1920 H.264 + AAC; 13.50 s = 12.00 s clip + 1.5 s end card; brand section,
  logo and end card as the template asks; −14.0 LUFS; end card −70.0 LUFS (silent); the template
  got a new version; the old version's settings unchanged, its file byte-identical, its origin
  still naming the version it was made with.
