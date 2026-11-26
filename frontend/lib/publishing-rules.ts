/** Types and pure rules for publishing (no imports: unit-tested with node --test). */

export type Privacy = "private" | "unlisted" | "public";
export type PublishStatus =
  /** Waiting for its scheduled time; nothing is uploaded yet. */
  | "scheduled"
  | "queued"
  | "preparing"
  | "uploading"
  | "uploaded"
  | "processing"
  | "published"
  | "failed"
  | "provider_failed";

export type YouTubeConnection = {
  provider: "youtube";
  status: "connected" | "needs_reconnect";
  /** Empty until the first upload reports the channel (PeakSift asks for upload access only). */
  account_title: string;
  connected_at: string;
  /** The creator granted the separate, read-only analytics upgrade. */
  analytics_access: boolean;
};

export type YouTubeStatus = {
  enabled: boolean;
  /** The server offers performance analytics (each creator still opts in). */
  analytics_enabled: boolean;
  connection: YouTubeConnection | null;
};

export type PublishMetadata = {
  title: string;
  description: string;
  tags: string[];
  privacy: Privacy;
  made_for_kids: boolean;
};

export type PublishJob = PublishMetadata & {
  id: string;
  edit_id: string;
  provider: string;
  status: PublishStatus;
  progress_percent: number;
  bytes_uploaded: number;
  bytes_total: number | null;
  video_url: string | null;
  studio_url: string | null;
  /** Uploaded by the in-memory test provider (non-production stacks): no real video. */
  simulated: boolean;
  error_code: string | null;
  error_message: string | null;
  retryable: boolean;
  is_stale: boolean;
  /** YouTube's processing is still being checked (false once known, or unknowable). */
  awaiting_processing: boolean;
  attempt: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  published_at: string | null;
  /** When the creator asked for it to go out (null when published right away). */
  scheduled_at?: string | null;
};

export type PublishPanel = {
  enabled: boolean;
  connection: YouTubeConnection | null;
  edit_ready: boolean;
  defaults: PublishMetadata;
  jobs: PublishJob[];
};

/** Google's consent page is a full navigation away (the API redirects back to /settings). */
export function isGoogleConsentUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.hostname === "accounts.google.com";
  } catch {
    return false;
  }
}

// --- YouTube's rules, mirrored for live feedback (the API is the authority) -------------------

export const TITLE_MAX = 100;
export const DESCRIPTION_MAX_BYTES = 5000;
export const TAGS_MAX = 500;
export const TAG_COUNT_MAX = 50;

export const characters = (text: string) => Array.from(text).length; // code points, like Python
export const bytes = (text: string) => new TextEncoder().encode(text).length;

