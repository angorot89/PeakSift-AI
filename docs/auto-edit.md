# Auto Edit (V1.2)

Auto Edit turns a generated clip into a **reviewable first draft** of a short: PeakSift reads
what it already knows about the clip, a planner chooses options inside a creator recipe, the
server checks every choice, and the creator reviews the plan — then uses it, adjusts it in the
editor, or tries another. A plan is an ordinary edit configuration; the existing renderer
renders it.

Status: **V1.2 implementation complete locally — pending CI/merge/release.** The work is on
stacked pull requests that wait for GitHub Actions; it is not released.

## What it does, and does not do

Does:

- Chooses framing, caption style and position, an opening hook, B-roll cutaways or
  picture-in-picture from the creator's own matching assets, and the audio finish (levels,
  the creator's chosen music, ducking, transition sounds) — inside one of four recipes.
- Explains each choice in a short sentence, and says what it left out and why.
- Works without a language model: when the local model is offline, slow or malformed, a
  deterministic planner makes a conservative plan, and the plan says so.
- Keeps the creator in control: nothing renders until the creator chooses **Use this edit**;
  **Edit choices** opens the plan's settings in the normal editor.

Does not:

- Publish anything, or decide anything the creator cannot change.
- Start other jobs. It uses the framing analysis, word timing and B-roll suggestions that
  already exist; the editor offers those separately.
- Pick music on its own, search or download media, generate images, video, music or sound,
  or invent assets, names, numbers or claims.
- Predict performance. There is no "viral" or quality score anywhere.

## Architecture

```
Clip + transcript + candidate + word timing + framing + B-roll suggestions + project assets
  → sources.gather (completed inputs only; handles instead of ids)      ─┐
  → planner: local Ollama model (bounded) or deterministic rules         │ Celery
  → validate_plan (server): handles → ids, recipe bounds, existence     │ peaksift.plan_auto_edit
  → AutoEditPlan ready: EditConfig snapshot + explanations + confidence ─┘
creator reviews → apply → create_or_reuse_edit (same checks as the edit API) → normal ClipEdit
  → existing renderer
```

| Area | Code |
| --- | --- |
| Model | `app/models/auto_edit.py` (`AutoEditPlan`) |
| Inputs and fingerprint | `app/services/auto_edit/sources.py`, `fingerprint.py`, `config.py` |
| Recipes | `app/services/auto_edit/recipes.py` |
| Planner contract | `app/services/auto_edit/contract.py` |
| Local planner | `app/services/auto_edit/ollama.py`, `planners.py` |
| Deterministic planner | `app/services/auto_edit/fallback.py` |
| Server validation | `app/services/auto_edit/validation.py` |
| Pipeline and state | `app/services/auto_edit/pipeline.py`, `state.py`; `app/workers/auto_edit_tasks.py` |
| API | `app/api/auto_edit.py` |
| Quality check | `app/services/auto_edit/benchmark.py`, `scripts/auto_edit_benchmark.py` |
| Frontend | `components/app/auto-edit-view.tsx`; `lib/auto-edit.ts`, `lib/auto-edit-rules.ts`, `lib/edit-draft.ts`, `lib/project-clip.ts` |

Migration: `b981abf316d9` (auto edit plans).

## AutoEditPlan

One planning run for a clip:

- `recipe`, `recipe_version`, `planner_version`, `planner_provider`, `planner_model`,
  `fallback_reason` (why the rules stood in), `generation` ("try another plan" makes the next);
- `config`: the request snapshot (recipe and exact version, planner, model, fallback switch,
  an explicit music choice, generation) — server values except the recipe and the track;
- `source_fingerprint`: everything the plan depends on (below); `(clip_id,
  source_fingerprint)` is unique, so the same request with the same inputs returns the
  existing plan;
- `status`: `queued → analyzing → planning → validating → ready → applied`, or `failed`;
  `progress_percent` is stage-based (5, 15, 35, 85, 100), never a fake percentage;
