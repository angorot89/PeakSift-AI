import { apiFetch } from "@/lib/api";
import type { ShortDetail, ShortsLibrary } from "@/lib/shorts-rules";

export * from "@/lib/shorts-rules";

export const getShorts = () => apiFetch<ShortsLibrary>("/shorts");
export const getShort = (shortId: string) => apiFetch<ShortDetail>(`/shorts/${shortId}`);

/** Hide a Short from the library, or show it again. */
export const setShortHidden = (shortId: string, hidden: boolean) =>
  apiFetch<{ id: string; hidden: boolean }>(`/shorts/${shortId}`, { method: "PATCH", body: JSON.stringify({ hidden }) });
