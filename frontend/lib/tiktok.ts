import { apiFetch, postJson } from "@/lib/api";
import type { PublishJob, PublishPanel, YouTubeConnection } from "@/lib/publishing-rules";
import { isTikTokConsentUrl, type TikTokCreator } from "@/lib/tiktok-rules";

export * from "@/lib/tiktok-rules";

export type TikTokConnection = Omit<YouTubeConnection, "provider" | "analytics_access"> & { provider: "tiktok" };
export type TikTokStatus = { enabled: boolean; connection: TikTokConnection | null };

export const getTikTokStatus = () => apiFetch<TikTokStatus>("/publishing/tiktok");
export const getTikTokCreator = () => apiFetch<TikTokCreator>("/publishing/tiktok/creator");
export const disconnectTikTok = () =>
  apiFetch<{ revoked_with_provider: boolean }>("/publishing/tiktok", { method: "DELETE" });

export const getTikTokPanel = (editId: string) => apiFetch<PublishPanel>(`/edits/${editId}/publish?platform=tiktok`);

/** Post to TikTok now, or at `scheduledAt` (an ISO time with its zone) when given. */
export const publishToTikTok = (
  editId: string,
  title: string,
  caption: string,
  options: Record<string, boolean | string>,
  scheduledAt?: string,
) =>
  postJson<PublishJob>(`/edits/${editId}/publish`, {
    platform: "tiktok",
    title,
    description: caption,
    options,
    ...(scheduledAt ? { scheduled_at: scheduledAt } : {}),
  });

/** Open TikTok's consent screen. TikTok sends the browser back to Settings. */
export async function connectTikTok(): Promise<void> {
  const { authorization_url } = await postJson<{ authorization_url: string }>("/publishing/tiktok/connect", {});
  if (!isTikTokConsentUrl(authorization_url)) throw new Error("Unexpected sign-in address.");
  window.location.assign(authorization_url);
}
