# Performance Analytics & Learning (V1.4)

PeakSift shows creators how the shorts they published from PeakSift are doing on YouTube, and
which of their own editing choices have **tended to go with** stronger results in their recent
uploads. It is observational analytics over the creator's own videos:

- figures are what YouTube reported, labelled with where they came from; **a figure YouTube did
  not report is shown as "—", never as 0**;
- comparisons use the same early windows for every short and the creator's own median, never
  other creators' data;
- patterns are associations, never causes, and are reported only when they pass a corrected
  significance test; with too little data the answer is **"No reliable pattern yet"**;
- nothing predicts how a short will do. There are no virality or performance scores.

Operator setup: [youtube-setup.md](youtube-setup.md#analytics-optional-v14). Creator guide:
[user-guide.md](user-guide.md#analytics--how-your-published-shorts-are-doing).

## Pieces

| Piece | Where |
| --- | --- |
| Published content, snapshots, daily metrics, syncs | `app/models/performance.py` |
| Provenance (how a short was made) and linking from the publish job | `app/services/performance/provenance.py`, `content.py` |
| Metric definitions and the reporting day | `app/services/performance/metrics.py` |
| Explicit analytics permission upgrade | `app/services/publishing/youtube_oauth.py`, `app/api/publishing.py` |
| Provider contract, YouTube Data + Analytics, deterministic fake | `app/services/performance/provider.py`, `youtube.py`, `fake.py`, `factory.py` |
| Sync job, schedule, backfill, operator CLI | `sync.py`, `lifecycle.py`, `app/workers/performance_tasks.py`, `app/cli/performance.py` |
| Totals, windows and the creator's baseline | `summary.py`, `normalization.py` |
| Creator insights (deterministic engine) | `insights.py`, `app/models/insight.py`, `scripts/insights_benchmark.py` |
| Auto Edit performance context | `profile.py`, `app/services/auto_edit/` (config, contract, ollama, fallback) |
| Deleting collected metrics | `retention.py` |
| API | `app/api/performance.py`, `/auto-edit/performance-context` |
| UI | `/analytics`, `/analytics/[id]`, Settings → YouTube → Analytics access, the Auto Edit composer |

## Permission: an explicit, read-only upgrade

Publishing asks for `youtube.upload` only, and still does. Reading metrics needs more, so the
creator asks for it separately: **Settings → YouTube → Connect analytics (read-only)** (also on
the Analytics page) starts a second consent for:

| Scope | Why |
| --- | --- |
| `youtube.upload` | already granted; asked again so the new token keeps publishing working |
| `youtube.readonly` | the video's live counters and status (`videos.list`) |
| `yt-analytics.readonly` | processed daily analytics (`reports.query`) |

- The flow is the publishing flow: PKCE S256, `access_type=offline`, single-use hashed state
  bound to the user, 10 minutes. The state stores its **purpose**; the callback never takes it
  from the request.
- Google lets the creator untick scopes, so **the grant is checked**. Only upload *and* both read
  scopes replace the stored token (the same AES-GCM store as publishing; no second credential
  store). A partial grant, a declined consent or an unticked upload change **nothing**: the
  existing connection is byte-for-byte unchanged and publishing keeps working. A newly issued
  but unused token is not revoked (that would revoke the creator's whole grant).
- Reconnecting for publishing asks for upload only again; analytics then shows as not connected.
- Access tokens are requested **per use with only that use's scopes**: publishing gets upload,
  analytics gets the two read scopes. Google's `invalid_scope` (a grant without a scope) is kept
  apart from `invalid_grant` (revoked or expired): only the latter asks the creator to reconnect.
- Until the upgrade, the UI says **"Analytics access not connected"** and explains what the
  permission allows (read-only; only PeakSift's own shorts are tracked; publishing unaffected).

## Data model

- **`PublishedContent`** — one remote video PeakSift published. Linked from the publish job the
  moment YouTube returns the video id (never by title), unique per `(provider, remote id)` and
  per job. Holds the user, project, clip, edit, applied Auto Edit plan and job (`SET NULL` when
  those are deleted), title, publication time, duration, privacy, `remote_status`
  (`active` / `remote_missing` / `unknown`), the sync schedule and the settled day.
- **Provenance** — an immutable snapshot of normalized features built at link time: duration,
  recipe, Auto Edit and planner, framing, caption preset/position/timing, hook (present,
  length in characters, duration, style — never its words), visuals by mode, audio (music,
  ducking, sound effects, normalization), semantic visuals, and the candidate's rank, editorial
  score and category. No transcript text, asset ids, file names or provider payloads.
- **`PerformanceSnapshot`** — one observation of live counters; **`PerformanceDailyMetric`** —
  one processed reporting day, unique per `(content, source, date, metric_version)` and upserted.
  Every metric is nullable: **NULL means not reported, 0 means YouTube reported zero.** The
  database refuses negative values; retention above 100% (replayed Shorts) is allowed.
- **`source`** is `youtube` or `fake` (the deterministic simulation, refused in production), so
  simulated data is always labelled and never compared with real data.
- **`AnalyticsSync`** — one sync attempt (history kept), at most one queued or syncing per video
  (a partial unique index), with a fencing task id, heartbeat and a safe error code.
- **`InsightSet` / `CreatorInsight`** — the latest insights per creator and source (below).

## What a "view" is (metric versions)

YouTube has redefined a view twice:

- **2025-03-31** — Shorts views count every start and replay; `engagedViews` (in the Analytics API
  from 2025-04-30) keeps the earlier method.
- **2026-08-27** — views of every format count from the moment playback begins (the Data API
  announcement gives 2026-08-24); `engagedViews` is unchanged.

Each daily row records the definition in force on its day (`youtube_views_legacy`,
`youtube_views_2025_03`, `youtube_views_2026_08`). Comparisons use **engaged views** (one
definition throughout) and retention; views are summed within a window only under one definition.

YouTube's processed analytics count days in **Pacific Time** and arrive about **2–3 days**
late; rows for days without data are omitted (never filled with zeros).

## Syncing

A sync (Celery `peaksift.sync_performance`, ids only through the broker):

1. checks the creator's grant (connected, both read scopes) — otherwise it fails without calling
   Google (`not_connected`, `reconnect_required`, `analytics_not_connected`);
2. decrypts the refresh token for this call only (never logged) and gets a read-only access token;
3. reads the live counters (`videos.list?part=statistics,status`, 1 quota unit) into a snapshot;
4. reads processed daily rows (`reports`: `ids=channel==MINE`, `dimensions=day`,
   `filters=video==<id>`) from the day of publication — or, once data exists, from three days
   before the settled day, because recent days are still revised — and upserts them;
5. advances `analytics_complete_through` to `min(last day returned, today − 3)`.

Columns are read **by name** from `columnHeaders`; every number is validated (non-negative
integers, finite averages, days inside the range, at most once) and nothing is repaired. Errors
are normalized (`authentication_required`, `analytics_not_authorized`, `api_not_enabled`,
`quota_exceeded`, `rate_limited`, `network_error`, `provider_error`, `invalid_response`);
Google's messages never reach logs or creators.

**A missing video.** When YouTube does not return a video, it becomes `unknown` and is checked
again a day later; only a second miss marks it `remote_missing`. Its history is kept, no "0
views" is recorded, and it is no longer scheduled (a creator's Refresh checks again).

**Failures** record a safe code; temporary ones (quota, rate limit, network, provider, invalid
response, API not enabled, stalled, queue unavailable, time limit) retry with a backoff of
1 h, 2 h, 4 h … 24 h; ones that need the creator wait for them. A refused grant marks the
connection `needs_reconnect`, as publishing does. A worker that stops reporting is replaced
(`stalled`) and its late writes are refused by the fencing token.

**Schedule.** Celery beat (`peaksift.schedule_performance_syncs`, every
`PERFORMANCE_SCHEDULE_INTERVAL_SECONDS`) starts a bounded batch of due videos of creators who
granted access. By age: every 6 h (< 2 days), 12 h (< 7 days), daily (< 30 days), every 3 days
(< 90 days), weekly (< 180 days), then never — a creator's Refresh still works (cooldown
`PERFORMANCE_MANUAL_COOLDOWN_SECONDS`, and a per-creator rate limit `analytics_refresh`).

**Backfill.** Right after a creator grants access, PeakSift links its own earlier uploads (from
the publish jobs — never other videos on the channel) and syncs them (20 now, the rest by the
scheduler).

## Comparable figures

Lifetime totals are not comparable, so every short is compared over the **same early windows**,
in reporting days from the day of publication:

| Window | Meaning |
| --- | --- |
| `day_1` | the day of publication — a partial day, so roughly the first 24 hours |
| `day_3` | the first three reporting days (≈ 72 hours) |
| `day_7` | the first seven reporting days (≈ one week) — the primary window |

A window is **complete** only when every day is settled and reported (including engaged views);
**open** while days are still processing; **incomplete** when settled days are missing — never
filled with zeros, never compared. Retention is weighted by each day's views.

**Baseline.** The creator's own median first-week engaged views and retention over their
comparable shorts (complete first week, one data source). Below **5** comparable shorts there is
no reliable baseline. A short's position (`above` / `near` / `below`, ±15% counting as near)
compares it with the median of the *other* shorts (leave-one-out).

## Creator insights

A deterministic engine (no model, no randomness) over the creator's 50 most recent comparable
shorts. For each editing feature from the provenance — Auto Edit or by hand, recipe, framing,
captions and their style, an opening hook, added visuals, music, length bucket, clip category —
and each figure (first-week engaged views, first-week average % viewed), it compares the shorts
*with* a value against the creator's other comparable shorts. A pattern needs:

- at least **10** comparable shorts and **5 on each side**;
- a two-sided **Mann–Whitney U test** (rank-based; exact for small samples without ties) that
  passes after a **Holm–Bonferroni correction across every comparison tested** (family-wise
  α = 0.05);
- one median at least **1.2×** the other (symmetric), consistency (≥ 60% of the group on the same
  side of the others' median) and stability (leaving out any one short keeps the difference).

At most five are kept. Confidence is **limited**, or **moderate** with 8+ shorts per side and a
corrected p < 0.01 — never higher. Statements are fixed templates: *"In your recent uploads,
shorts with an opening hook have tended to get more engaged views in their first week: median
5,960 vs 2,278 for your other shorts (8 vs 7 shorts)."* The page always adds: these are
associations, not causes; topic, timing and trends differ between shorts too; nothing predicts
how a short will do.

Insight sets are persisted per creator and source with an input fingerprint (recomputed only
when the comparable shorts change). Creators can hide an insight (kept across recomputation)
and see which of their shorts are on each side.

**Measured** (`python scripts/insights_benchmark.py`, synthetic libraries generated in memory
and never stored): on libraries with no real effect, at least one pattern appears in **2.7%** of
1,200 libraries (CI gate 6%); a ×3 effect is found in 100% of 40-short libraries and 22% of
12-short ones (σ 0.5). Without the correction the rate was 86–100% — which is why it exists.
Small libraries deliberately say "No reliable pattern yet" rather than guess.

## Auto Edit performance context

Optional per plan (**"Consider patterns from my published shorts"**, off by default). The
request stores a **profile snapshot**: the creator's visible insights about choices a planner
makes — caption style, captions on/off, hook, added visuals, framing — as symbolic hints
(feature, value, direction, confidence, group sizes). Never music (Auto Edit never picks music
on its own), never ids, titles or raw metrics.

- The local model sees `creator_history` with the rule: *weak evidence, not rules; the recipe
  and this clip come first; use one only to choose between options the recipe already allows.*
- The deterministic planner applies only safe, in-bounds hints and names each in its
  explanation: a caption preset the recipe offers; leaving out the hook or a cutaway when the
  creator's shorts without one did better. It never turns captions off, changes framing or adds
  music because of a hint.
- The server validator is unchanged. Without the toggle, requests and fingerprints are exactly
  as in V1.2/V1.3.

## Privacy and control

- Every endpoint is owner-scoped; responses never contain tokens, task ids, scopes or provider
  payloads; nothing is shared or aggregated across creators.
- **Delete collected metrics** (Settings, with a second confirmation; `DELETE /performance/data`)
  removes every snapshot, daily row, sync and insight of the creator and stops scheduled syncs.
  Disconnecting YouTube revokes the grant with Google and deletes the token.
- Logs carry ids and codes only — never tokens, titles, metrics or Google's messages. No
  audience demographics are requested.

## API

| Method and path | Purpose |
| --- | --- |
| `POST /publishing/youtube/analytics/connect` | start the read-only upgrade (Google's consent URL) |
| `GET /performance` | access state; every published short with counters, processed totals, windows and position; baselines |
| `GET /performance/videos/{id}` | daily rows per view definition, counter history, syncs, provenance |
| `POST /performance/videos/{id}/refresh` | `202` sync; `409` without the grant; `429` + `Retry-After` |
| `GET /performance/insights` | the creator's insight set (computed when inputs changed) |
| `POST /performance/insights/{id}/dismiss` · `/restore` | hide or show an insight |
| `DELETE /performance/data` | delete collected metrics and insights |
| `GET /auto-edit/performance-context` | whether patterns can inform Auto Edit, and which |

## Configuration

| Setting | Default | |
| --- | --- | --- |
| `YOUTUBE_ANALYTICS_ENABLED` | `false` | needs `YOUTUBE_PUBLISHING_ENABLED` |
| `PERFORMANCE_PROVIDER` | `youtube` | `fake` outside production only |
| `PERFORMANCE_SYNC_STALE_AFTER_SECONDS` | 900 | |
| `PERFORMANCE_MANUAL_COOLDOWN_SECONDS` | 900 | |
| `PERFORMANCE_SCHEDULE_BATCH` | 100 | due videos per scheduler run |
| `PERFORMANCE_SCHEDULE_INTERVAL_SECONDS` | 1800 | Celery beat |

Run one `celery -A app.workers.celery_app beat` per deployment (the Compose stack's `beat`
service), or `python -m app.cli.performance sync-due` from cron. Operator commands:
`python -m app.cli.performance status | sync-due | backfill --user ID`.

## Testing

Unit and API suites with a mocked Google and the deterministic fake (CI never calls Google and
has no Google credentials); the insights benchmark gate; a CI matrix on object storage. Local
acceptance: an isolated synthetic stack (18 simulated shorts, 170/170 browser checks at 1440,
1024, 768 and 375 px) and real-account checks with existing upload-only grants (publishing
still valid; Google refuses Data and Analytics reads → `analytics_not_authorized`).

## Known limitations

- The real analytics consent must be completed by a creator in their own browser; it was not
  exercised automatically. The operator must enable the **YouTube Analytics API** (and Data API)
  in the Google Cloud project, and add the two read scopes to the consent screen.
- `day_1` is a reporting day (Pacific Time), not exactly 24 hours.
- Insights compare features one at a time (marginal comparisons): strong co-varying choices can
  mask smaller ones, and patterns describe the past uploads of one creator only.
- Retention and engaged views are YouTube's definitions; PeakSift does not recompute them.
- No other platforms, no revenue, no audience demographics, no scheduling or automatic changes
  based on analytics.
