# AI clip detection (Milestone 4)

How PeakSift turns a finished transcript into ranked, explained clip candidates. This page is the reference for operators and contributors; the end-user walkthrough is at the end.

## What it does — and does not — do

A **detection run** reads the video's completed transcript, asks an AI model (local Ollama or hosted OpenAI) to point at moments with short-form potential, re-checks every proposal against the transcript, deduplicates and ranks the survivors, and stores them as **clip candidates** with absolute timestamps, a title, a hook, a rationale, a category and five 0–100 scores. The user previews each candidate in the original video and saves or dismisses it.

It does **not** render or export clips, add captions, reframe to vertical, identify speakers, or predict performance. Scores are editorial judgement, normalised across providers — never a probability that a clip goes viral.

## Pipeline

```
POST …/clip-detection {provider, model}
  → ClipDetectionRun row (queued, config snapshot, transcript fingerprint, pre-chosen Celery task id)
  → enqueue peaksift.detect_clips(run_id)  →  201 at once

Worker (app/services/clip_detection/pipeline.py):
  claim (DB state + fencing token)
  → preparing_transcript   normalise lines, validate timeline, fingerprint must match the run    (progress 5)
  → analyzing              bounded windows → provider.analyze → validate per window              (5 → 80)
  → validating             transcript fingerprint re-checked                                      (85)
  → ranking                dedupe + weighted ranking                                              (90)
  → completed              every candidate row + status in ONE transaction                      (100)
  | failed                 error_code + safe error_message, no candidates
```

### Stage A — transcript preparation (`windowing.py`)

- `normalize_text`: control characters removed, whitespace collapsed, lines capped at 2000 characters; Unicode kept.
- `prepare_lines`: refuses non-finite, negative, inverted or out-of-order times and lines ending after the video (beyond `CLIP_DETECTION_TIMESTAMP_TOLERANCE_SECONDS`); drops empty lines; an all-empty transcript is `transcript_empty`. Nothing is repaired.
- `transcript_fingerprint`: sha256 over the transcription id and every `(start, end, text)` — the immutable snapshot reference stored on the run. If the transcript is re-generated, old runs report `transcript_current: false` and cannot be retried (start a new detection).
- `build_windows`: deterministic windows bounded by `CLIP_DETECTION_WINDOW_SECONDS` (300) **and** `CLIP_DETECTION_WINDOW_MAX_CHARS` (8000), overlapping by `CLIP_DETECTION_WINDOW_OVERLAP_SECONDS` (20) so a moment on a boundary is seen whole by one window; at most `CLIP_DETECTION_MAX_WINDOWS` (500). A 4-hour stream is ~50 bounded requests, never one unbounded prompt.

### Stage B — provider analysis (`contract.py`, `prompt.py`, `ollama_provider.py`, `openai_provider.py`)

One system prompt for every provider: editorial heuristics (unexpected outcomes, humor, reactions, tension, emotional peaks, payoff, explanations, strong openings, self-contained stories, memorable dialogue), "use only the transcript, never invent speech", "align start/end to the line timestamps", duration limits, JSON only. The user prompt renders the window as `[start → end] text` rows in absolute seconds plus the bounds, the allowed categories and the language.

Both providers must answer with the shared strict JSON schema (`AnalysisOutput`: a list of candidates with `start_seconds`, `end_seconds`, `title`, `hook`, `rationale`, `category`, five integer scores). The provider returns **raw** candidates — untrusted until Stage C.

| Provider | Where | Mechanism | Needs |
| --- | --- | --- | --- |
| `ollama` | your machine / an internal host | `POST /api/chat` with the schema as `format`, `temperature 0`, `num_ctx` ≥ 8192 | Ollama running at `OLLAMA_BASE_URL`, the model pulled (`ollama pull llama3.2:3b`) |
| `openai` | OpenAI API | `responses.parse` with `text_format=AnalysisOutput` (structured outputs) | `OPENAI_API_KEY`; models listed in `OPENAI_CLIP_MODELS` |

