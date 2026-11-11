import { apiFetch } from "@/lib/api";
import type { ShortDetail, ShortsLibrary } from "@/lib/shorts-rules";

export * from "@/lib/shorts-rules";

export const getShorts = () => apiFetch<ShortsLibrary>("/shorts");
export const getShort = (shortId: string) => apiFetch<ShortDetail>(`/shorts/${shortId}`);
