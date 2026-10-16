import { apiFetch, postJson } from "@/lib/api";
import type { PublishJob, PublishMetadata, PublishPanel, YouTubeStatus } from "@/lib/publishing-rules";

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