Users pick a provider **and** a model, but only from the operator's allow-lists (`OLLAMA_CLIP_MODELS`, `OPENAI_CLIP_MODELS`; first entry = default). The endpoint and the key are never client input and never appear in responses or errors.

### Stage C — validation (`validation.py`)

Deterministic corrections (precision, not editorial changes): start/end snap outwards to transcript-line boundaries inside the window; a clip over `CLIP_DETECTION_MAX_CLIP_SECONDS` (90) is shortened from the end to the last line boundary that fits; texts are normalised and truncated to their column limits (title 120, hook 300, rationale 1000) on a word boundary; unknown categories become `other`.

Rejections (trusting them would store something false): non-finite/negative/inverted times; ranges touching no line of the window or outside the video; shorter than `CLIP_DETECTION_MIN_CLIP_SECONDS` (15) after snapping; a single line longer than the maximum; any score that is not a whole number in 0–100 (**no clamping**); empty title/hook/rationale. Rejections are counted and logged with a reason, never stored.

The `transcript_excerpt` saved with a candidate is **our** transcript text inside the snapped range — a model's "quote" is never persisted.

### Stages D–E — scoring, deduplication, ranking (`ranking.py`)

`overall = 0.30·hook + 0.25·entertainment + 0.15·clarity + 0.15·payoff + 0.15·completeness`, rounded, 0–100. Order: overall desc → earlier start → shorter duration → title. Two candidates whose time ranges overlap by more than `CLIP_DETECTION_OVERLAP_THRESHOLD` (0.5, intersection over union) are duplicates and the better-ranked one wins. The top `CLIP_DETECTION_TARGET_CANDIDATES` (10) are kept with contiguous ranks. Zero survivors is a legitimate completed run.

### Reliability

- **Idempotent on database state**: completed → ignored; failed → ignored until the retry endpoint resets it; running with a fresh heartbeat → ignored; heartbeat older than `CLIP_DETECTION_STALE_AFTER_SECONDS` (900 — keep it above the slowest single-window analysis) → reclaimed; every (re)start deletes earlier candidates.
- **Fencing**: the Celery task id is generated and committed on the row *before* the job is enqueued; the worker re-reads it before every commit and stops if a retry handed the row to a newer task.
- **Retries**: transient provider errors (unreachable, timeout, rate limit, 5xx) get bounded exponential backoff in-task (`CLIP_DETECTION_PROVIDER_MAX_ATTEMPTS`, `CLIP_DETECTION_RETRY_BACKOFF_SECONDS`); configuration, model-not-installed and malformed-output errors fail immediately. Users may retry a failed or stalled run up to `CLIP_DETECTION_MAX_ATTEMPTS` (5) times, then must start a new one. A Celery soft time limit is recorded as `time_limit`.
- **Bounded controls**: one active run per video (query + partial unique index), bounded prompts and request counts, bounded retries.

## Data model

| Table | Columns |
| --- | --- |
| `clip_detection_runs` | `id`, `video_id` (FK, cascade), `transcription_id` (FK, cascade), `transcript_fingerprint`, `provider`, `model`, `config` (JSONB snapshot), `status`, `progress_percent` (0–100), `attempt` (≥ 1), `windows_total`, `windows_done`, `error_code`, `error_message`, `celery_task_id`, `created_at`, `updated_at`, `started_at`, `completed_at`, `heartbeat_at`. Partial unique index: one active run per video. |
| `clip_candidates` | `id`, `run_id` (FK, cascade), `video_id` (FK, cascade), `start_time`, `end_time`, `duration_seconds` (checked = end − start), `title`, `hook`, `rationale`, `category`, `transcript_excerpt`, `overall_score` + `hook/entertainment/clarity/payoff/completeness_score` (each checked 0–100), `rank` (≥ 1, unique per run), `decision` (`undecided` / `saved` / `dismissed`), `decided_at`, `created_at`, `updated_at`. |

Deleting a video removes its runs and candidates; deleting a transcription removes the runs derived from it. The source video is never modified by detection.

