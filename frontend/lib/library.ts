/** PeakSift's built-in starter library: openly licensed sound effects, music and stickers
 * (CC0 or MIT), installed on the server. Adding an item imports it into the project as an
 * ordinary audio or visual asset, labelled with where it comes from. */
import { API_URL, apiFetch, postJson } from "@/lib/api";
import type { AudioAsset } from "@/lib/audio";
import type { VisualAsset } from "@/lib/visual-rules";

export type LibraryKind = "sfx" | "music" | "sticker";

export type LibraryItem = {
  id: string;
  kind: LibraryKind;
  title: string;
  category: string;
  tags: string[];
  duration_seconds: number | null;
  licence: string;
  credit: string;
  source_name: string;
  source_url: string;
};

export type LibrarySource = { name: string; url: string; licence: string };
export type Library = { available: boolean; items: LibraryItem[]; sources: LibrarySource[] };
export type LibraryImport =
  | { kind: "audio"; created: boolean; audio_asset: AudioAsset; visual_asset: null }
  | { kind: "visual"; created: boolean; audio_asset: null; visual_asset: VisualAsset };

let cached: Promise<Library> | null = null;

/** The catalogue (loaded once per page; it only changes with a new library release). */
export function getLibrary(): Promise<Library> {
  cached ??= apiFetch<Library>("/library").catch((error) => {
    cached = null;
    throw error;
  });
  return cached;
}

export const libraryContentUrl = (id: string) => `${API_URL}/library/${encodeURIComponent(id)}/content`;

export const addLibraryItem = (projectId: string, id: string) =>
  postJson<LibraryImport>(`/projects/${projectId}/library/${encodeURIComponent(id)}`, undefined);
