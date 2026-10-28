# Creator Copilot (V1.6)

*Ask PeakSift* is a contextual assistant inside PeakSift. It answers questions about the
creator's own projects — what to do next, which moment to start with, whether a visual fits,
what seems to be working — and offers safe product actions the creator clicks. It is not a
general chatbot: it only knows what PeakSift stores for this creator, and it never acts on its own.

## Context

`app/services/copilot/context.py` builds a **bounded, structured view** of the creator's data
for one question on one page:

- **Scope**: the workspace (Home, Projects, Analytics, Settings) or one project (Overview,
  Source, Moments, Create a Short, Auto Edit, Editor, Assets, project Analytics). Another
  creator's project or clip is refused (`404`).
- **Page-aware content**: the Overview gets the workflow (source, transcript, moments, Shorts,
  drafts); Moments the ranked moments with their reasons; the editor the current clip, its Short
  (layout, captions, opening, visuals, sound), its latest Auto Edit draft and its B-roll
  suggestions; Assets the visual library; Analytics the observed figures and patterns.
- **Symbolic handles**: every object the assistant may mention or act on is named `moment_1`,
  `short_2`, `visual_3`, `insight_1`… The handle → object map stays on the server. The model never
  receives ids, storage keys, paths, provider names, tokens or credentials.
- **Grounded figures only**: states, counts, times and editorial labels come from stored rows;
  an unreported figure is left out or `null`, never estimated. Editorial rankings are labelled as
  editorial judgement, analytics as observed figures.
- **Untrusted text is data**: transcript lines, titles, hooks and descriptions were written by
  people. They are collected as data (`transcript_excerpt`, object fields) and are never treated
  as instructions.
