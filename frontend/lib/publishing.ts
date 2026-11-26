import { apiFetch, postJson } from "@/lib/api";
import { isGoogleConsentUrl, safeReturnPath, type PublishJob, type PublishMetadata, type PublishPanel, type YouTubeStatus } from "@/lib/publishing-rules";

export * from "@/lib/publishing-rules";

// --- API --------------------------------------------------------------------------------------

export const getYouTubeStatus = () => apiFetch<YouTubeStatus>("/publishing/youtube");
export const startYouTubeConnection = () =>
  postJson<{ authorization_url: string }>("/publishing/youtube/connect", {});
export const disconnectYouTube = () =>
  apiFetch<{ revoked_with_provider: boolean }>("/publishing/youtube", { method: "DELETE" });

export const getPublishPanel = (editId: string) => apiFetch<PublishPanel>(`/edits/${editId}/publish`);
/** Publish now, or at `scheduledAt` (an ISO time with its zone) when given. */
export const publishEdit = (editId: string, metadata: PublishMetadata, scheduledAt?: string) =>
  postJson<PublishJob>(`/edits/${editId}/publish`, scheduledAt ? { ...metadata, scheduled_at: scheduledAt } : metadata);

/** One post on the calendar: a publish job with the Short it belongs to. */
export type CalendarItem = {
  job: PublishJob;
  /** Where it sits: its scheduled time, else when it was published or started. */
  at: string;
  short_title: string;
  project_id: string;
  project_name: string;
  clip_id: string;
};
export type PublishCalendar = { items: CalendarItem[]; connection_ready: boolean };

export const getCalendar = (from: Date, to: Date) =>
  apiFetch<PublishCalendar>(
    `/publish-jobs?from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(to.toISOString())}`,
  );
export const reschedulePost = (jobId: string, scheduledAt: string) =>
  apiFetch<PublishJob>(`/publish-jobs/${jobId}/schedule`, {
    method: "PATCH",
    body: JSON.stringify({ scheduled_at: scheduledAt }),
  });
export const publishPostNow = (jobId: string) => postJson<PublishJob>(`/publish-jobs/${jobId}/publish-now`, {});
export const cancelPost = (jobId: string) => apiFetch<void>(`/publish-jobs/${jobId}`, { method: "DELETE" });
export const getPublishJob = (jobId: string) => apiFetch<PublishJob>(`/publish-jobs/${jobId}`);
export const retryPublishJob = (jobId: string) =>
  postJson<PublishJob>(`/publish-jobs/${jobId}/retry`, {});


// --- connect, then come back --------------------------------------------------------------------

const RETURN_KEY = "peaksift.youtube.return";

/** Start Google's consent and remember where to come back to (a Short or an editor of this app). */
export async function connectYouTube(returnTo?: string): Promise<void> {
  const { authorization_url } = await startYouTubeConnection();
  if (!isGoogleConsentUrl(authorization_url)) throw new Error("Unexpected sign-in address.");
  const back = safeReturnPath(returnTo);
  try {
    if (back) window.sessionStorage.setItem(RETURN_KEY, back);
    else window.sessionStorage.removeItem(RETURN_KEY);
  } catch {
    // storage unavailable: the creator comes back to Settings, which links on
  }
  window.location.assign(authorization_url); // Google sends the browser back to /settings
}

/** The Short or editor to return to after connecting (null when there is none). */
export function peekReturnPath(): string | null {
  try {
    return safeReturnPath(window.sessionStorage.getItem(RETURN_KEY));
  } catch {
    return null;
  }
}

export function forgetReturnPath(): void {
  try {
    window.sessionStorage.removeItem(RETURN_KEY);
  } catch {
    // nothing stored
  }
}

/** A weekly posting time: a weekday (0 = Monday) and a wall-clock time in the creator's zone. */
export type PostingSlot = { weekday: number; time: string };
export type PostingSlots = {
  timezone: string | null;
  slots: PostingSlot[];
  /** The next free slot times (ISO, UTC): not in the past, not taken by a scheduled post. */
  upcoming: string[];
};

export const getPostingSlots = () => apiFetch<PostingSlots>("/posting-slots");
export const savePostingSlots = (timezone: string, slots: PostingSlot[]) =>
  apiFetch<PostingSlots>("/posting-slots", { method: "PUT", body: JSON.stringify({ timezone, slots }) });

/** A platform PeakSift can publish to, whether this server offers it, and the creator's connection. */
export type PublishingPlatform = {
  key: "youtube" | "tiktok" | "instagram";
  label: string;
  account_noun: string;
  enabled: boolean;
  connection: { provider: string; status: "connected" | "needs_reconnect"; account_title: string } | null;
};
export const getPlatforms = () => apiFetch<PublishingPlatform[]>("/publishing/platforms");
