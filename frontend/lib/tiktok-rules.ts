// TikTok publishing (pure rules, no React): the words for TikTok's visibility levels, checking
// a post before it is sent, and the options the server stores. Unit-tested with node --test.
// The server checks everything again against what TikTok offers the creator at that moment.

export type TikTokPrivacy = "PUBLIC_TO_EVERYONE" | "MUTUAL_FOLLOW_FRIENDS" | "FOLLOWER_OF_CREATOR" | "SELF_ONLY";

/** What TikTok offers this creator for a post right now. */
export type TikTokCreator = {
  nickname: string;
  username: string;
  privacy_levels: string[];
  comment_disabled: boolean;
  duet_disabled: boolean;
  stitch_disabled: boolean;
  max_duration_seconds: number | null;
};

export type TikTokForm = {
  caption: string;
  /** Empty until the creator chooses: TikTok requires a choice, never a default. */
  privacy: TikTokPrivacy | "";
  allowComment: boolean;
  allowDuet: boolean;
  allowStitch: boolean;
  commercial: boolean;
  yourBrand: boolean;
  brandedContent: boolean;
  musicConfirmed: boolean;
};

export const TIKTOK_CAPTION_MAX = 2200; // UTF-16 units, which is what a JS string's length counts

export const EMPTY_TIKTOK_FORM: TikTokForm = {
  caption: "",
  privacy: "",
  allowComment: false,
  allowDuet: false,
  allowStitch: false,
  commercial: false,
  yourBrand: false,
  brandedContent: false,
  musicConfirmed: false,
};

const PRIVACY_LABELS: Record<TikTokPrivacy, string> = {
  PUBLIC_TO_EVERYONE: "Everyone",
  FOLLOWER_OF_CREATOR: "Followers",
  MUTUAL_FOLLOW_FRIENDS: "Friends (followers you follow back)",
  SELF_ONLY: "Only me",
};

export const tiktokPrivacyLabel = (level: string): string => PRIVACY_LABELS[level as TikTokPrivacy] ?? level;

/** The levels TikTok offers, in TikTok's order, minus what branded content rules out. */
export function privacyChoices(creator: TikTokCreator, form: Pick<TikTokForm, "commercial" | "brandedContent">) {
  return creator.privacy_levels
    .filter((level) => level in PRIVACY_LABELS)
    .map((level) => ({
      value: level as TikTokPrivacy,
      label: PRIVACY_LABELS[level as TikTokPrivacy],
      // TikTok: branded content cannot be visible only to the creator.
      disabled: level === "SELF_ONLY" && form.commercial && form.brandedContent,
    }));
}

export type TikTokProblems = Partial<Record<"caption" | "privacy" | "commercial" | "music" | "duration", string>>;

/** What stops this post from being sent, by field. Empty when it can go. */
export function tiktokProblems(form: TikTokForm, creator: TikTokCreator, durationSeconds: number | null): TikTokProblems {
  const problems: TikTokProblems = {};
  if (form.caption.length > TIKTOK_CAPTION_MAX) {
    problems.caption = `The caption is ${form.caption.length} characters; TikTok allows ${TIKTOK_CAPTION_MAX}.`;
  }
  if (!form.privacy) problems.privacy = "Choose who can see this post.";
  else if (!creator.privacy_levels.includes(form.privacy)) problems.privacy = "That visibility is not available for your account.";
  else if (form.privacy === "SELF_ONLY" && form.commercial && form.brandedContent) {
    problems.privacy = "Branded content cannot be visible only to you.";
  }
  if (form.commercial && !form.yourBrand && !form.brandedContent) {
    problems.commercial = "Choose your brand, branded content or both.";
  }
  if (!form.musicConfirmed) problems.music = "Confirm TikTok's music usage terms to post.";
  const limit = creator.max_duration_seconds;
  if (limit && durationSeconds && durationSeconds > limit) {
    problems.duration = `This Short is longer than the ${limit} seconds TikTok allows you.`;
  }
  return problems;
}

/** The options sent with the post. Switches TikTok has turned off for the creator stay off. */
export function tiktokOptions(form: TikTokForm, creator: TikTokCreator): Record<string, boolean | string> {
  return {
    privacy_level: form.privacy,
    allow_comment: form.allowComment && !creator.comment_disabled,
    allow_duet: form.allowDuet && !creator.duet_disabled,
    allow_stitch: form.allowStitch && !creator.stitch_disabled,
    commercial: form.commercial,
    brand_organic: form.commercial && form.yourBrand,
    brand_content: form.commercial && form.brandedContent,
    music_usage_confirmed: form.musicConfirmed,
  };
}

/** What TikTok will label the post with, as its guidelines ask the creator to be told. */
export function commercialNotice(form: Pick<TikTokForm, "commercial" | "yourBrand" | "brandedContent">): string | null {
  if (!form.commercial || (!form.yourBrand && !form.brandedContent)) return null;
  return form.brandedContent
    ? "Your post will be labelled “Paid partnership”."
    : "Your post will be labelled “Promotional content”.";
}

/** TikTok's consent screen and nothing else. */
export function isTikTokConsentUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.hostname === "www.tiktok.com" && parsed.pathname.startsWith("/v2/auth/authorize");
  } catch {
    return false;
  }
}

/** What coming back from TikTok's consent screen means (null when the address says nothing). */
export function tiktokOutcome(params: URLSearchParams): { ok: boolean; message: string } | null {
  const outcome = params.get("tiktok");
  if (outcome === "connected") return { ok: true, message: "Your TikTok account is connected." };
  if (outcome !== "error") return null;
  const reasons: Record<string, string> = {
    denied: "You declined access on TikTok's screen, so nothing was connected.",
    invalid_state: "That connection link was not valid for this account. Start again from here.",
    expired: "The connection took too long. Start again from here.",
    signin_required: "Sign in to PeakSift, then connect again.",
    missing_refresh_token: "TikTok did not grant lasting access. Connect again.",
    insufficient_scope: "Permission to post videos was not granted. Connect again and allow it.",
    exchange_failed: "TikTok could not complete the connection. Try again.",
    disabled: "TikTok publishing is not enabled on this server.",
  };
  return { ok: false, message: reasons[params.get("reason") ?? ""] ?? "The connection did not complete. Try again." };
}

/** Where a TikTok post stands, in words. Never "posted" before TikTok says so. */
export function tiktokStage(job: {
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
      return { label: `Uploading to TikTok · ${job.progress_percent}%`, tone: "working" };
    case "uploaded":
    case "processing":
      return { label: "Uploaded. TikTok is processing it", tone: "working" };
    case "published":
      return { label: job.simulated ? "Posted (simulated)" : "Posted on TikTok", tone: "done" };
    case "provider_failed":
      return { label: "TikTok could not post it", tone: "attention" };
    default:
      return { label: "Not posted", tone: "attention" };
  }
}
