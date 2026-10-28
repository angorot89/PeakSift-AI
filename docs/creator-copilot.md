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
