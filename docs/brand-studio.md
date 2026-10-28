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
