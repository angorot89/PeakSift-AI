import { apiFetch, postJson } from "@/lib/api";
import type { PerformanceOverview, SyncInfo, VideoPerformanceDetail } from "@/lib/performance-rules";

export * from "@/lib/performance-rules";

export const getPerformance = () => apiFetch<PerformanceOverview>("/performance");
export const getVideoPerformance = (id: string) => apiFetch<VideoPerformanceDetail>(`/performance/videos/${id}`);
export const refreshVideoPerformance = (id: string) => postJson<SyncInfo>(`/performance/videos/${id}/refresh`, {});
/** The explicit, creator-initiated analytics permission upgrade (read-only scopes). */
export const startAnalyticsConnection = () =>
  postJson<{ authorization_url: string }>("/publishing/youtube/analytics/connect", {});
