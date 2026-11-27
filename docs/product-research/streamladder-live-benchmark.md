# StreamLadder live benchmark

Inspected 26 November 2026 in the live StreamLadder web app (free plan, signed in), desktop and a
375 px viewport. Screens walked: Home, Streams, a stream's clip review page, the clip library
(New / Draft / Exported / Scheduled / Hidden), the review-and-post dialog, the Content Publisher
calendar, posting-time slots, Social connections and Editors.

The clip editor was inspected the next day; see **The clip editor** below (the comparison
table's *not seen* rows are answered there). The Editors and Auto Pilot features are behind the
paid plan, so only their pitch page was visible.

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

## The clip editor (inspected 27 November 2026)

Opened by uploading a 5½-minute synthetic test video (a test pattern and a computer voice, nothing
personal) to the creator's private workspace; uploads under 5 minutes are refused everywhere, and
every older clip in the account had expired. ClipGPT found 11 clips in about two minutes; the top
one was opened in the vertical editor. Nothing was exported, posted or saved beyond that draft.

**Setup before ClipGPT** (one page, three steps): streamer name, language, "about you", a
writing-style box for titles with quick starts (Hype gamer · Chill & clean · Funny / meme ·
Professional), the part of the video to search; then a caption style; then an intro title style.

**Editor shell.** A left rail of steps — Layouts → Elements → Effects → Audio → Captions → Export —
each with a "next" button; a 9:16 preview inside a phone frame with the **platform's own UI drawn
over it** (YouTube / TikTok preview, so you see what the buttons cover); Undo / Redo; zoom to fit.

**Timeline.** Ruler, a caption track with **one chip per word**, the video track, and a track per
effect (a zoom is a pink bar with drag handles). Toolbar: split at the playhead, trim start / end
to the playhead, delete, add, colour. Clicking a word seeks there.

**Layouts.** Small facecam, Circle facecam, Game UI, Split, Blurred, Fullscreen, Basecam, Mosaic,
Dual facecam, Duo split, Half — each a set of crop boxes drawn on the source with snapping, per
shot ("Shot #1"). "AI Magic Cut" splits by scene and picks a layout per scene.

**Captions.** Every caption editable as text; speakers. *Presets*: ~40 animated styles (globe badge
= works in other scripts). *Effects* toggles: caption size, **AI Shake** (loud words shake), **AI
Supersize** (key words big and bold), multiple speakers, emojis, speaker avatars, hide punctuation,
random rotation. *Style designer*: font, weight, italic, spacing; fill, stroke, extra stroke,
shadow, glow, background. *Effect*: no animation, one word at a time, accessible short captions,
karaoke bounce, marker reveal, scale to fit, underline, highlight, typewriter, random bounce,
cascade slide, morph bloom. *Configure*: show as word / sentence, break lines, caption length
short / medium / long; **highlight the spoken word**: colour, underline or pill; word animations
(reveal, slow zoom, fade, slide, shrink, bounce, opacity, slide in, bounce in, snap in, blast in,
diagonal, glow reveal) and sentence animations; visual effects that play throughout (glitter,
holographic, neon pulse, wave, snap wave, floating words, shake blur, rainbow, RGB shift) with
intensity and speed.

**Elements.** Upload your own PNG / JPEG / GIF (≤ 10 MB). *Social stickers*: generated name tags —
the creator's handle on a platform badge, animated or static.

**Effects.** Zoom (drag a box, animation style, level, saved zooms), speed control, word censoring
(bleep), text to speech, **AI – Remove silences**, AI hook intro title, add a hook clip (a moment
plays first). *Special effects*: zoom blur, shake, slide shake, morph, slide, screen shake, glitch,
pixelate, film-grain shake; *intros*: cloud, fire, flash, lightning, smoke, speed lines;
*overlays*: error, eyes, flowers, confetti, skull and similar reactions.

**Remove silences — what "tightening" means there.** "N silences longer than X s found", a
sensitivity slider (default 0.5 s), one **Remove N silences** button, **Reset effect**. On the test
clip at 0.2 s: 10 silences, 24.0 s → 22.3 s, and the video track became 11 segments on the
timeline, each still adjustable. Built on the caption word timings.

**Audio.** Sound effects: search, All · Uploaded · Favorites · categories (Alerts & Notifications …),
upload ≤ 5 MB. Music: search, uploads, full songs. The library includes recognisable brand and
meme sounds (a fast-food chime, a console click) — exactly what PeakSift must not ship.

**Export.** One "Export clip" button; the free plan watermarks.

### Editor gaps, and what PeakSift should build

| StreamLadder | PeakSift now | Build |
| --- | --- | --- |
| Remove silences with a threshold, segments on the timeline | Nothing; a Short is one continuous span | **Tighten**: cut pauses longer than a threshold from the persisted word timings; the cuts are part of the edit, shown as segments; captions, sound and visuals follow the new time |
| Split / trim / delete on the video track | Timeline is "not an NLE" | Split at the playhead and delete a segment, in the same cut list as Tighten |
| ~40 caption styles + designer | 4 dynamic presets | More presets in libass: one word at a time, highlight colour / pill / underline, pop and bounce entrances, typewriter, glow; key-word supersize; hide punctuation; open-licence fonts (Latin and Arabic) |
| SFX and music libraries | The creator's own audio only | A **built-in starter library** of openly licensed sounds and loops (below), beside the creator's own |
| Stickers, intro and reaction overlays | The creator's own images and B-roll | Built-in stickers (open-licence emoji) and overlays made by PeakSift with alpha (confetti, flash, speed lines …); social handle tags generated from the creator's handle |
| Zoom bars, shake, flash | No zoom | Punch-in zoom items on the timeline; flash and shake as short effects |
| Word censoring | — | Bleep and mask a chosen word |
| Platform UI over the preview | Safe area only | TikTok / Shorts / Reels overlay toggle |
| Facecam layouts | Smart Reframe, centre, blur, fit | Later: two-crop layouts (facecam + gameplay) |

### Where a built-in library can come from

Researched 27 November 2026 (pages read, nothing downloaded). The rule: every file must be
redistributable inside PeakSift **and** usable in creators' commercial videos without a credit
they must add. That means CC0, MIT, Apache 2.0 or OFL, mirrored by PeakSift with a pinned manifest
(source page, licence, sha256) — never fetched from the source at runtime.

| Kind | Use | Licence |
| --- | --- | --- |
| Sound effects | Kenney audio packs (Interface Sounds, Impact, UI, Digital); hand-picked Freesound and OpenGameArt items marked CC0 | CC0 |
| Music | OpenGameArt CC0 loops; Kenney Music Jingles. Thin: expect < 50 good loops | CC0 |
| Stickers | Microsoft Fluent Emoji; Google Noto Emoji images; Kenney Emotes | MIT; Apache 2.0; CC0 |
| Overlays | Made by PeakSift as alpha video from CC0 particles (Kenney Particle Pack) and the emoji above. No verified CC0 green-screen meme library exists | CC0 / own |
| Caption fonts | Montserrat, Bangers, Anton, Bebas Neue, Fredoka, Titan One; Luckiest Guy; Arabic: Lalezar, Cairo, Baloo Bhaijaan 2 | OFL; Apache 2.0 |

**Rejected:** YouTube Audio Library (not redistributable); Pixabay, Mixkit, Pexels, ZapSplat,
Sonniss (their terms bar redistributing the files in an app or library); BBC Sound Effects
(non-commercial); Freesound CC-BY-NC and its API (non-commercial without a licence); Kevin MacLeod
/ Incompetech (CC-BY, a credit in every video, and a history of false Content ID claims); Twemoji
(CC-BY) and OpenMoji (CC BY-SA, share-alike); Komika (freeware, unclear for apps); meme sounds such
as the "Vine boom" and "bruh" (owned by others, no licence); anything ripped from YouTube, Tenor or
Giphy. Creators can still upload sounds they have the rights to. Platform logos are trademarks —
handle tags use neutral icons.

**Still to check by hand before mirroring:** FreePD's licence text, the contents of the Kenney
Particle Pack, Fluent Emoji's formats.

## Build order

1. **Quick start on Home** — one drop, automatic transcription and moments. Smallest change,
   seen by every creator in the first minute.
2. **Find Clips in plain language** — ahead of StreamLadder, uses what PeakSift already knows.
3. **Schedule & Post** — scheduled publish jobs, calendar, then posting slots and the review queue
   (built: `/shorts/review`, see [shorts-library.md](../shorts-library.md)).
4. **Platform-neutral publishing** — lift the YouTube-only constraint in the data model so TikTok
   and Instagram can be added when credentials exist.
5. Montage and editor workspaces — after the above, each needs its own product decision.
6. **Editor, from the clip-editor study:** Tighten (remove pauses) with split / delete on the
   timeline → more caption styles and open-licence fonts → the built-in starter library (sounds,
   loops, stickers, overlays) → zoom, flash and shake → word censoring and the platform preview.
