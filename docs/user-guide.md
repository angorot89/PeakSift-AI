# PeakSift user guide

From a long recording to a short on YouTube, in seventeen steps — or let **Auto Edit** make
the first draft (see below).

1. **Create your account.** Open PeakSift, choose **Create account**, and register with your email
   and a password of at least 8 characters. You stay signed in on this browser until you log
   out.
2. **Create a project.** **Projects → New project**, give it a name (for example the stream or
   episode). Everything for one recording lives in its project.
3. **Upload your video.** On the project page, drop an MP4, MOV or WebM file into **Source
   video** (up to 2 GB by default). The progress bar is the real upload.
4. **Check the source.** PeakSift reads the file and shows its duration, resolution and frame
   rate with a preview player. An unreadable file says so clearly — upload another.
5. **Transcribe it.** In **Transcript**, start the transcription. It runs in the background
   (you can leave the page); progress is real, and a failed or stalled job offers **Retry**.
6. **Read the transcript.** Every line has its timestamp; copy it if you need it elsewhere.
7. **Find clip moments.** In **Clip moments**, choose the AI provider and model your server
   offers and start the analysis. PeakSift reads the transcript in sections and proposes
   moments with a title, hook and reason.
8. **Review the candidates.** Candidates are ranked by a 0–100 editorial score (a judgement of
   the moment, not a prediction of views). Preview each range of your video, **Save** the
   good ones and **Dismiss** the rest.
9. **Generate a clip.** **Generate clip** renders exactly that moment from your original
   video. When it is ready you can play it and **Download MP4**.
10. **Open the editor.** **Create vertical short** opens the short-form editor for that clip.
    Pick a layout: **Center crop**, **Blur background** or **Fit**.
11. **Frame it.** **Smart reframe → Analyze framing** follows visible faces with a smooth
    moving crop (it stays centred when no face is clear); or choose **Focal point** and place
    the crop yourself. PeakSift tells you how confident the framing is.
12. **Add captions and a hook.** Turn captions on; **Generate word sync** times every word so
    the spoken word is highlighted (or use **Phrase timed**). Pick a preset — **Focus**,
    **Punch**, **Minimal** or **Boxed** — a position, and an optional opening hook. The
    **Safe area** guide shows where platform buttons cover the screen.
13. **Add visuals (optional).** On the project page, upload your own images (JPEG, PNG, WebP)
    and B-roll videos (MP4, MOV, WebM) to the **Visual assets** library. PeakSift prepares
    **visual search** for each one in the background, so you can find it by what it shows
    (see "Visual search" below); a description and tags still help. In the editor's
    **Visuals** section, **Suggest B-roll** asks the local AI where a visual would help and
    what it should show — each suggestion lists your **best matches** (by what they show and by
    their words) to use in one click — or **Add visual** to choose any asset. Each visual is a **Cutaway** (replaces the picture; your
    voice keeps playing), **Picture-in-picture** or an image **Overlay**, with start/end,
    position, size, opacity, the video's start point, looping and a cut or fade. Captions
    and the hook always stay on top. B-roll sound is never used.
14. **Finish the audio.** In **Audio**, adjust the original level, add music you own (start
    point, loop, fades, volume) with automatic ducking under speech, place sound effects on
    the timeline, and keep loudness normalization on. Preview plays them with the video.
15. **Render and download.** **Render short** produces a 1080 × 1920 MP4 in the background.
    Each combination of settings is its own version; play any version and **Download short**.
16. **Connect YouTube.** **Settings → YouTube → Connect YouTube** opens Google's consent page.
    PeakSift asks only to upload videos — it cannot read, change or delete anything on your
    channel. You can **Disconnect** at any time.
17. **Publish.** In the editor, **Publish to YouTube** (beside Download short) opens the
    publish dialog. Review the title, description and tags (the counters show YouTube's
    limits), keep **Private** or choose Unlisted/Public, answer whether it is made for kids,
    and publish. The dialog shows the real progress — preparing, uploading, uploaded — with
    links to the video and YouTube Studio once YouTube has it. If something goes wrong before
    the upload finished, **Retry** continues where it stopped; a published short is never
    uploaded twice.

## Auto Edit — the quick path

Auto Edit proposes a complete, reviewable first draft of a short from a generated clip. You
always review it, and you can change anything before it renders.

1. **Generate a clip** (steps 1–9 above).
2. **Choose Auto Edit.** On the clip's card (**Auto Edit**, beside Create short) or in the
   editor's header. For the best plan, first open the editor and **Analyze framing**,
   **Generate word sync** and **Suggest B-roll** — Auto Edit uses what is ready and never
   starts these for you.
