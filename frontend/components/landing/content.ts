// The website's pages as data: every tool, every audience and every guide. Everything here
// describes what PeakSift does today (see docs/*.md); nothing is promised that is not built, and
// there are no usage figures, testimonials or predictions.

import type { VisualName } from "@/components/landing/visuals";

export type Faq = { q: string; a: string };

export type Tool = {
  slug: string;
  name: string;
  /** One line for menus and cards. */
  summary: string;
  title: string;
  lead: string;
  visual: VisualName;
  features: { title: string; text: string }[];
  steps: { title: string; text: string }[];
  explainer: string[];
  faq: Faq[];
  related: string[];
};

export const TOOLS: Tool[] = [
  {
    slug: "ai-moments",
    name: "AI moments",
    summary: "The strongest moments of a long video, ranked, with the reason for each.",
    title: "AI moments: the best parts of your long video, found for you",
    lead: "Upload a stream, podcast or interview. PeakSift transcribes it, reads what was said and ranks the moments worth clipping — each one with the reason it made the list.",
    visual: "moments",
    features: [
      { title: "Runs by itself", text: "Drop a video on Home and PeakSift names the project, transcribes it and finds moments without another click." },
      { title: "A reason for every pick", text: "Each moment says why it was chosen — the line it opens on, the turn in the story — so you decide, not a score." },
      { title: "Real transcript lines", text: "Moments start and end on lines that were actually said. Nothing is paraphrased or invented." },
      { title: "Ranked best first", text: "The strongest moments come first, with a top pick, on an editorial 0–100 scale that is never a prediction of views." },
      { title: "Save or dismiss", text: "Keep the moments you like and dismiss the rest; your saved moments are where Shorts start." },
      { title: "Your choice of model", text: "Use a local model on your own server or a hosted one — the server decides which are allowed." },
    ],
    steps: [
      { title: "Upload your video", text: "MP4, MOV or WebM. PeakSift checks it and shows a preview." },
      { title: "PeakSift reads it", text: "It transcribes the speech with timestamps and looks for the moments worth a Short." },
      { title: "Pick your moments", text: "Review them best first, preview each one, save the ones you want." },
    ],
    explainer: [
      "Long recordings hide their best moments. Scrubbing through an hour of footage to find the forty seconds that work is the slowest part of making Shorts — so PeakSift does that part. It transcribes your video, splits it into overlapping windows and asks a language model which stretches stand on their own: a clear question, a story with a turn, a tip someone would save.",
      "Everything the model returns is checked before you see it. Start and end times are snapped to real transcript lines, moments that do not fit are dropped rather than repaired, and every moment keeps the exact words that were said. What you get is a ranked list you can trust — and a reason for each pick, so you can disagree with it.",
    ],
    faq: [
      { q: "Does PeakSift predict how many views a moment will get?", a: "No. Moments are ranked on an editorial scale from 0 to 100 that says how well a moment stands on its own. It is never presented as a prediction of views or virality." },
      { q: "Which videos work best?", a: "Anything with speech: podcasts, streams, interviews, talks, lessons. PeakSift reads what was said, so the clearer the audio, the better the moments." },
      { q: "Can I look for a specific moment?", a: "Yes — use Find Clips and describe it in your own words. Anything you keep becomes a saved moment like the others." },
      { q: "How long does it take?", a: "Transcription and moment finding run in the background while you do other things; the project page updates by itself when they are done." },
    ],
    related: ["find-clips", "auto-edit", "smart-reframe", "captions"],
  },
  {
    slug: "find-clips",
    name: "Find Clips",
    summary: "Describe a moment in your own words and jump to where it was said.",
    title: "Find Clips: search your video the way you remember it",
    lead: "Type “the part where I explain pricing” and PeakSift shows you where you said it — real lines from your transcript, with timestamps. Keep the one you want and it becomes a moment.",
    visual: "find",
    features: [
      { title: "Plain-language search", text: "Describe the moment the way you remember it; no exact words needed." },
      { title: "Real lines, real times", text: "Every result is a stretch of your transcript with its start and end time." },
      { title: "Related words", text: "PeakSift also looks for closely related words, and tells you which ones it tried." },
      { title: "Preview in place", text: "Play just that stretch of your source video right in the results." },
      { title: "Keep a result", text: "One click turns a result into a saved moment, ready for a Short." },
      { title: "Any language you speak", text: "Search works on your transcript, including right-to-left text." },
    ],
    steps: [
      { title: "Open your project's moments", text: "Find Clips sits above the moments PeakSift found." },
      { title: "Describe the moment", text: "Or tap one of the examples to see how it works." },
      { title: "Keep what you want", text: "Preview a result, then keep it — it lands under Saved." },
    ],
    explainer: [
      "AI picks are a great start, but you were there — you remember the moment you want. Find Clips searches your own transcript for it, ranks the places where you said it, and shows the exact lines so you can check before keeping anything.",
      "Results are never guessed: if nothing in the transcript matches, PeakSift says so and suggests trying other words, instead of showing something close but wrong.",
    ],
    faq: [
      { q: "Is Find Clips the same as AI moments?", a: "No. AI moments are PeakSift's own picks; Find Clips finds the moment you ask for. Both end up as moments you can turn into Shorts." },
      { q: "What if I search for something I never said?", a: "PeakSift tells you nothing matched and lists the words it looked for — it never shows a made-up result." },
      { q: "Does it need an internet AI service?", a: "Search runs on your transcript; related words can come from a local model on your server." },
    ],
    related: ["ai-moments", "auto-edit", "captions", "smart-reframe"],
  },
  {
    slug: "auto-edit",
    name: "Auto Edit",
    summary: "A first cut made for you: framing, captions, hook and visuals.",
    title: "Auto Edit: a first cut of your Short, made for you",
    lead: "Pick a moment and let PeakSift plan the edit — framing, captions, an opening hook from your own words and visuals from your library. Review it, then apply it in one click.",
    visual: "auto-edit",
    features: [
      { title: "A plan you can read", text: "See every choice before it is applied, each explained in plain words." },
      { title: "Hooks from your words", text: "Opening hooks use what was said in the clip — no new names or numbers." },
      { title: "Your templates first", text: "Auto Edit follows your brand and template, then fills the rest." },
      { title: "Your visuals, matched", text: "Only strong matches from your own visual library are placed automatically." },
      { title: "Never picks your music", text: "Music is always your choice; Auto Edit never adds it on its own." },
      { title: "Everything stays editable", text: "An applied plan is just a starting point in the editor." },
    ],
    steps: [
      { title: "Choose a moment", text: "Any saved moment, from AI moments or Find Clips." },
      { title: "Review the plan", text: "Framing, captions, hook and visuals, each with its reason." },
      { title: "Apply and fine-tune", text: "Open it in the editor, change anything, render." },
    ],
    explainer: [
      "Most Shorts need the same first steps: frame the speaker, add captions, write an opening line, place a visual or two. Auto Edit does those steps for you, using what PeakSift already knows about the clip — the faces in it, the words with their timing, the visuals in your library.",
      "The model only proposes; PeakSift checks every choice against what exists and against your template before you see it. If something cannot be done, the plan tells you why instead of guessing.",
    ],
    faq: [
      { q: "Will Auto Edit change a Short I already made?", a: "No. A plan only ever creates a new version; existing Shorts and applied plans never change." },
      { q: "Does it add music?", a: "Never on its own. Music is always the creator's explicit choice." },
      { q: "Can I use my brand?", a: "Yes. Auto Edit follows your Brand Studio template and brand, and records which ones it used." },
    ],
    related: ["captions", "smart-reframe", "visuals", "brand-studio"],
  },
  {
    slug: "smart-reframe",
    name: "Smart reframe",
    summary: "Follows faces to turn widescreen footage into clean 9:16.",
    title: "Smart reframe: widescreen to vertical, with the face in frame",
    lead: "PeakSift finds the faces in your clip and moves a smooth 9:16 crop to keep them in view — no black bars, no awkward cropping. Prefer something simpler? Centre crop, blur background and fit are one click away.",
    visual: "reframe",
    features: [
      { title: "Face-aware crop", text: "Faces are found on sampled frames and followed with a smooth crop path." },
      { title: "Four layouts", text: "Smart reframe, centre crop, blur background or fit — pick per Short." },
      { title: "Manual focus point", text: "Set the focal point yourself when you want a fixed frame." },
      { title: "Runs on your server", text: "Face detection is a local model; your video never leaves the server." },
      { title: "Honest fallbacks", text: "No face found? PeakSift says so and uses the centre, never a guess." },
      { title: "Full-HD vertical", text: "Every Short renders at 1080×1920, ready for every platform." },
    ],
    steps: [
      { title: "Open a Short in the editor", text: "The Style tool holds the layouts." },
      { title: "Choose Smart reframe", text: "PeakSift analyses the clip and plans the crop." },
      { title: "Render", text: "Preview the frame, then render your vertical Short." },
    ],
    explainer: [
      "A centred crop cuts off whoever is not in the middle, and letterboxing looks unfinished. Smart reframe samples frames from your clip, finds the faces, tracks them, and turns that into a smooth crop path that FFmpeg follows when it renders.",
      "It is face framing, not speaker detection: it keeps faces in view, and when there are none it tells you and falls back to the centre or your own focal point.",
    ],
    faq: [
      { q: "Does it know who is speaking?", a: "No — it frames faces. It is not speaker detection, and PeakSift never describes it as such." },
      { q: "What if there is no face?", a: "PeakSift tells you and uses the centre, or the focal point you set." },
      { q: "Can I still use letterbox or blur?", a: "Yes. Fit and blur background are layouts in the same Style tool." },
    ],
    related: ["captions", "auto-edit", "visuals", "ai-moments"],
  },
  {
    slug: "captions",
    name: "Dynamic captions",
    summary: "Word-by-word captions with the spoken word highlighted.",
    title: "Dynamic captions that follow every word",
    lead: "Captions timed to each word you say, with the spoken word emphasised — in four styles, kept inside the safe area of every platform, with an opening hook on top.",
    visual: "captions",
    features: [
      { title: "Word-by-word timing", text: "Each word is timed from the audio itself, then checked before it is used." },
      { title: "Four styles", text: "Focus, Punch, Minimal and Boxed — each emphasises the spoken word its own way." },
      { title: "Platform safe area", text: "Captions stay clear of the buttons and text each app puts on top." },
      { title: "Opening hook", text: "A line at the start that says why to keep watching — from your own words." },
      { title: "Arabic and more", text: "Captions render in many languages, including Arabic, right to left." },
      { title: "Live preview", text: "See the captions move in the editor before you render." },
    ],
    steps: [
      { title: "Open the Captions tool", text: "In the editor, next to Style." },
      { title: "Pick a style", text: "Focus, Punch, Minimal or Boxed, with a position." },
      { title: "Add an opening", text: "Choose a hook idea from your clip, then render." },
    ],
    explainer: [
      "Most viewers watch with the sound off, so captions carry the Short. PeakSift times every word from the audio of the clip, checks the timing, and renders captions that light up the word being spoken.",
      "Captions are your exact words — never paraphrased — and phrase-timed captions are never called word-synced. What you see in the preview is what the render uses.",
    ],
    faq: [
      { q: "Can I edit the caption text?", a: "Captions follow the transcript exactly; PeakSift does not rewrite what you said." },
      { q: "Which languages work?", a: "Any language the transcription supports, including Arabic with right-to-left text." },
      { q: "Can I use my brand colours?", a: "Yes — Brand Studio sets caption emphasis and hook accent colours, contrast-checked." },
    ],
    related: ["smart-reframe", "brand-studio", "auto-edit", "music"],
  },
  {
    slug: "visuals",
    name: "B-roll & visuals",
    summary: "Your own images and clips, matched to what is being said.",
    title: "B-roll from your own library, matched to your words",
    lead: "Upload your images and clips once. PeakSift suggests where they fit in a Short, finds them when you search in plain words, and places them as cutaways, picture-in-picture or overlays.",
    visual: "edit",
    features: [
      { title: "Your visual library", text: "Images and B-roll clips per project, checked, with thumbnails and tags." },
      { title: "Search your visuals", text: "Describe what you need; PeakSift finds it by what is in the picture." },
      { title: "Suggestions from the clip", text: "PeakSift suggests B-roll where your words call for it, grounded in the transcript." },
      { title: "Three placements", text: "Cutaway, picture-in-picture or overlay, with fades." },
      { title: "Captions stay on top", text: "Visuals sit under captions and the hook; B-roll is always muted." },
      { title: "Never stock media", text: "Only your own visuals — PeakSift never fetches images from the internet." },
    ],
    steps: [
      { title: "Upload your visuals", text: "Images and short clips into the project's Assets." },
      { title: "Open the Visuals tool", text: "See suggestions, or search your library." },
      { title: "Place and render", text: "Pick the placement and timing, then render." },
    ],
    explainer: [
      "B-roll makes a talking-head Short feel produced, but finding the right picture at the right second is slow. PeakSift indexes your own images and clips, understands what is in them, and suggests them where your words call for them.",
      "Matches are offered, never forced: only strong matches are placed automatically by Auto Edit, and everything stays your choice in the editor.",
    ],
    faq: [
      { q: "Does PeakSift add stock footage?", a: "No. It only uses visuals you uploaded; it never searches or downloads media." },
      { q: "Can I delete a visual a Short uses?", a: "Not while a Short uses it — PeakSift keeps your renders intact." },
      { q: "Do my files leave the server?", a: "No. Visual search runs on your server." },
    ],
    related: ["auto-edit", "captions", "brand-studio", "music"],
  },
  {
    slug: "music",
    name: "Music & sound",
    summary: "Your music under the voice, ducking, effects and loudness.",
    title: "Music and sound that sit right under your voice",
    lead: "Add your own music and sound effects, let the music dip whenever you speak, and get a Short mixed to a consistent loudness — all in the editor's Sound tool.",
    visual: "audio",
    features: [
      { title: "Your own audio", text: "Upload music and effects to the project; PeakSift checks each file." },
      { title: "Ducking", text: "Music dips under your voice with a choice of presets." },
      { title: "Levels and fades", text: "Set voice and music levels, start, loop and fades." },
      { title: "Timed effects", text: "Drop sound effects at exact moments of the clip." },
      { title: "Consistent loudness", text: "Every mix is limited and normalised to −14 LUFS." },
      { title: "Never generated", text: "PeakSift uses only audio you upload — no libraries, no generated music." },
    ],
    steps: [
      { title: "Upload your audio", text: "Music and effects into the project's Assets." },
      { title: "Open the Sound tool", text: "Pick music, set levels and ducking." },
      { title: "Preview and render", text: "Hear it in the editor, then render the final mix." },
    ],
    explainer: [
      "A Short with music that drowns the voice gets skipped. PeakSift mixes your voice, music and effects with ducking that lowers the music while you speak, then limits and normalises the result so every Short plays at the same loudness.",
      "The browser preview is a guide; the render is the final mix.",
    ],
    faq: [
      { q: "Does PeakSift have a music library?", a: "No. You bring your own music and effects; PeakSift never fetches or generates audio." },
      { q: "Is the loudness a platform requirement?", a: "No — −14 LUFS is PeakSift's target for a consistent level, not a platform rule." },
    ],
    related: ["captions", "visuals", "auto-edit", "brand-studio"],
  },
  {
    slug: "brand-studio",
    name: "Brand Studio",
    summary: "Your colours, logo and templates on every Short.",
    title: "Brand Studio: your look on every Short",
    lead: "Set your colours, logo and end card once, save the edits you like as templates, and start every new Short from them.",
    visual: "brand",
    features: [
      { title: "Colours, checked", text: "Brand colours are contrast-checked; an unreadable colour is dropped, never altered." },
      { title: "Your logo", text: "Placed where it never covers captions or faces." },
      { title: "End card", text: "A closing line in your words at the end of each Short." },
      { title: "Templates", text: "Save framing, captions, hook, visuals and sound settings as a template." },
      { title: "Versioned", text: "Changing a template never changes Shorts you already made." },
      { title: "Explicit only", text: "Saving or updating a template is always your click." },
    ],
    steps: [
      { title: "Create your brand", text: "Colours, logo and end card in Brand Studio." },
      { title: "Save a template", text: "From the editor: Save as template." },
      { title: "Start from it", text: "Every new Short and Auto Edit plan can use it." },
    ],
    explainer: [
      "Consistency is what makes a channel recognisable. Brand Studio keeps your colours, logo and favourite settings in one place, and every Short — made by you or by Auto Edit — can start from them.",
      "Each Short records the template and brand it was made with, so you always know where a look came from.",
    ],
    faq: [
      { q: "Can I use custom fonts?", a: "Not yet — PeakSift uses its own caption fonts so text renders the same everywhere." },
      { q: "Will changing my brand change old Shorts?", a: "No. Brands and templates are versioned; existing Shorts keep what they were made with." },
    ],
    related: ["auto-edit", "captions", "publish", "visuals"],
  },
  {
    slug: "publish",
    name: "Schedule & publish",
    summary: "YouTube Shorts, TikTok and Instagram Reels, now or later.",
    title: "Post to YouTube, TikTok and Instagram — now or on schedule",
    lead: "Connect your accounts, publish a Short or schedule it, and set your weekly posting times once so the next free slot is always one click away.",
    visual: "publish",
    features: [
      { title: "Three platforms", text: "YouTube Shorts, TikTok and Instagram Reels from one place." },
      { title: "Schedule ahead", text: "Pick a time; nothing is uploaded before it." },
      { title: "Posting times", text: "Set weekly slots once, then take the next free one." },
      { title: "A real calendar", text: "See the week: what is planned, what is out, what is free." },
      { title: "Move or cancel", text: "Change the time, publish now or cancel until it goes out." },
      { title: "Never posts on its own", text: "Nothing is published without your click, and YouTube uploads are private by default." },
    ],
    steps: [
      { title: "Connect your accounts", text: "In Settings, one connection per platform." },
      { title: "Publish or schedule", text: "From a finished Short, pick the platform and the time." },
      { title: "Watch it go out", text: "The calendar and the Short show real stages, never a guess." },
    ],
    explainer: [
      "Uploading the same Short to three apps is busywork. PeakSift keeps one connection per platform and one calendar for all of them, with posting slots you choose and a worker that releases each post at its time.",
      "PeakSift only says “Published” when the platform confirms it, uploads resume safely if interrupted, and a Short is never uploaded twice.",
    ],
    faq: [
      { q: "Which permissions does PeakSift ask for?", a: "Only what posting needs — for YouTube, upload access. Reading analytics is a separate permission you grant yourself." },
      { q: "Can I post at the best time automatically?", a: "You choose your posting times; PeakSift fills the next free one. It does not guess times for you." },
      { q: "Is publishing switched on everywhere?", a: "Each platform is switched on by its server's settings; Settings shows what is available to you." },
    ],
    related: ["analytics", "brand-studio", "auto-edit", "ai-moments"],
  },
  {
    slug: "analytics",
    name: "Analytics",
    summary: "How every published Short is doing, compared with your own uploads.",
    title: "Analytics: how your Shorts are doing, in plain words",
    lead: "See views and watch time for every Short you published with PeakSift, compared with your own recent uploads — and the patterns that have tended to work for you.",
    visual: "learn",
    features: [
      { title: "Every published Short", text: "Performance linked to the Short and version it came from." },
      { title: "Your own baseline", text: "Compared with the median of your recent uploads, never other creators." },
      { title: "Early windows", text: "How a Short did in its first days, once the data is complete." },
      { title: "Observed patterns", text: "What has tended to work for you, only when the evidence is strong enough." },
      { title: "Only what is reported", text: "Missing figures stay missing — never estimated, never zero." },
      { title: "Yours to delete", text: "Remove collected metrics whenever you want." },
    ],
    steps: [
      { title: "Grant read access", text: "A separate, read-only permission you start yourself." },
      { title: "Publish with PeakSift", text: "Shorts you publish are linked automatically." },
      { title: "Read the results", text: "In Analytics and on each Short's page." },
    ],
    explainer: [
      "Analytics only matter if they tell you what to make next. PeakSift compares each Short with your own recent uploads, waits for complete data before comparing, and only shows a pattern when it passes a statistical test — in careful words like “has tended to”.",
      "There are no predictions and no virality scores: PeakSift reports what happened, not what will.",
    ],
    faq: [
      { q: "Which platforms are covered?", a: "YouTube, for Shorts published with PeakSift." },
      { q: "Does PeakSift compare me with other creators?", a: "No. Only with your own uploads." },
    ],
    related: ["publish", "ask", "ai-moments", "auto-edit"],
  },
  {
    slug: "ask",
    name: "Ask PeakSift",
    summary: "An assistant that answers from your projects, not from guesswork.",
    title: "Ask PeakSift: an assistant that knows your projects",
    lead: "Ask what to post next, which moment to use or how a Short is doing. Ask PeakSift answers from your own projects, and takes you straight to the right place.",
    visual: "ask",
    features: [
      { title: "Grounded answers", text: "Answers come from your projects, moments and Shorts." },
      { title: "Exact where it matters", text: "Next steps, top picks and results are answered by PeakSift itself, not a guess." },
      { title: "Short ideas", text: "Idea cards built from your real moments." },
      { title: "One click to act", text: "Buttons open the right page or start a Short — re-checked when clicked." },
      { title: "Never acts alone", text: "It never publishes, deletes or changes anything." },
      { title: "Per project", text: "One conversation per project, clearable any time." },
    ],
    steps: [
      { title: "Open Ask PeakSift", text: "From the sidebar, or with ⌘K." },
      { title: "Ask in your words", text: "Or start from a suggested question." },
      { title: "Follow the answer", text: "Open the page it points to, or create the Short." },
    ],
    explainer: [
      "An assistant is only useful if it is right about your work. Ask PeakSift sees a careful summary of your project — never other creators' data — and anything it knows exactly is answered by PeakSift, not the model.",
      "It suggests; you decide. It never claims to have done something it did not, and it never posts or changes anything for you.",
    ],
    faq: [
      { q: "Can Ask PeakSift publish for me?", a: "No. It can only point you to pages or start creating a Short; publishing is always your click." },
      { q: "Does it use my transcript?", a: "Only within the project you ask about, treated as data, never as instructions." },
    ],
    related: ["analytics", "ai-moments", "auto-edit", "publish"],
  },
  {
    slug: "morocco-mode",
    name: "Morocco Mode",
    summary: "Darija-aware hooks and Moroccan formats, on top of everything else.",
    title: "Morocco Mode: everything in PeakSift, plus Moroccan context",
    lead: "Switch a project to Morocco Mode and keep every Global tool — plus hook ideas from your own Darija, curated Moroccan formats and your local visuals first.",
    visual: "morocco",
    features: [
      { title: "Global, plus", text: "Morocco Mode extends PeakSift; it never hides a Global tool." },
      { title: "Darija from your words", text: "Hooks use what you said — verbatim, or across scripts with “check the spelling”." },
      { title: "Language detection", text: "PeakSift notices Darija, Arabic, French and English, and says when it is unsure." },
      { title: "Curated formats", text: "Moroccan formats built on existing settings — never called trending." },
      { title: "Your local assets", text: "Label your visuals and sounds by origin, category and place; local ones come first." },
      { title: "Per project", text: "Market and language are separate choices, set per project." },
    ],
    steps: [
      { title: "Choose Morocco Mode", text: "On Home or when you create a project." },
      { title: "Work as usual", text: "Moments, editing and publishing are the same." },
      { title: "Use the extras", text: "Hook ideas, Moroccan formats and local assets appear where they fit." },
    ],
    explainer: [
      "Moroccan creators switch between Darija, Arabic, French and English — often in one sentence. Morocco Mode keeps that in mind: it detects the languages carefully, offers hooks only from your own words, and puts your local visuals and sounds first.",
      "PeakSift never writes Darija for you, never invents trends or places, and never speaks for an audience.",
    ],
    faq: [
      { q: "Do I lose anything from Global?", a: "No. Morocco Mode only adds; every Global tool, template and asset stays." },
      { q: "Will PeakSift write Darija captions?", a: "No. Darija only ever comes from your own words." },
    ],
    related: ["captions", "brand-studio", "ai-moments", "visuals"],
  },
];