- once ready: `configuration_snapshot` (an `EditConfig` snapshot) and its fingerprint,
  `explanation_snapshot` (per section `choice` and `reason`, plus `notes`), and
  `confidence_summary` (local AI or rules, fallback, framing confidence, word and phrase
  timing, B-roll method, suggestion and match counts);
- applied: `clip_edit_id` and `applied_at`. An applied plan never changes; deleting its edit
  empties the reference and keeps the plan.

The database insists that a ready or applied plan holds its whole result and that
`applied ⇔ applied_at`. Deleting a clip deletes its plans.

### Source fingerprint

`PlanSources` covers the clip and its rendered file, the transcript lines, the current word
timing track, the current framing analysis and its confidence, the current B-roll analysis and
its non-dismissed suggestions, every visual asset's name, description, tags and geometry, the
chosen music and the transition sounds — plus the request. No timestamps. A new caption track,
a tagged asset, a dismissed suggestion, another recipe, a recipe version or a regeneration
makes a new plan; earlier plans are kept.

### Attempt ownership

Every job uses the PeakSift fencing pattern: the task id committed before enqueueing is the
attempt token; claiming ignores finished, failed, live and superseded rows and takes over stale
ones (`AUTO_EDIT_STALE_AFTER_SECONDS`); every write re-checks the token, so a stalled worker
never writes after a retry took over; a plan deleted mid-run (its clip was removed) stops the
job; the result is written in one commit.

## Recipes

Recipes are **preferences and bounds**, not fixed output: a planner chooses inside them and may
choose less (no hook, no visual, no music). Every bound is a value the editor and renderer
already accept (tests prove it). Versions (`punchy_v1`) are stored on each plan, so improving a
recipe never changes an old plan.

| Recipe | Framing | Captions | Hook | Visuals | Music | Sound effects |
| --- | --- | --- | --- | --- | --- | --- |
| Clean | Smart Reframe at high confidence | Focus, Minimal or Boxed · bottom | Minimal or Headline, ≤ 2.5 s | ≤ 2, cutaway or PiP, fade, 4 s apart | quiet / low | none |
| Punchy | Smart Reframe at high or mixed | Punch or Boxed · bottom or centre | Headline or Boxed, ≤ 2.5 s | ≤ 4, cutaway or PiP, quick cuts, 2.5 s apart | low / medium | ≤ 2 transition sounds |
| Story | Smart Reframe at high or mixed | Focus or Minimal · bottom | Minimal or Headline, ≤ 2.5 s | ≤ 3 cutaways, fade 0.4 s, ≥ 2 s holds | quiet / low | none |
| Minimal | Smart Reframe at high | Minimal · bottom | Minimal, ≤ 2 s, optional | ≤ 1 cutaway | quiet only | none |

Music levels map to dB on the server (quiet −24, low −20, medium −16). Picture-in-picture
always sits in a top corner, clear of bottom captions. Overlays remain a manual choice.

## Planners

The planner is server configuration (`AUTO_EDIT_PLANNER_PROVIDER`: `ollama` or `fallback`);
clients choose only a recipe and, optionally, one of the project's music tracks.

### Contract

A planner receives an `AutoEditContext` — facts only: the timed transcript, the candidate's
title and hook, the source orientation, explicit **capabilities** (Smart Reframe available and
how confident, word or phrase timing, whether text and visuals can be drawn), the recipe's
bounds, the validated B-roll suggestions with their matching assets (and which matches are
strong), the chosen music track and transition sounds. Everything addressable has a **symbolic
handle** (`suggestion_1`, `visual_asset_2`, `music_1`, `sfx_1`); the real ids stay on the server.

It answers an `AutoEditProposal`: strict JSON (unknown keys refused) of creator-level choices —
framing mode, caption preset and position, hook text/style/seconds, visuals as (suggestion,
asset, mode) handles, music level, ducking, whether to use transition sounds — and one short
explanation per section. It cannot express ids, paths, URLs, coordinates, filters or raw dB.

