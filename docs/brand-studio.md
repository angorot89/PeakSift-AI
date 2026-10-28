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
