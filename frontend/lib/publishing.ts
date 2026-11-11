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
export const publishEdit = (editId: string, metadata: PublishMetadata) =>
  postJson<PublishJob>(`/edits/${editId}/publish`, metadata);
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