3. **Select a recipe.** **Clean** (professional, little on screen), **Punchy** (high energy),
   **Story** (explainers and stories) or **Minimal** (speaker first). Optionally choose one of
   your music tracks — Auto Edit never picks music on its own.
4. **Review the plan.** Each section — framing, captions, hook, visuals, audio — shows the
   choice and a short reason, and what was left out and why. It says whether the local AI
   planned it or PeakSift's built-in rules did (when the local AI was unavailable).
5. **Apply.** **Use this edit** renders the short with exactly these settings and opens it in
   the editor. **Try another plan** makes a new plan (earlier ones stay in the list).
6. **Make optional manual changes.** **Edit choices** opens the plan's settings in the editor
   without rendering; the editor works as always.
7. **Render.** **Render short** (or the render started by **Use this edit**) produces the 1080 ×
   1920 MP4.
8. **Publish or download.** **Download short**, or **Publish to YouTube** (step 17).

Auto Edit chooses only between options the editor already has, from your own media. It places a
visual only when it strongly matches a suggestion, by what it shows or by its words, and says
which. It does not publish, search the internet for or generate media, or predict how a short
will perform.

## Visual search — find your visuals by what they show

1. **Upload your visual assets** to a project's **Visual assets** library, as always. Camera
   names like `IMG_7834.jpg` are fine; tags are optional.
2. **PeakSift prepares visual search automatically.** A local model on PeakSift's own server
   looks at each image (and a few frames of each video); nothing is sent anywhere. A card shows
   **Preparing visual search** for a moment. You can use the asset right away.
3. **Search by what appears in the visual.** Type in **Search your visuals**, for example
   "rocket launch", "bridge", "city skyline" or "microphone". Results show **Strong match** or
   **Possible match**. A video shows where its best scene is (**Best at 0:08**), and its preview
   opens there.
4. **Generate B-roll suggestions** in the editor's **Visuals** section (**Suggest B-roll**).
5. **Review the visually matched assets.** Each suggestion lists its **Best matches** with
   *Matched visually to “…”* or *Matched by its name or tags*. **Preview** a match (a video
   opens at its matched scene). **Use asset** opens a chooser that already searches for the
   suggestion's words; clear it to browse everything.
6. **Use them by hand, or through Auto Edit.** **Use** places a match; a video starts at its
   matched scene. Auto Edit places only **strong** matches and tells you how each was matched.
   Possible matches stay for you to decide.
7. **Render** as usual.

If a visual cannot be analysed (for example a video that is completely black), its card shows
**Visual search unavailable**. You can still use it by hand, and **Retry visual analysis** in
its preview tries again without re-uploading.

Good to know about visual search:

- It finds pictures that *look* like your words. That is not understanding: a photo of an
  intact bridge can "match" a sentence about a bridge collapsing. Always review what you use.
- Long videos are judged by a few sampled frames, so a very brief moment can be missed.
- It works best for common objects and scenes, and less well for abstract ideas, text inside
  images, or specific people or places. It never recognises faces.
- There is no internet or stock search, and nothing is generated: it only searches **your**
  uploads.

## Good to know

- **Visibility:** new uploads are private by default. Google keeps videos uploaded through
  apps it has not yet verified private, whatever you choose — the dialog says when that
  applies. Change visibility in YouTube Studio.
- **After publishing:** PeakSift cannot edit or delete the video on YouTube; use YouTube
  Studio.
- **Reconnect:** if you remove PeakSift's access in your Google account (or it expires),
  Settings shows **Reconnect** and publishing asks you to reconnect first.
- **Deleting a project** (bottom of the project page, confirmed by typing its exact name)
  permanently removes it with all its videos, clips, shorts, audio and files. It does not
  touch anything already published to YouTube.
- **Your media is private:** only you can play or download your uploads, visuals, clips and
  shorts. Upload only footage, images and music you own or are allowed to use — PeakSift
  never searches or downloads media for you.
- **The editor continues where you were:** it opens with your newest version's settings (or
  the version or plan you came from); **Reset to defaults** starts over.
- **Visuals in use:** a visual used by a rendered or saved short cannot be deleted until
  those versions are deleted, so a short never loses a picture.
- **Suggestions are suggestions:** the AI only proposes moments grounded in what was said;
  a clip can get none. Matching reads words, not pictures — tag your assets.
