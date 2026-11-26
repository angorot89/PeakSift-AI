import { apiFetch, postJson } from "@/lib/api";
import { isMetaConsentUrl } from "@/lib/instagram-rules";
import type { PublishJob, PublishPanel } from "@/lib/publishing-rules";
import type { TikTokConnection } from "@/lib/tiktok";

export * from "@/lib/instagram-rules";

export type InstagramConnection = Omit<TikTokConnection, "provider"> & { provider: "instagram" };
export type InstagramStatus = { enabled: boolean; connection: InstagramConnection | null };

export const getInstagramStatus = () => apiFetch<InstagramStatus>("/publishing/instagram");
export const disconnectInstagram = () =>
  apiFetch<{ revoked_with_provider: boolean }>("/publishing/instagram", { method: "DELETE" });
export const getInstagramPanel = (editId: string) => apiFetch<PublishPanel>(`/edits/${editId}/publish?platform=instagram`);

/** Post a Reel now, or at `scheduledAt` (an ISO time with its zone) when given. */
export const publishToInstagram = (editId: string, title: string, caption: string, scheduledAt?: string) =>
  postJson<PublishJob>(`/edits/${editId}/publish`, {
    platform: "instagram",
    title,
    description: caption,
    ...(scheduledAt ? { scheduled_at: scheduledAt } : {}),
  });

/** Open Meta's consent screen. Meta sends the browser back to Settings. */
export async function connectInstagram(): Promise<void> {
  const { authorization_url } = await postJson<{ authorization_url: string }>("/publishing/instagram/connect", {});
  if (!isMetaConsentUrl(authorization_url)) throw new Error("Unexpected sign-in address.");
  window.location.assign(authorization_url);
}