### Local model (Ollama)

`AUTO_EDIT_OLLAMA_MODEL` (empty: the first `OLLAMA_CLIP_MODELS` entry) answers the proposal's
JSON schema at temperature 0. The system prompt asks for an editor, not a marketer: keep speech
clear, prefer Smart Reframe when it is available, add a visual only when it helps its line,
build the hook from the speaker's words or the candidate hook, invent nothing. The user prompt
also states **this clip's constraints in plain sentences** (Smart Reframe available or not, the
recipe's presets, the only allowed suggestion/asset pairs or "visuals must be []", whether music
and transition sounds may be used) — the quality check showed this removes invented handles
from a small model's answers. Bounded: one request plus one corrective request for malformed
JSON, within `AUTO_EDIT_TIMEOUT_SECONDS` (default 120). Failures (unreachable, timed out, model
not installed, malformed) become planner errors with safe messages.

### Deterministic planner

Used when the model cannot answer (with `AUTO_EDIT_FALLBACK_ENABLED`, default on) or when it is
the configured planner. It is conservative and the same context always gives the same plan:
Smart Reframe when the analysis is confident enough for the recipe, otherwise the source
geometry (portrait or square: centre crop; landscape: blur background); captions whenever there
is timing; the candidate's own hook when it fits (never new text); at most one cutaway, only for
a suggestion with a strong matching asset long enough for the recipe; music only from the
creator's choice, at the quietest level; no sound effects.

## Server validation

`validate_plan` turns any proposal into a normal `EditConfig` using only what the server knows
exists. Handles become ids here and nowhere else; invented handles and real assets attached to
a suggestion they do not match are refused and counted. An invalid **optional** choice is
replaced by the safe one (or left out) with a plain note; only a proposal that forms no valid
configuration is refused (the pipeline then validates the deterministic plan instead).

| Section | Checks | When invalid |
| --- | --- | --- |
| Framing | Smart Reframe needs a completed, current analysis at a confidence the recipe accepts | source geometry |
| Captions | preset and position in the recipe; word timing needs a completed current track | recipe default; phrase timing; none |
| Hook | control/format characters removed, ≤ 60 characters, fits on screen; **grounded**: most content words were said, no new names, no unsaid numbers; not the first caption repeated; style and seconds in the recipe; never the captions' position | the candidate's own hook, otherwise none |
| Visuals | a known suggestion and one of its matching assets; recipe modes, count, hold and gap; no overlap or clash; the asset can fill the moment | left out, with a note |
| Audio | music only from the creator's chosen track and when the recipe allows; recipe levels and ducking; transition sounds only at cutaway starts from an available effect, at −10 dB | left out, with a note |

Explanations are product copy: a planner's sentence is kept only for a section accepted
unchanged and only when it reads as a sentence — no handles, identifiers or URLs, no internal
vocabulary (candidate, handle, schema, JSON, proposal, planner), and for audio, music is
mentioned exactly when the mix has music; otherwise the server writes it. Explanations never
contain an id.

## Applying a plan

`POST …/auto-edits/{id}/apply` creates (or reuses) a normal `ClipEdit` through exactly the same
checks as the edit endpoint — every asset is checked again for ownership and kind — and records
it on the plan. Applying twice returns the same edit; an identical manual edit is reused. The
plan's used B-roll suggestions are recorded as accepted (history). A plan whose version was
deleted cannot be applied again (it never changes); its settings can still be opened in the
editor.

## Editor hydration

The editor opens with stored settings instead of defaults:

- `?edit=<id>` ("Use this edit"): that version's exact settings, with the version shown (or
  followed while it renders); an unknown version falls back to the newest;
- `?plan=<id>` ("Edit choices"): the plan's settings, not rendered;
- otherwise the newest version.

`lib/edit-draft.ts` maps a configuration onto the editor (layout, focal point, captions, hook,
audio including a "normalize only" section, visuals) and says when something cannot be
reproduced exactly (a classic V0.6 caption style; framing or word timing regenerated since).
Hydration happens once; any change the creator makes before the stored settings arrive wins.
**Reset to defaults** resets deliberately.