export type Audience = {
  slug: string;
  name: string;
  summary: string;
  title: string;
  lead: string;
  visual: VisualName;
  reasons: { title: string; text: string }[];
  steps: { title: string; text: string }[];
  tools: string[];
  faq: Faq[];
};

export const AUDIENCES: Audience[] = [
  {
    slug: "podcasters",
    name: "Podcasters",
    summary: "Turn every episode into a week of Shorts.",
    title: "Turn every podcast episode into a week of Shorts",
    lead: "Your episode is full of quotable moments. PeakSift finds them, frames both speakers, captions every word and schedules them across the week.",
    visual: "moments",
    reasons: [
      { title: "Made for conversation", text: "Moments are found from what was said, so a one-hour talk becomes a ranked list of clips." },
      { title: "Two people, one frame", text: "Smart reframe keeps faces in view as the conversation moves." },
      { title: "A week from one episode", text: "Schedule the best moments across YouTube, TikTok and Instagram." },
    ],
    steps: [
      { title: "Upload the episode", text: "Video podcasts in MP4, MOV or WebM." },
      { title: "Pick the moments", text: "Top picks first, or Find Clips for the one you remember." },
      { title: "Schedule the week", text: "Fill your posting slots from one calendar." },
    ],
    tools: ["ai-moments", "find-clips", "smart-reframe", "publish"],
    faq: [
      { q: "Do audio-only podcasts work?", a: "PeakSift works from video files; an audio-only episode needs a video version first." },
      { q: "Can I keep my show's look?", a: "Yes — save it in Brand Studio and every Short starts from it." },
    ],
  },
  {
    slug: "streamers",
    name: "Streamers",
    summary: "Clip the best of a long stream while it is still fresh.",
    title: "Clip the best of every stream while it's still fresh",
    lead: "Upload your VOD and PeakSift finds the moments worth posting, frames your face, captions what you said and helps you post while people still remember the stream.",
    visual: "reframe",
    reasons: [
      { title: "Hours to minutes", text: "PeakSift reads the whole VOD and ranks the moments, so you skip the scrubbing." },
      { title: "Your face in frame", text: "Smart reframe follows faces when you go vertical." },
      { title: "Post while it's fresh", text: "Schedule clips across the days after a stream." },
    ],
    steps: [
      { title: "Upload your VOD", text: "Download it from your platform, then drop it on Home." },
      { title: "Let PeakSift find moments", text: "Transcription and moments run by themselves." },
      { title: "Edit and post", text: "Auto Edit a first cut, then publish or schedule." },
    ],
    tools: ["ai-moments", "auto-edit", "smart-reframe", "captions"],
    faq: [
      { q: "Can I paste a Twitch or Kick link?", a: "Not yet — upload the video file. PeakSift only works with videos you upload yourself." },
      { q: "Does it find gameplay highlights without talking?", a: "PeakSift finds moments from what was said, so it works best when you talk through your stream." },
    ],
  },
  {
    slug: "educators",
    name: "Educators & coaches",
    summary: "Short lessons from long classes and calls.",
    title: "Turn long classes and calls into short lessons",
    lead: "Every lesson has tips people would save. PeakSift finds them, captions them clearly and keeps your brand on every one.",
    visual: "captions",
    reasons: [
      { title: "Tips that stand alone", text: "Moments are chosen for being complete on their own — a rule, a tip, an answer." },
      { title: "Clear captions", text: "Word-by-word captions for viewers watching on mute." },
      { title: "Always on-brand", text: "Your colours, logo and end card on every lesson." },
    ],
    steps: [
      { title: "Upload a class or call", text: "Recorded lessons, webinars or coaching calls." },
      { title: "Find the lessons", text: "AI moments, or search for the topic you taught." },
      { title: "Brand and publish", text: "Start from your template, then schedule." },
    ],
    tools: ["ai-moments", "find-clips", "captions", "brand-studio"],
    faq: [
      { q: "Can I use it in Arabic or French?", a: "Yes — transcription and captions work in many languages, including Arabic." },
    ],
  },
  {
    slug: "interviews",
    name: "Interviews & talks",
    summary: "The quotable moments from every conversation.",
    title: "The quotable moments from every interview and talk",
    lead: "PeakSift finds the lines worth quoting, keeps the speaker in frame and turns each into a captioned Short.",
    visual: "auto-edit",
    reasons: [
      { title: "Quotes, not guesses", text: "Every moment is the exact words that were said." },
      { title: "Speaker in frame", text: "Smart reframe keeps faces in view in vertical." },
      { title: "A first cut in one click", text: "Auto Edit plans framing, captions, hook and visuals." },
    ],
    steps: [
      { title: "Upload the recording", text: "Interviews, panels, keynotes, talks." },
      { title: "Pick the quotes", text: "Review the ranked moments with their reasons." },
      { title: "Auto Edit and post", text: "Apply a plan, fine-tune, publish or schedule." },
    ],
    tools: ["ai-moments", "auto-edit", "smart-reframe", "publish"],
    faq: [
      { q: "Can I add slides or photos?", a: "Yes — upload them as visuals and place them as cutaways or picture-in-picture." },
    ],
  },
];