- **A visual question is searched**: when the question names something to show ("a visual for
  the bridge section"), its descriptive words are matched against the project's visuals with
  the same hybrid search as *Search your visuals* (strong / possible tiers).
- **Bounded**: at most 12,000 characters. Transcript lines go first, then catalogue entries;
  counts stay exact when lists are shortened.

`GET /copilot/context?page=&project_id=&clip_id=&edit_id=` returns what the panel shows as its
context label: the scope and a few facts ("Bridge Workshop · 3 moments · 6 visuals").

## Conversations and retention

`app/models/copilot.py`, `app/services/copilot/history.py`:

- **One conversation per project**, plus one for the workspace (Home, Projects, Analytics,
  Settings). The database enforces it (partial unique indexes). Moving between a project's
  pages keeps the same conversation; the context follows the page.
- **Only what the creator saw is stored**: their question, the assistant's final answer and
  optional suggestion, the page, the actions offered (type, target, server-written label) and
  the reference chips. Prompts, the context sent to the model and any hidden reasoning are
  never stored.
- **Bounded**: a conversation keeps its latest 200 messages; the model sees at most the last
  6 messages as plain text (answers PeakSift gave without the local assistant are left out).
- **Clear conversation**: `DELETE /copilot/thread?project_id=` deletes that conversation and
  nothing else. Deleting a project or an account deletes its conversations.
- `GET /copilot/thread?project_id=` returns the latest 50 messages. Another creator's project is
  a `404`.

## The local assistant (provider)

`app/services/copilot/provider.py`, `prompt.py`, `contract.py`, `service.py`:

- **Local by default**: `COPILOT_PROVIDER=ollama` asks the model at `OLLAMA_BASE_URL`
  (`COPILOT_OLLAMA_MODEL`, default the first `OLLAMA_CLIP_MODELS` entry; locally
  `llama3.2:3b`). Nothing leaves the server. `fake` gives deterministic answers for tests, CI and
  demos and is refused in production.
- **Instructions apart from data**: the system message holds PeakSift's rules; the creator's
  question is quoted; the project facts follow in a fenced `DATA` block described as
  information only. Transcripts, titles and descriptions inside it are never followed as
  instructions.
- **A strict answer**: JSON with `message` (the factual answer, in the question's language, 1–3
  sentences), an optional `suggestion` (shown apart, as a suggestion), up to 3 `actions` and up
  to 4 `references` — by handle only. PeakSift drops unknown action types, invented handles and
  handles of the wrong kind, replaces handle names in the text with real names, removes links and
  markdown, and writes every button and chip label itself.
- **Bounded**: temperature 0, the answer schema, at most 700 generated tokens, one corrective
  attempt when the reply is not JSON, all within `COPILOT_TIMEOUT_SECONDS` (45 s); questions of at
  most `COPILOT_MESSAGE_MAX_CHARS` (1,000); 6 questions per minute and 120 per hour per creator.
- **When it can't answer**: offline, too slow, model not installed or an unusable answer — the
  creator reads "PeakSift's local assistant isn't available right now." (or "couldn't give a
  usable answer this time"). The question is still saved, and nothing else in PeakSift depends
  on the assistant. `GET /copilot/status` reports whether it can answer now (checked at most
  every 30 s).
- `POST /copilot/messages` `{text, page, project_id?, clip_id?, edit_id?}` returns the saved
  question and answer. No database connection is held while the model thinks.

## Actions

`app/services/copilot/actions.py`, `app/services/routes.py`:

| Action | Target | Leads to |
| --- | --- | --- |
| `open_home`, `new_project`, `open_analytics` | — | Home, a new project, Analytics |
| `open_project`, `open_source`, `open_moments`, `open_assets`, `open_project_analytics` | a project | its Overview, Source, Moments, Visuals or Analytics |
| `search_assets` | a project + words | Visuals, searching for those words |
| `create_short` | a moment | *Create a Short* (the clip is created first if it does not exist yet) |
| `open_create`, `open_auto_edit`, `open_editor` | a clip, draft or moment | Create a Short, Auto Edit, or the editor |
| `open_short` | a Short | the editor on that version (preview, download, publish) |
| `open_published` | a published Short | its analytics |

- **Allow-listed**: the model proposes a type and a handle; nothing else is possible. No
  action publishes, deletes, disconnects, renders or changes settings.
- **Checked when offered**: the target must exist, belong to the creator and fit the step (a
  dismissed moment is never offered; "open the editor" on a moment without a clip becomes
  *Create Short*). Labels are written by PeakSift; repeated labels name their object.
- **Checked again when clicked**: `POST /copilot/messages/{id}/actions/{index}` re-validates
  ownership and state and returns where to go now — or `409` with "This moment is no longer
  available." (or Short, clip, draft, project, published Short). `create_short` returns the
  moment's ids so the frontend creates the clip through the normal clip API (its validation
  and rate limits apply), then opens *Create a Short*.

## Next best action (one source of truth)

`app/services/next_action.py` decides each project's next step from its real state
(`workspace_summary.project_summary`) with deterministic rules — no model decides the workflow:

| State | Next step |
| --- | --- |
| No source video / unreadable / being read | Add your long video · upload a different file · preparing |
| Not transcribed / transcribing / failed | Transcribe your video · transcribing · needs attention |
| Auto Edit draft ready (no Short yet) | Your Auto Edit draft is ready → Review the draft |
| A Short failed / rendering / ready | needs attention · rendering · Your Short is ready → Publish or download |
| Upload failed / uploading / published | needs attention · uploading · See how your Shorts are doing |
| A clip ready / being cut | Make your clip a Short → Create Short · preparing your clip |
| No moments yet / finding / none / some | Find the best moments · finding · No moments stood out · *N* moments ready to review |

Problems come first, then work in progress, then the next creative step. Each step carries its
link and the matching Copilot action. **Home's *Continue working***
(`GET /workspace/home` → `continue_items`), **the project Overview** (`GET
/projects/{id}/summary` → `next_action`) and **the Copilot** (`next_step` in its context; the
prompt tells the model to recommend that step) all read it, so "What should I do next?" and the
dashboard always lead to the same page. When the local assistant is unavailable, the answer still
offers PeakSift's own next step as a button.

## Content strategy

`app/services/strategy.py`, `app/services/copilot/ideas.py` — from the creator's own data only:
no web trends, no competitor data, no predictions.

- **Notes** (deterministic, shown to the model as `strategy.notes`):
  - unused moments in this video ("You have 2 moments in this video you haven't used yet
    (explanation, funny).");
  - variety against what the creator published recently ("You've published 3 insight Shorts
    recently. This video also has a funny moment: …");
  - the creator's own patterns about length, style or kind of moment, relayed with their
    observational wording plus "This is an observed pattern, not a prediction.";
  - and, when the history is small, exactly that: "Your current sample isn't large enough to
    recommend a length, style or kind of moment yet (3 of 10 comparable Shorts)." or "You haven't
    published from PeakSift yet, so there is no performance history to learn from."
- **Repeated work**: a moment already made into a clip, or already published, is marked
  ("Similar to a Short you've already published.") so it is not suggested as new.
- **Short ideas**: for an ideas question (detected in English, French, Arabic and Chinese), the
  model must return 3–5 ideas. Each is anchored in the video — a moment (by handle or exact
  title) or a time range whose start and end are transcript times in the context — otherwise it
  is dropped. PeakSift writes each card: the real time range, an angle from *Lesson, Story,
  Mistake, Reaction, Surprise, Explanation, Comparison, Opinion*, a style from *Clean, Punchy,
  Story, Minimal*, the reason, the repeated-work note, and *Create Short* for a moment.
- **Without the local assistant**, an ideas question still gets idea cards built from the
  video's best unused moments (angle and style from the moment's kind).
