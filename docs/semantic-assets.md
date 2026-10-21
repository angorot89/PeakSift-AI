# Semantic asset intelligence (V1.3)

V1.3 lets PeakSift understand **what a creator's own images and videos show**, locally. An
untagged `IMG_7834.jpg` of a bridge can be found by searching "bridge structure", matched to a
B-roll suggestion about a bridge joint, and placed by Auto Edit, without the creator writing a
single tag. A `VID_1429.mp4` that cuts from a city skyline to a rocket launch is found for
"rocket launch" *at its launch scene*.

The creator stays in control:

- Matches come in two tiers, **strong** and **possible**. Only strong matches may be placed
  automatically; possible ones are offered.
- Names, descriptions and tags still count.
- Any asset can always be chosen by hand.

## What it does, and does not do

Does:

- Indexes every uploaded image, and representative frames of every video, with a **local**
  image–text embedding model, in the background. Uploads never wait for it.
- **Search your visuals** by what they show, combined with names, descriptions and tags (hybrid).
- Matches B-roll suggestions to the creator's own visuals by content, and lets Auto Edit place
  **strong** matches. A matched video starts at its best scene.
- Keeps working without the model: search and matching fall back to names, descriptions and
  tags, and say so.

Does not:

- Send images or videos anywhere. There is no cloud vision API, no embedding service, and no
  stock or web search.
- Generate, download or fetch media of any kind.
- Recognise faces or identities, read text in images (OCR), or track objects.
- Understand facts. Similarity is a ranking signal, not knowledge or a probability: a photo of
  a bridge "matches" a sentence about bridges, which is not the same as being the right shot.

## Architecture

```
VisualAsset ──► request_index ──► Celery: peaksift.index_visual_asset (ids only)
   (upload)      (fenced row)        │  StorageProvider.fetch → attempt workspace
                                      │  image: safe decode → canonical RGB
                                      │  video: bounded frame sampling (FFmpeg) → canonical RGB
                                      ▼
                         VisualEmbeddingProvider (CLIP ViT-B/32, onnxruntime, CPU)
                                      │  unit vectors (validated)
                                      ▼
            visual_semantic_indexes + visual_asset_embeddings (pgvector)
                                      │
     query text ─► text encoder ─► exact scoped scan (best frame per asset)
                                      │      + names, descriptions, tags (V1.1 matcher)
                                      ▼
                   hybrid ranking: strong / possible tiers (versioned thresholds)
                       │                   │                       │
              Search your visuals    B-roll matching        Auto Edit sources
                                    (match_details)    (strong may be placed)
```

| Part | Where |
|---|---|
| Domain | `app/models/semantic.py` — `VisualSemanticIndex`, `AssetEmbedding`; migration `956a0e44dc9a` |
| Provider contract | `app/services/semantic/contract.py`, `vectors.py`, `images.py` |
| Local model | `app/services/semantic/clip_onnx.py`; `scripts/fetch_semantic_model.py` |
| Test stand-in | `app/services/semantic/fake.py` (deterministic, refused in production) |
| Registry | `app/services/semantic/registry.py` (one provider per process) |
| Indexing | `app/services/semantic/indexing.py`, `sampling.py`; `app/workers/semantic_tasks.py` |
| Lifecycle | `app/services/semantic/lifecycle.py` (upload start, state, lazy reindex) |
| Search | `app/services/semantic/search.py` (thresholds, query cache, scan, hybrid ranking) |
| Matching | `app/services/semantic/matching.py` (B-roll queries, scene offsets) |
| Operator | `python -m app.cli.semantic status|reindex`, `scripts/semantic_search_probe.py`, `scripts/semantic_benchmark.py` |
| UI | `components/app/visual-library.tsx`, `use-visual-search.ts`, `editor/visuals-panel.tsx`, `editor/asset-chooser.tsx`, `lib/visual-search.ts` |

## The model