export type Guide = {
  slug: string;
  title: string;
  summary: string;
  minutes: number;
  sections: { heading: string; body: string[] }[];
};

export const GUIDES: Guide[] = [
  {
    slug: "getting-started",
    title: "Get your first moments from a long video",
    summary: "Drop a video on Home and let PeakSift do the rest.",
    minutes: 3,
    sections: [
      { heading: "Drop a video on Home", body: ["Open Home and use the box at the top: drop a video file or browse for one. MP4, MOV and WebM work.", "PeakSift suggests a project name from the file — change it if you like — then press Find my moments."] },
      { heading: "Let it run", body: ["PeakSift uploads the video, transcribes it and finds moments, one after another. You can leave the page; the project shows each step and updates by itself."] },
      { heading: "Review your moments", body: ["Open the project's Moments tab. The strongest moments come first, each with the reason it was picked. Preview one, then save it or dismiss it.", "Saved moments are where Shorts start."] },
    ],
  },
  {
    slug: "find-a-moment",
    title: "Find a specific moment with Find Clips",
    summary: "Search your video the way you remember it.",
    minutes: 2,
    sections: [
      { heading: "Open Find clips", body: ["In a project's Moments tab, the Find clips box sits above the moments PeakSift found."] },
      { heading: "Describe the moment", body: ["Type what you remember — “the part where I explain pricing” — and press Find clips. PeakSift shows the places in your transcript where you said it, with times."] },
      { heading: "Keep the right one", body: ["Preview a result to play just that stretch. Press Keep this moment and it appears under Saved with your other moments."] },
    ],
  },
  {
    slug: "first-short",
    title: "Make your first Short in the editor",
    summary: "Framing, captions, an opening line and a render.",
    minutes: 4,
    sections: [
      { heading: "Create a Short from a moment", body: ["From a saved moment, choose Create Short. PeakSift cuts the clip and opens the editor with the preview on the left and the tools on the right."] },
      { heading: "Style and Captions", body: ["In Style, pick a layout: Smart reframe, centre crop, blur background or fit. In Captions, choose Focus, Punch, Minimal or Boxed and a position."] },
      { heading: "Opening, Visuals, Sound and Brand", body: ["Opening adds a hook from your own words. Visuals places your images and clips, Sound adds your music and effects, and Brand applies your colours and logo."] },
      { heading: "Render", body: ["Press Render. When it is ready, the Short appears in your Shorts library to download, publish or schedule."] },
    ],
  },
  {
    slug: "auto-edit",
    title: "Let Auto Edit make the first cut",
    summary: "Review a plan, apply it, then fine-tune.",
    minutes: 2,
    sections: [
      { heading: "Start Auto Edit", body: ["From a moment, open Auto Edit. PeakSift plans the framing, captions, hook and visuals, following your template."] },
      { heading: "Read the plan", body: ["Each choice comes with a short explanation. Anything PeakSift could not do is listed with the reason."] },
      { heading: "Apply and adjust", body: ["Apply the plan to open it in the editor as a new version. Change anything, then render."] },
    ],
  },
  {
    slug: "schedule-posts",
    title: "Schedule a week of Shorts",
    summary: "Posting times, the calendar and the next free slot.",
    minutes: 3,
    sections: [
      { heading: "Set your posting times", body: ["Open Schedule and choose Posting times. Pick the days and times you want to post each week, in your own time zone."] },
      { heading: "Schedule a Short", body: ["From a finished Short, open Publish, pick the platform, then choose When: now, a time, or the next free slot."] },
      { heading: "Manage the week", body: ["The Schedule calendar shows what is planned and what is out. Change a time, publish now or cancel a post until it goes out."] },
    ],
  },
  {
    slug: "connect-platforms",
    title: "Connect YouTube, TikTok and Instagram",
    summary: "One connection per platform, in Settings.",
    minutes: 2,
    sections: [
      { heading: "Open Settings", body: ["Settings lists each platform your PeakSift server has switched on, with its connection status."] },
      { heading: "Connect", body: ["Press Connect and sign in on the platform's own page. PeakSift only asks for what posting needs, and keeps your tokens encrypted."] },
      { heading: "Disconnect any time", body: ["Disconnecting removes PeakSift's access. Shorts you already published stay on the platform."] },
    ],
  },
];

export const toolBySlug = (slug: string) => TOOLS.find((tool) => tool.slug === slug);
export const audienceBySlug = (slug: string) => AUDIENCES.find((audience) => audience.slug === slug);
export const guideBySlug = (slug: string) => GUIDES.find((guide) => guide.slug === slug);