## API

All routes require the session cookie and are owner-scoped (anything else is `404`).

| Method | Path | Description |
| --- | --- | --- |
| GET | `/clip-detection/providers[?diagnose=true]` | Providers the user may choose: `name`, `label`, `models`, `default_model`, `configured`, user-safe `detail`; with `diagnose`, configured providers are probed and report `available`. |
| POST | `/projects/{id}/videos/{video_id}/clip-detection` | `{provider, model?}` → `201` run. `409` without a completed transcript / video not ready / another active run; `400` for a provider or model outside the allow-lists; `503` if the queue is down (no row left). |
| GET | `…/clip-detection?offset&limit(1–100)` | Runs, newest first. |
| GET | `…/clip-detection/{run_id}` | Status: `status`, `progress_percent`, `windows_total/done`, `attempt`, `candidate_count`, `is_stale`, `transcript_current` (null while active), `config`, safe `error_code`/`error_message`, timestamps. |
| POST | `…/clip-detection/{run_id}/retry` | Failed or stalled runs only; `409` if the transcript changed, another run is active, or the attempt limit is reached. |
| GET | `…/clip-detection/{run_id}/candidates?offset&limit(1–100)&decision=&view=` | Ranked candidates of a completed run (`409` before). `view=active` leaves dismissed ones out; `view=top` keeps the undismissed ones ranked first or scoring at least 75 (the "Strong moment" threshold). Every page carries `counts` (`active`, `top`, `saved`, `dismissed`) for the review filters. |
| GET | `…/candidates/{candidate_id}` | One candidate. |
| POST | `…/candidates/{candidate_id}/save` · `/dismiss` · `/reset` | Record the user's decision. |

