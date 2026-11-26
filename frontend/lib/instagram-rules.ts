// Instagram Reels (pure rules, no React): checking a caption before it is sent, the words for
// coming back from Meta's consent screen and for a post's state. Unit-tested with node --test.
// The server checks everything again.

export const INSTAGRAM_CAPTION_MAX = 2200;
export const INSTAGRAM_MAX_HASHTAGS = 30;
export const INSTAGRAM_MAX_MENTIONS = 20;
export const INSTAGRAM_MIN_SECONDS = 3;
export const INSTAGRAM_MAX_SECONDS = 15 * 60;

const count = (text: string, mark: string) => text.split(/\s+/).filter((word) => word.startsWith(mark)).length;

export type InstagramProblems = Partial<Record<"caption" | "duration", string>>;

/** What stops this Reel from being sent, by field. Empty when it can go. */
export function instagramProblems(caption: string, durationSeconds: number | null): InstagramProblems {
  const problems: InstagramProblems = {};
  const text = caption.trim();
  if (text.length > INSTAGRAM_CAPTION_MAX) {
    problems.caption = `The caption is ${text.length} characters; Instagram allows ${INSTAGRAM_CAPTION_MAX}.`;
  } else if (count(text, "#") > INSTAGRAM_MAX_HASHTAGS) {
    problems.caption = `Instagram allows at most ${INSTAGRAM_MAX_HASHTAGS} hashtags.`;
  } else if (count(text, "@") > INSTAGRAM_MAX_MENTIONS) {
    problems.caption = `Instagram allows at most ${INSTAGRAM_MAX_MENTIONS} mentions.`;
  }
  if (durationSeconds != null && (durationSeconds < INSTAGRAM_MIN_SECONDS || durationSeconds > INSTAGRAM_MAX_SECONDS)) {
    problems.duration = "Instagram Reels last between 3 seconds and 15 minutes.";
  }
  return problems;
}

/** "12 hashtags · 2 mentions" under the caption, when there are any. */
export function captionCounts(caption: string): string {
  const parts: string[] = [];
  const tags = count(caption, "#");
  const mentions = count(caption, "@");
  if (tags) parts.push(`${tags} hashtag${tags === 1 ? "" : "s"}`);
  if (mentions) parts.push(`${mentions} mention${mentions === 1 ? "" : "s"}`);
  return parts.join(" · ");
}

/** Meta's consent screen and nothing else. */
export function isMetaConsentUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.hostname === "www.facebook.com" && /^\/v\d+\.\d+\/dialog\/oauth$/.test(parsed.pathname);
  } catch {
    return false;
  }
}

/** What coming back from Meta's consent screen means (null when the address says nothing). */
export function instagramOutcome(params: URLSearchParams): { ok: boolean; message: string } | null {
  const outcome = params.get("instagram");
  if (outcome === "connected") return { ok: true, message: "Your Instagram account is connected." };
  if (outcome !== "error") return null;
  const reasons: Record<string, string> = {
    denied: "You declined access on Facebook's screen, so nothing was connected.",
    invalid_state: "That connection link was not valid for this account. Start again from here.",
    expired: "The connection took too long. Start again from here.",
    signin_required: "Sign in to PeakSift, then connect again.",
    missing_refresh_token: "Facebook did not grant lasting access. Connect again.",
    insufficient_scope: "Permission to publish to Instagram was not granted. Connect again and allow it.",
    no_instagram_account:
      "None of your Facebook Pages has an Instagram professional account linked. Switch Instagram to a professional account, link it to a Page, then connect again.",
    exchange_failed: "Facebook could not complete the connection. Try again.",
    disabled: "Instagram publishing is not enabled on this server.",
  };
  return { ok: false, message: reasons[params.get("reason") ?? ""] ?? "The connection did not complete. Try again." };
}

/** Where a Reel stands, in words. Never "posted" before PeakSift has published it on Instagram. */
export function instagramStage(job: {
  status: string;
  progress_percent: number;
  is_stale: boolean;
  simulated: boolean;
}): { label: string; tone: "working" | "done" | "attention" } {
  if (job.is_stale) return { label: "Stalled", tone: "attention" };
  switch (job.status) {
    case "queued":
    case "preparing":
      return { label: "Getting ready", tone: "working" };
    case "uploading":
      return { label: "Uploading to Instagram", tone: "working" };
    case "uploaded":
    case "processing":
      return { label: "Uploaded. Instagram is processing it, then PeakSift posts it", tone: "working" };
    case "published":
      return { label: job.simulated ? "Posted (simulated)" : "Posted on Instagram", tone: "done" };
    case "provider_failed":
      return { label: "Instagram could not post it", tone: "attention" };
    default:
      return { label: "Not posted", tone: "attention" };
  }
}
