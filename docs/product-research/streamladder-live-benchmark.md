# StreamLadder live benchmark

Inspected 26 November 2026 in the live StreamLadder web app (free plan, signed in), desktop and a
375 px viewport. Screens walked: Home, Streams, a stream's clip review page, the clip library
(New / Draft / Exported / Scheduled / Hidden), the review-and-post dialog, the Content Publisher
calendar, posting-time slots, Social connections and Editors.

**Not inspected:** the clip editor itself (preview, timeline, layouts, captions, overlays, audio,
templates, export). Opening it means importing a clip into the account, which was not done; the
editor rows below are marked *not seen* rather than guessed. The Editors and Auto Pilot features
are behind the paid plan, so only their pitch page was visible.

Nothing was copied: no source, assets, private APIs or branding. This is a workflow reference.

## Why their workflow feels strong

1. **One box on Home.** "What will you create today?" — paste a URL or upload a video, press one
   button, and clips come back. No project to name, no steps to learn.
2. **Everything is a status.** Clips move New → Draft → Exported → Scheduled (or Hidden), and the
   same six tabs appear on every list. You always know what is waiting for you.
3. **Posting is a queue, not a form.** "Review clip 1 of 12": preview, channels and caption, a
   filmstrip of the rest, then *Skip* or *Approve*, with "Now" or a time next to the button.
4. **The calendar has empty slots.** You choose how often you post (a slider, "21× a week"); the
   week fills with dashed slots, and approving a clip drops it into the next one.

## Comparison

| Area | StreamLadder | PeakSift now | Gap | What we should build |
| --- | --- | --- | --- | --- |
| Home | One input (URL or upload), tool tiles, recent streams, new clips, scheduled posts | Continue cards, recent Shorts, getting-started list; starting needs `/projects/new` | Starting takes five manual steps: name → open → upload → transcribe → find moments | **Quick start on Home:** drop a video, PeakSift names the project and runs transcription and moments by itself |
| New project / import | Paste a Twitch, YouTube or Kick URL; upload; browse your channel's VODs | Name-and-market form, then file upload on the next page | No one-step start; no URL import; no channel browsing | Quick start first. URL import later, and only for the creator's own channel (see "not copy") |
| AI clip discovery | ClipGPT runs automatically after import; clips listed per stream with a score, on a stream timeline bar | Transcript-wide detection with reasons, saved/dismissed decisions; started by hand with a provider picker | Not automatic; the picker is a hurdle for a first run | Auto-run with the default provider after upload; keep the picker under "Advanced" |
| Natural-language Find Clips | Not present in the app that was seen ("Find clips" means ClipGPT). "Clip This" catches the phrase "clip that" said on stream | Semantic search exists for images and B-roll only | No way to ask for a moment in words | **Find Clips:** "the part where I explain pricing" → transcript-grounded moments with timestamps → one click to a clip. A place to be ahead |
| Editor | *Not seen.* Split into "Clip Editor" (portrait) and "Video Editor" (landscape) | One Short editor with preview, panels, versions, Auto Edit | Unknown | Nothing from this benchmark |
| Timeline | *Not seen* | Visual timeline with tracks | Unknown | Nothing from this benchmark |
| Captions | *Not seen* | Dynamic captions, Arabic and Darija aware | Unknown | Nothing from this benchmark |
| Layouts | *Not seen.* "Vertical clips" selector on the review page | Smart Reframe | Unknown | Nothing from this benchmark |
| Visuals | *Not seen* | B-roll and visual intelligence, semantic asset search | Likely ahead | Keep |
| Audio | *Not seen* | Audio and SFX mixing with ducking and loudness | Likely ahead | Keep |
| Templates | *Not seen* | Brand Studio, reusable templates, Morocco formats | Likely ahead | Keep |
| Shorts / content library | One Clips list, six status tabs, list/grid, sort, source filter; each card has Post · Save · Hide · More | Shorts Library with statuses and a Short detail page | No "Scheduled" state; no review queue | Add Scheduled to the library with the scheduling work |
| Publishing | Review-and-approve queue across all connected channels | Publishing Center, YouTube, one Short at a time | No batch review; one platform | **Review queue** for ready Shorts; platform-neutral publish targets underneath |
| Scheduling | Week/month calendar, posting-time slots from a frequency slider, slightly randomised minutes | None: publishing is immediate only | The whole feature | **Schedule & Post:** `scheduled_at` on publish jobs, a worker that releases due jobs, a calendar, then posting slots |
| Analytics | None seen in the app | Per-video analytics, creator learning, grounded recommendations | Ahead | Keep; feed "best time to post" into scheduling |
| Collaboration / workspaces | Workspace id in every URL; invite editors by link with scoped access (paid); "Auto Pilot" announced | Single creator; nothing shared | The whole feature | Later: an editor role limited to edit and schedule. Needs a product decision first |
| Mobile | Same layout stacks cleanly; hamburger menu; pushes a native app | Responsive, audited at seven widths | Roughly level on the web | Keep |

Also on their Home but outside PeakSift's direction: Montage Maker (stitch exported clips into one
landscape video), stream Schedule Maker, Clip Downloader, Emote Maker.

## Things StreamLadder does better

- Time to first clip: one input, one button.
- A single status vocabulary across the product.
- Posting as a review queue with approve / skip.
- A calendar that shows the empty slots you still have to fill.
- Their empty states always carry the next action ("Go to streams", "Schedule a post").

## Things PeakSift already does better

- Explains *why* a moment was chosen; lets the creator save or dismiss and learns from it.
- Creator Copilot (Ask PeakSift) with grounded answers.
- Semantic asset intelligence and B-roll matching.
- Auto Edit, Smart Reframe, dynamic captions and audio as one pipeline.
- Brand Studio and reusable templates.
- Analytics with creator learning. StreamLadder shows none in the app.
- Morocco Mode: market, Darija-aware language handling, local formats.
- Works on any long video, not only game streams.

## Things we should NOT copy

- **Importing anyone's stream by URL.** Their demo account is full of another creator's VODs.
  PeakSift should only import a channel the creator has connected and owns.
- **A single "virality score" badge** (🔥 98). PeakSift's rule is no virality predictions; keep
  ranked moments with reasons.
- **Clips that expire** on the free plan ("7 expired"). It reads as punishment.
- **A tool grid** (emote maker, downloader, schedule maker). One workflow beats eight tools.
- **Hiding the posting pattern** ("so your schedule never looks automated"). Show the creator the
  exact times instead.
- **Upsell and contest banners over the workspace**, and a native-app banner on every mobile page.
- Their look: purple gradient, mascot, type. PeakSift keeps its own design system.

## Build order

1. **Quick start on Home** — one drop, automatic transcription and moments. Smallest change,
   seen by every creator in the first minute.
2. **Find Clips in plain language** — ahead of StreamLadder, uses what PeakSift already knows.
3. **Schedule & Post** — scheduled publish jobs, calendar, then posting slots and the review queue.
4. **Platform-neutral publishing** — lift the YouTube-only constraint in the data model so TikTok
   and Instagram can be added when credentials exist.
5. Montage and editor workspaces — after the above, each needs its own product decision.
