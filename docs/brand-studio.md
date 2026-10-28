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