## B-roll and audio behaviour

- A suggestion counts as **used** only while a current visual covers at least half of its
  moment; removing the visual makes it available again. The server's `accepted` status is
  history.
- Auto Edit only places a visual for a suggestion with a matching project asset; without one it
  says "No project asset matched this B-roll suggestion".
- Music is never chosen by Auto Edit. A track chosen for the plan is mixed at a recipe level,
  ducked under speech; several tracks in the project change nothing.
- Transition sounds are added only by the Punchy recipe, only at cutaway starts, and only from a
  project sound effect whose name marks it as a transition (whoosh, swoosh, transition…).

## API

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/auto-edit/recipes` | name, version, label, description |
| `POST` | `/projects/{p}/videos/{v}/clips/{c}/auto-edits` | `{recipe, music_asset_id?}`; existing plan for equal inputs (200) or a new one (201); rate limited (`auto_edit`, 60/hour) |
| `GET` | `…/auto-edits`, `…/auto-edits/{id}` | newest first; status, configuration, explanations, confidence |
| `POST` | `…/auto-edits/{id}/retry` | failed or stalled plans; fresh attempt token |
| `POST` | `…/auto-edits/{id}/regenerate` | "Try another plan": the next generation; old plans kept |
| `POST` | `…/auto-edits/{id}/apply` | a normal edit (rate limited like rendering) |

401 without a session, 404 for anyone else's clip or plan, 409 when the clip is not ready or
its file is missing, 503 when storage or the queue is unavailable. Responses never contain
prompts, model output, model names or server addresses, task ids, fingerprints, storage keys
or handles.

## Security

- The model proposes; the server decides. Model output never becomes a filter, path, id,
  provider name, caption style, coordinate or volume: every value maps onto an allow-list.
- Hooks and explanations are untrusted text: cleaned (NFC, no control or format characters),
  bounded, grounded, and drawn through the caption renderer's escaping.
- Ownership is checked at every step (assets come only from the clip's project; apply checks
  again); another user's resources are a 404.
- The planner endpoint and model are operator configuration; nothing about them reaches the
  browser.

## Testing

- Backend suites: domain, fingerprint, state (fencing), recipes, contract, local planner
  (mocked HTTP), fallback, validation, pipeline, API, hardening, quality check and a CI matrix
  that renders plans through the real renderer and runs plan → apply → render on MinIO.
- `python scripts/auto_edit_benchmark.py` (rules, in CI) and `--planner ollama` (local model):
  six representative clips × four recipes, objective measures only (valid, replaced choices,
  invented handles, grounded hooks, visual relevance, effect density, fallback).
- Frontend unit tests for the display rules, editor hydration, suggestion use and the asset
  chooser; real-stack and visual/UX acceptance in a browser.

No test downloads a model or media; CI runs no model.

## Known limitations (V1.2)

- Quality depends on what is prepared: without framing analysis, word timing or B-roll
  suggestions, plans are simpler (the review lists what to prepare).
- The small local model's choices are sensible but conservative; it can still prefer an
  option a creator would not choose. Hooks are limited to the clip's own words.
- Matching is word-based (tags, names, descriptions): untagged assets are rarely matched.
- Transition sounds are recognised by file name only.
- An applied plan whose version was deleted cannot be applied again (open its settings
  instead).
- Versions made with an older framing analysis or word timing open with the current ones (the
  editor says so).

## Since V1.3: semantic asset matches

Auto Edit's B-roll matches now include what each asset *shows* (local embeddings), not only its
words. Planners see each match as **strong** or **possible** (never a number); only strong matches
may be placed, a video starts at its matched scene (offset computed by the server), and when
nothing matches strongly no visual is added. The planner contract is `auto_edit_planner_v2`. See
[semantic-assets.md](semantic-assets.md#auto-edit-integration).