/** "a, two words ,b" → ["a", "two words", "b"]: commas separate tags. */
export function parseTags(text: string): string[] {
  return text
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

/** YouTube's count: each tag, +2 for quotes around a tag with a space, + commas between. */
export function tagsLength(tags: string[]): number {
  if (tags.length === 0) return 0;
  return tags.reduce((sum, tag) => sum + characters(tag) + (tag.includes(" ") ? 2 : 0), 0) + tags.length - 1;
}

export type FieldProblems = Partial<Record<"title" | "description" | "tags", string>>;

const ANGLE = /[<>]/;

export function metadataProblems(metadata: PublishMetadata): FieldProblems {
  const problems: FieldProblems = {};
  const title = metadata.title.trim();
  if (!title) problems.title = "Add a title";
  else if (characters(title) > TITLE_MAX) problems.title = `${characters(title)} / ${TITLE_MAX} characters`;
  else if (ANGLE.test(title)) problems.title = "YouTube does not accept < or >";
  const description = metadata.description.trim();
  if (bytes(description) > DESCRIPTION_MAX_BYTES)
    problems.description = `${bytes(description)} / ${DESCRIPTION_MAX_BYTES} bytes`;
  else if (ANGLE.test(description)) problems.description = "YouTube does not accept < or >";
  const tags = metadata.tags;
  const unique = new Set(tags.map((tag) => tag.toLocaleLowerCase()));
  if (tags.length > TAG_COUNT_MAX) problems.tags = `Use at most ${TAG_COUNT_MAX} tags`;
  else if (unique.size !== tags.length) problems.tags = "Each tag can appear only once";
  else if (tags.some((tag) => ANGLE.test(tag))) problems.tags = "YouTube does not accept < or >";
  else if (tagsLength(tags) > TAGS_MAX) problems.tags = `${tagsLength(tags)} / ${TAGS_MAX} characters`;
  return problems;
}

// --- job stages ---------------------------------------------------------------------------------

export const ACTIVE_STATUSES: PublishStatus[] = ["queued", "preparing", "uploading"];
export const STAGES = ["queued", "preparing", "uploading", "uploaded", "processing", "published"] as const;

export function isActive(job: PublishJob): boolean {
  return ACTIVE_STATUSES.includes(job.status) && !job.is_stale;
}

/** After the upload, while the server still checks YouTube's processing. */
export function isFollowing(job: PublishJob): boolean {
  return job.awaiting_processing;
}

export function stageLabel(job: PublishJob): string {
  switch (job.status) {
    case "scheduled":
      return "Scheduled";
    case "queued":
      return job.is_stale ? "Stalled" : "Waiting to start";
    case "preparing":
      return job.is_stale ? "Stalled" : "Preparing the upload";
    case "uploading": {
      if (job.is_stale) return "Stalled";
      return `Uploading to YouTube · ${job.progress_percent}%`;
    }
    case "uploaded":
      if (job.awaiting_processing) return "Uploaded · checking processing";
      return job.simulated ? "Uploaded (simulated)" : "Uploaded to YouTube";
    case "processing":
      return "YouTube is processing the video";
    case "published":
      return job.simulated ? "Published (simulated)" : "Published on YouTube";
    case "failed":
      return "Not uploaded";
    case "provider_failed":
      return "YouTube could not publish it";
  }
}

const PRIVACY_LABELS: Record<Privacy, string> = {
  private: "Private",
  unlisted: "Unlisted",
  public: "Public",
};
export const privacyLabel = (privacy: Privacy) => PRIVACY_LABELS[privacy];

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const RETURN_PATHS = [new RegExp(`^/shorts/${UUID}$`, "i"), new RegExp(`^/projects/${UUID}/clips/${UUID}(\\?edit=${UUID})?$`, "i")];

/** Where to come back to after connecting YouTube: only a Short or an editor of this app, never
 * an address from elsewhere (anything else is dropped). */
export function safeReturnPath(path: string | null | undefined): string | null {
  if (!path) return null;
  return RETURN_PATHS.some((pattern) => pattern.test(path)) ? path : null;
}

/** What the /settings page shows after Google sends the browser back. */
export function connectionOutcome(params: URLSearchParams): { ok: boolean; message: string } | null {
  const outcome = params.get("youtube");
  if (outcome === "connected") return { ok: true, message: "Your YouTube account is connected." };
  if (outcome !== "error") return null;
  const reasons: Record<string, string> = {
    denied: "You declined access on Google's consent screen, so nothing was connected.",
    invalid_state: "That connection link was not valid for this account. Start again from here.",
    expired: "The connection took too long. Start again from here.",
    signin_required: "Sign in to PeakSift, then connect again.",
    missing_refresh_token: "Google did not grant lasting access. Remove PeakSift from your Google account's third-party access, then connect again.",
    insufficient_scope: "Upload access was not granted. Connect again and allow uploading videos.",
    exchange_failed: "Google could not complete the connection. Try again.",
    disabled: "YouTube publishing is not enabled on this server.",
  };
  return { ok: false, message: reasons[params.get("reason") ?? ""] ?? "The connection did not complete. Try again." };
}