| | |
|---|---|
| Model | OpenAI **CLIP ViT-B/32** (MIT). This is OpenCLIP's `ViT-B-32` architecture with OpenAI's weights. |
| Files | Qdrant's ONNX exports for fastembed (MIT), from pinned repository revisions: image encoder `e0c24ed` (351,686,194 bytes), text encoder `48ca1db` (254,102,519 bytes) and its `tokenizer.json`. Size and sha256 are pinned for every file. |
| Dimension | **512**, read from the ONNX output shape (`image_embeds: [batch, 512]`). The `vector(512)` column matches it. |
| Runtime | onnxruntime (CPU) and Hugging Face `tokenizers`. Both already ship with PeakSift through faster-whisper, so no PyTorch or second vision framework is added. Runs on Linux x86-64/arm64 and Apple silicon. |
| Determinism | Fixed threads (`SEMANTIC_THREADS`), sequential execution, CPU provider: the same input on the same machine gives the same vector. |
| Preprocessing | Exactly the model's `CLIPImageProcessor`: shortest side 224 (bicubic), centre crop 224 × 224, CLIP mean and std. Text is normalized, wrapped in start and end tokens, truncated to 77 tokens, and padded with the end token. |

Why this model: it is small enough for CPU workers, it is licensed for this use, and the
runtime is already a dependency. It is also the best-documented image–text space.

Rejected alternatives:

- **OpenCLIP or PyTorch:** about 1 GB more dependencies for the same weights.
- **Quantized exports:** a different numeric model to calibrate.
- **Hosted embedding APIs:** they would send creator media off the server.

**Installing.** The model is never committed and never downloaded automatically. An operator
runs `python scripts/fetch_semantic_model.py` once per server. It streams each pinned file,
caps the size, verifies the sha256, and renames atomically. The provider refuses any other
file. If the model is missing, indexing fails with "The visual search model is not installed on
this server" (retryable) and search falls back to words.

**Settings:**

- `SEMANTIC_PROVIDER`: `clip_onnx`, or `disabled`. `fake` is for tests and non-production
  stacks; production refuses it.
- `SEMANTIC_MODEL_DIR`, `SEMANTIC_THREADS`, `SEMANTIC_BATCH_SIZE`, `SEMANTIC_VIDEO_MAX_FRAMES`,
  `SEMANTIC_FRAME_TIMEOUT_SECONDS`, `SEMANTIC_QUEUE`, `SEMANTIC_LAZY_REINDEX_PER_REQUEST`,
  `SEMANTIC_STALE_AFTER_SECONDS`, `SEMANTIC_MAX_ATTEMPTS`.

## Model versioning and stale indexes

A vector belongs to an **embedding identity**:

- `provider`, `model`, `model_version` (the pinned export revisions);
- `embedding_version` (`semantic_v1`: PeakSift's canonical pixels plus the CLIP preprocessing);
- `dimensions`.

Rules:

- `(asset, identity)` is unique.
- Search reads only indexes whose identity equals the server's *current* one, so vectors of
  different models are **never compared**.
- Changing the model, or the preprocessing version, makes every older index **stale**. It is
  kept but ignored until the asset is indexed again:
  - listing a library re-queues a few stale assets per request (`SEMANTIC_LAZY_REINDEX_PER_REQUEST`, default 3);
  - `python -m app.cli.semantic reindex` re-queues them in bounded batches.
- When an asset's new index is ready, its stale ones are deleted.

A model with a different dimension needs a migration, because the column is typed.

## Indexing

**Requesting** (`indexing.request_index`):

- There is one index row per asset and current identity.
- A ready index is reused; a live one is not started twice.
- A failed one restarts only on an explicit retry; a stalled one can be taken over.
- Attempts are bounded.
- The Celery task id is committed on the row **before** the job is enqueued; this is the
  fencing token.
- Concurrent requests (two uploads of one file) create one row: the loser steps back.
- A broker outage records a retryable failure ("Visual analysis could not start; try again").
  The upload itself still succeeds.

**Running** (`run_semantic_index`, ids only, no Celery autoretry):

1. **Claim:** stray, duplicate and older tasks are ignored.
2. **Reuse:** an identical file (same sha256 and kind) **of the same owner**, already indexed
   by the same model, gives its vectors with no model run. They are re-validated before they
   are copied, and they never cross owners.
3. **Fetch** through `StorageProvider.fetch` into the attempt's own `job_workspace`, which is
   always removed.
4. **Image:** the stored rendition (JPEG or PNG only; uploads are already normalized) is decoded
   with bomb protection and pixel limits. `canonical_rgb` then makes it EXIF-upright,
   composites transparency on a fixed neutral grey (never a random colour), converts it to RGB
   and bounds it to 1024 px.
5. **Embed** in bounded batches. Every vector passes `to_unit`: exact dimension, finite values,
   a non-zero norm, scaled to unit length in float32.
6. **Finish:** the vectors and `ready` are written in **one commit** (owners only). If the asset
   or project was deleted meanwhile, the job stops quietly.

Failures never make the asset unusable. They record a safe code and message:

- `asset_missing`, `storage_unavailable`, `unreadable_image`, `unusable_image`;
- `unreadable_video`, `no_frames`;
- `model_unavailable`, `embedding_failed`, `model_changed`;
- `time_limit`, `internal_error`.

Messages contain no paths, model locations or internals. The creator can **Retry visual
analysis** while attempts remain.

**Progress is real:** for a video, embeddings computed out of the frames selected (the API
reports `frames_done` / `frames_total`); for an image, one step.

## Video frame sampling

A video is never embedded frame by frame (`sampling.py`):

1. **Target:** `clamp(ceil(duration / 2 s), 1, SEMANTIC_VIDEO_MAX_FRAMES)` frames, default at
   most 8. A ten-minute upload, the longest visual assets allow, costs at most 8 model runs.
2. **Candidates:** twice the target, evenly spaced after a short edge margin (`min(0.25 s, 5 %)`)
   where fades and black leaders live. Times come from the validated probe and are formatted by
   the module only.
3. **Extraction:** one FFmpeg call per candidate, as an argument list with a timeout:
   - fast seek, one frame;
   - display orientation and square pixels;
   - at most 640 px wide;
   - written to the attempt workspace.

   A candidate FFmpeg cannot decode is skipped.
4. **Filtering:** deterministic and lightweight; this is not a scene detector.
   - Nearly black frames (dark *and* low contrast) are dropped; a night scene with lights is kept.
   - Completely flat frames are dropped.
   - Near-duplicates are dropped (16 × 16 greyscale thumbnails, mean absolute difference below 4).
5. **Selection:** an evenly spaced subset when more frames survive than the target.

Each kept frame stores its own vector and **time**.

**Aggregation:** an asset's similarity to a query is its **maximum** frame similarity, so a short
relevant scene is never averaged away. That frame's time is `best_frame_time`.

In acceptance:

- a 9 s video with a 1 s black intro, a city scene and a rocket scene kept 5 frames (1.5 to 8.3 s);
- a 10 s video made of two still shots kept 2 frames (duplicates dropped).

## Vector storage

PostgreSQL with **pgvector**:

- The migration creates the extension.
- `visual_asset_embeddings.embedding` is `vector(512)`; the database itself refuses other
  lengths, NaN and infinity.
- Deleting an asset or project cascades to its indexes and vectors. Vectors are not storage
  objects, so media cleanup is unchanged.

Search is always scoped to **one project and one identity**, so it is an exact scan (btree on
index and asset, `DISTINCT ON (asset)`, pgvector cosine distance) rather than an approximate
nearest-neighbour index over every project. It is exact, isolated per project, and fast at
library sizes (below).

**Deployment:**

- `deploy/postgres.Dockerfile` is the stack's own `postgres:16-alpine` plus pgvector 0.8.7
  built from its pinned release. Staying on Alpine keeps existing data volumes on the same C
  library and collations.
- CI and local Docker use the official `pgvector/pgvector:pg16`.
- A local PostgreSQL needs pgvector installed (`brew install pgvector`, or build it for your
  server version).

## Search ("Search your visuals")

`GET /projects/{id}/visual-assets/search?q=…&kind=&limit=` (owner-only, rate-limited):

1. **Query:**
   - The text is cleaned: control and format characters removed, whitespace collapsed, NFC,
     at most 100 characters. Input over 200 characters, or empty after cleaning, gives 422.
   - It is embedded inside the model's prompt template ("a photo of {query}").
   - Query vectors are cached in a bounded per-process LRU.
2. **Visual similarity:** one exact scan over this project's ready vectors of the current model,
   keeping each asset's best frame.
3. **Metadata:** the V1.1 word matcher still counts (tags > name > description), so an exact tag
   stays useful with or without the model.
4. **Hybrid tiers:** an asset's strength is the better of its visual tier and its metadata tier.
   - Visual tier: the model's versioned thresholds.
   - Metadata tier: ≥ 0.9 is strong, ≥ 0.5 is possible.
   - Below both, an asset is **not a match** and is not returned.
5. **Order:** strong before possible, then a combined score (the better signal scaled between its
   cut-offs, plus a small bonus when both agree), then raw similarity, then the newest asset.

The response carries, per result:

- the asset;
- `match: {strength, method: visual | metadata | visual_and_metadata, best_frame_time}` (the
  time only for videos matched by what they show).

It also carries `visual_search_used` and `assets_preparing`. Vectors, similarities and scores
are never returned.

## Confidence tiers and thresholds

| Model | Strong | Possible | Version |
|---|---|---|---|
| CLIP ViT-B/32 (`clip_onnx`) | cosine ≥ **0.27** | ≥ **0.23** | `clip-b32-v1` |
| deterministic fake (tests) | ≥ 0.6 | ≥ 0.4 | `fake-v1` |

They were calibrated with the **semantic benchmark** (`scripts/semantic_benchmark.py`):

- **Assets:** 23 public-domain or CC0 photos and 2 generated two-scene videos, untagged, with
  camera-style names.
- **Queries:** 20 positive queries across 6 concepts (direct, related, contextual) and
  5 negative queries.

Results:

- **Ranking:** a relevant asset ranked first for **20/20** positive queries (top-3: 20/20).
- **At the provisional cut-off (strong ≥ 0.26):** one false strong match. "Driving to work in
  the morning" scored 0.265 against a snowy-mountain photo. Strong therefore starts at 0.27,
  with a margin.
- **At 0.27 / 0.23:**
  - all 20 relevant assets found, 18 of them strong;
  - **0 false strong matches**;
  - **5/5 negative queries quiet**;
  - 15 false *possible* matches, which rank below the relevant ones and are only offered.

These are **similarity cut-offs for this model, not probabilities**. Another model gets its
own, separately calibrated entry.

## B-roll matching

`semantic/matching.py` replaces word-only matching for B-roll suggestions:

- Every suggestion's query goes through the same hybrid ranking, with at most 3 matches each.
- The B-roll API keeps `matches` (asset ids, strongest first) and adds
  `match_details: [{asset_id, strength, method, best_frame_time}]`.
- **Strong** matches may be placed automatically; **possible** ones are offered.
- The creator can always pick any other asset.

**Scene offset.** `asset_offset(best_frame_time, element_seconds, video_seconds)` centres an
element on the matched scene. For example, a scene at 8.4 s with a 2.5 s element starts at
7.15 s. It is clamped to `[0, video − element]` and rounded **down**, so there is never a black
tail. Images and word matches start at 0. The editor applies the same rule (`sceneOffset`) when
a creator places a video found by what it shows.

## Auto Edit integration

- Planners see, per suggestion, matching assets with a **category** and, for videos, a scene.
  For example:
  `{"asset": "visual_asset_1", "strength": "strong"}` or
  `{"asset": "visual_asset_2", "strength": "possible", "best_scene_start": 4.2}`.

  They never see decimals: a small model should not reason about cosine values (planner
  contract `auto_edit_planner_v2`).
- The Ollama prompt allows **strong pairs only**.
- The deterministic fallback places strong matches only, so semantic matching is not Ollama-only.
- **The server stays authoritative:**
  - a possible match chosen by a planner is refused, with a creator-facing note;
  - a video's offset is computed by the server, never by the model;
  - the visual explanation says how the asset matched, for example "Matched this image to
    “bridge crashing onto table” by what it shows." Never a score.
- **Abstention:** when nothing matches strongly, no visual is placed. The plan says "No project
  visual strongly matched a B-roll suggestion; possible matches are offered in the editor."
- **Fingerprint:** plan fingerprints include each asset's visual-search state and the matching
  model only when present, so V1.2-shaped facts keep their fingerprints and a plan made before
  an asset became searchable is not reused afterwards.

## The editor and the library

- **Library:**
  - "Search your visuals", with the hint "Search by what's in the image or video";
  - **Strong match** and **Possible match** chips, with the reason in the accessible name;
  - a video's **Best at 0:08**, and its preview opens at that scene;
  - "Visual search is still preparing…" when relevant; a name, description and tag fallback if
    search is unavailable.
- **Card states:** cards are marked only while **Preparing visual search** or when **Visual
  search unavailable**. The preview explains the state (with real progress for videos) and
  offers **Retry visual analysis**. The list refreshes quietly while anything is preparing.
- **B-roll suggestions:** **Best matches**, each with a thumbnail, a tier, *Matched visually to
  “…”* or *Matched by its name or tags*, a video's best scene, **Preview** (seeks to the scene)
  and **Use**.
- **Asset chooser:** it opens with the suggestion's words in its search box (clearable), searches
  the library by content, and places a video at its matched scene.

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/projects/{id}/visual-assets` | each asset carries `visual_search: {state, frames_done, frames_total, message, can_retry}` |
| GET | `/projects/{id}/visual-assets/search?q=&kind=&limit=` | hybrid search; `visual_search` rate limit (600 per hour per user) |
| POST | `/projects/{id}/visual-assets/{asset_id}/visual-search/retry` | analyse again without re-uploading; `visual_analysis` rate limit (100 per hour per user) |
| GET | `/projects/{id}/videos/{v}/clips/{c}/broll` | suggestions with `matches` and `match_details` |

States: `unavailable` (off on this server), `not_indexed`, `queued`, `indexing`, `ready`,
`failed`, `stale`.

## Privacy and security

- **Local only:** pixels and frames never leave the server.
- **Isolation:** every endpoint is owner-scoped (404 for others). Search and matching scan only
  the project's own ready vectors of the current model. Reused vectors never cross owners.
- **Never exposed:** responses carry no vectors, similarities, scores, model names, cache or
  model locations, task ids or hashes. Logs carry no pixel data, vectors or server paths. All of
  this is tested.
- **The model is a closed box:** its input is validated, decoded pixels (never a path or URL);
  its output is validated before storage; its files are pinned and verified. Model text never
  reaches FFmpeg, paths or ids.
- **Bounded work:**
  - query length, result counts, frames per video (and FFmpeg calls), batch size, image size;
  - retries (attempts and a rate limit) and lazy re-queues per listing;
  - the upload and search rate limits.

## Performance

Measured on an Apple-silicon laptop (CPU, 2 threads), the real model, PostgreSQL 14 with
pgvector 0.8.7. These are local measurements, not cloud benchmarks.

| What | Measured |
|---|---|
| Text encoder: first query in a process (loads the encoder) | ~0.4 s |
| Text encoder: a new query once loaded / a repeated query | ~32 ms / ~0 ms |
| Scoped scan: one project's 1,600 vectors among 81,600 stored | median 7.7 ms |
| Search end to end through the HTTPS proxy (warm) | ~40 ms |
| Image indexing | ~80 ms (first job ~0.5 s: loads the image encoder) |
| Video indexing (9–10 s B-roll) | ~1.4–1.6 s |
| Upload → searchable (production-mode stack) | 0.3 s images, 1.6–1.8 s videos |
| Memory | API process +~0.5 GB (text encoder only); worker ~1 GB peak (both encoders) |

**Where the model runs:**

- **Workers** load both encoders on their first indexing job: one copy per worker process.
  Keep one job per process, or route `SEMANTIC_QUEUE=semantic` to a dedicated worker
  (`-Q semantic --concurrency 1`).
- **The API** loads only the text encoder, on the first search, and reuses it for the life of
  the process. Interactive search therefore avoids a Celery round trip. Size `WEB_CONCURRENCY`
  for about 0.5 GB per process, or set `SEMANTIC_PROVIDER=disabled` on very small hosts.

`scripts/semantic_search_probe.py` reproduces the timings on an empty scratch database.

## Reindexing

| Need | How |
|---|---|
| A failed asset | the creator's **Retry visual analysis**, or `reindex --failed` |
| After a model change | automatic and bounded per library listing, or `python -m app.cli.semantic reindex` (stale and never-indexed, `--limit`, `--project`, `--dry-run`) |
| Status | `python -m app.cli.semantic status` (assets per state for the current model) |

The command only enqueues jobs; workers embed.

## Testing

- **Standard CI never downloads model weights.** It runs everything on the deterministic fake
  provider (`SEMANTIC_PROVIDER=fake`): a colour-to-concept palette, labelled fake and refused in
  production.
- **Suites:**
  - `test_semantic_domain`, `_provider`, `_indexing`, `_video`, `_lifecycle`, `_search`,
    `_broll_matching`, `_management`, `_performance`, `_hardening`, `_benchmark`, `_ci_matrix`
    (index, search and match on moto and the live MinIO);
  - `test_auto_edit_semantic`;
  - frontend `lib/visual-search.test.ts`.
- **Benchmark:** `python scripts/semantic_benchmark.py` runs in CI with safety gates: no false
  strong match, every negative query quiet, every first result relevant. The real-model run is
  local acceptance: `--model-dir … --media … --calibrate`.
- **Opt-in real model:** `pytest -m real_model` with `PEAKSIFT_REAL_SEMANTIC_MODEL_DIR`.
- **Acceptance (production-mode stack, real model, real Ollama):** 22/22. Visual and UX
  acceptance at 1440, 1024, 768 and 375 px: 153/153.

## Known limitations (V1.3)

- Semantic similarity is **not factual understanding**. A visually similar picture can be wrong
  for the context: a bridge photo "matches" a sentence about a bridge collapsing even though it
  shows an intact bridge (that match is only *possible*).
- Long videos are represented by **sampled frames** (at most 8). A brief moment between samples
  can be missed, and a still-shot video may keep only one or two frames.
- Results depend on the content and the model. CLIP ViT-B/32 is good at common objects and
  scenes, and weaker at abstract ideas, small details, text in images and specific places or
  people.
- There is **no** internet or stock search, **no** generated media, **no** facial identity
  matching or OCR, and **no** object tracking.
- The thresholds were calibrated on a small, documented benchmark. They are cut-offs, not
  probabilities, and a different model needs its own calibration.
- Library cards show the asset's usual thumbnail, not the matched frame; the scene time is shown
  and the preview opens there.
- Each API process holds about 0.5 GB for the text encoder once it has served a search.
- Manual creator review remains important: Auto Edit places only strong matches, and the creator
  decides what ships.