A candidate is `{id, run_id, video_id, rank, start, end, duration, title, hook, rationale, category, transcript_excerpt, overall_score, scores{hook, entertainment, clarity, payoff, completeness}, decision, decided_at, created_at}`. Responses never include task ids, fingerprints, storage paths, endpoints or keys.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CLIP_DETECTION_OLLAMA_ENABLED` | `true` | Offer the local provider |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama-compatible endpoint (operator only) |
| `OLLAMA_CLIP_MODELS` | `llama3.2:3b` | Allowed local models, comma-separated; first = default |
| `OLLAMA_CONNECT_TIMEOUT_SECONDS` / `OLLAMA_TIMEOUT_SECONDS` | `5` / `300` | Connect / read timeouts per request |
| `OLLAMA_NUM_CTX` | `8192` | Context window requested per call (must hold the prompt + one window) |
| `OPENAI_API_KEY` | empty | Enables the hosted provider (shared with transcription) |
| `OPENAI_CLIP_MODELS` | `gpt-5-mini,gpt-5` | Allowed hosted models; first = default |
| `OPENAI_CLIP_TIMEOUT_SECONDS` / `OPENAI_CLIP_MAX_OUTPUT_TOKENS` | `120` / `4000` | Per-request limits |
| `CLIP_DETECTION_WINDOW_SECONDS` / `_OVERLAP_SECONDS` / `_MAX_CHARS` / `_MAX_WINDOWS` | `300` / `20` / `8000` / `500` | Analysis windows |
| `CLIP_DETECTION_MIN_CLIP_SECONDS` / `_MAX_CLIP_SECONDS` | `15` / `90` | Accepted clip length (min must be < max) |
| `CLIP_DETECTION_TARGET_CANDIDATES` / `_CANDIDATES_PER_WINDOW` | `10` / `3` | Results kept per run / asked per window |
| `CLIP_DETECTION_OVERLAP_THRESHOLD` | `0.5` | IoU above which candidates are duplicates |
| `CLIP_DETECTION_TIMESTAMP_TOLERANCE_SECONDS` | `1` | Allowed overrun past the video end |
| `CLIP_DETECTION_PROVIDER_MAX_ATTEMPTS` / `_RETRY_BACKOFF_SECONDS` | `3` / `2` | In-task retries for transient provider errors |
| `CLIP_DETECTION_STALE_AFTER_SECONDS` | `900` | Heartbeat age after which a running job counts as dead |
| `CLIP_DETECTION_MAX_ATTEMPTS` | `5` | User retries per run before a new detection is required |

## Local Ollama setup

```bash
brew install ollama            # or https://ollama.com/download
ollama serve                   # http://localhost:11434
ollama pull llama3.2:3b        # ~2 GB; the default allow-list entry
```

The worker never pulls or loads a model itself: if the configured model is missing, the provider reports "Model 'x' is not installed on the local inference server" and the UI shows it before you start. A 3B model runs comfortably on an Apple-silicon laptop (a 55-second transcript analyses in ~15 s); larger models improve judgement at the cost of time. Set `OLLAMA_CLIP_MODELS` to whatever you have pulled.

## Hosted OpenAI setup

Set `OPENAI_API_KEY` and, optionally, `OPENAI_CLIP_MODELS`. The provider uses the SDK's structured outputs so the API enforces the schema; models that do not support structured outputs surface as a clear request error rather than silent degradation. Transcript windows are sent to OpenAI — keep that in mind for sensitive recordings. The key is never logged, returned or shipped to the frontend; CI has no key and mocks the SDK.

## Security boundaries

- Provider/model are validated server-side against allow-lists; the Ollama endpoint and the API key are server configuration only.
- Only database ids cross the broker; the worker uses its own session.
- Model output is sanitised and bounded before storage; timestamps are always transcript boundaries inside the video.
- Transcript text that *sounds* like instructions ("ignore previous instructions…") is just text: validation and persistence never execute or trust it.
- Error messages stored or shown come from typed errors or fixed strings — no stack traces, paths, payloads or secrets.

## Testing

- Unit: models/migration, contract and schema, prompt, factory allow-lists, both providers (mocked transport / fake SDK client), windowing, validation, ranking, pipeline (idempotency, fencing, retries, failures, rollback), API (ownership, pagination, states, decisions).
- Integration: API → eager Celery → pipeline → candidates; the real Ollama provider over sockets against an in-process fake Ollama; a live worker smoke proving `peaksift.detect_clips` is registered.
- Opt-in real inference: `PEAKSIFT_REAL_OLLAMA=1 pytest tests/test_ollama_clip_provider.py -k real` against your local Ollama. CI points `OLLAMA_BASE_URL` at a closed port and holds no API key.

## Known limitations

- Windows are cut on time/character budgets, not topics; a story longer than one window may be seen in parts. Snapping is line-granular (no word-level alignment).
- Windows are analysed sequentially; a retry re-analyses everything (no window-level resume).
- Deduplication is temporal only; two candidates about the same topic at different times are both kept.
- Small local models propose misaligned or weak moments more often; validation drops them, which can leave few or zero candidates on short or repetitive transcripts.
- Candidates cannot be trimmed or retitled in V0.4; nothing is exported — that is Milestone 5.
- Preview precision depends on the browser's media-fragment and `timeupdate` behaviour (sub-second overshoot at the end).

## Using it (end-user guide)

1. Open a project, upload a video and wait for **Ready**.
2. Click **Transcribe video** and wait for the transcript.
3. In **AI clip detection**, choose a provider and model (unavailable ones say why) and click **Find clip moments**. The run queues at once; the page shows *Preparing transcript → Analyzing (window i of n) → Validating → Ranking* with real progress.
4. Review the ranked cards: title, time range, duration, overall score, hook, rationale, score breakdown and the transcript excerpt. **Preview** plays just that range of your video.
5. **Save** the ones you like, **Dismiss** the rest (both reversible); filter by Saved/Dismissed. Decisions persist across sessions.
6. If a run fails (for example the local model server is down), the message says why; **Retry detection** once it is fixed, or **Start a new detection** with another provider or model. After re-transcribing, run detection again — old candidates are flagged as belonging to a previous transcript.
