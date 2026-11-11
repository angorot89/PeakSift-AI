/** Types and pure rules for visual assets (no imports: unit-tested with node --test). */

export type VisualKind = "image" | "video";

/** A project's uploaded image or B-roll video (no storage keys, hashes or paths). */
import type { VisualSearchStatus } from "./visual-search.ts";

export type VisualAsset = {
  id: string;
  project_id: string;
  kind: VisualKind;
  display_name: string;
  content_type: string;
  file_size: number;
  /** Display size: after rotation and pixel aspect ratio. */
  width: number;
  height: number;
  duration_seconds: number | null;
  fps: number | null;
  has_alpha: boolean;
  has_audio: boolean;
  has_thumbnail: boolean;
  /** The creator's words about it (help match B-roll suggestions). */
  description: string;
  tags: string[];
  created_at: string;
  /** Whether it can be found by what it shows (absent from older responses). */
  visual_search?: VisualSearchStatus | null;
  /** V1.8 labels, chosen by the creator (absent from older responses). */
  origin?: string;
  license_note?: string | null;
  market?: string;
  category?: string | null;
  location?: string | null;
};

export type VisualFilter = "all" | VisualKind;

/** "0:08" or "1:05" (B-roll is short; hours are not expected). */
export function formatVisualDuration(seconds: number): string {
  const total = Math.max(0, Math.round(Number.isFinite(seconds) ? seconds : 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** "Portrait", "Landscape" or "Square" (within 5 %), for cards. */
export function orientationLabel(asset: Pick<VisualAsset, "width" | "height">): string {
  const ratio = asset.width / asset.height;
  if (ratio > 1.05) return "Landscape";
  if (ratio < 0.95) return "Portrait";
  return "Square";
}

/** The same rule as the API's search: every word must appear in the name, description or
 * tags (case-insensitive). */
export function filterVisuals<T extends Pick<VisualAsset, "kind" | "display_name"> & Partial<Pick<VisualAsset, "description" | "tags">>>(
  assets: T[],
  filter: VisualFilter,
  query: string,
): T[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return assets.filter((asset) => {
    const text = [asset.display_name, asset.description ?? "", ...(asset.tags ?? [])].join(" ").toLowerCase();
    return (filter === "all" || asset.kind === filter) && words.every((word) => text.includes(word));
  });
}

/** "rocket, space, launch" → ["rocket", "space", "launch"] (the server normalizes further). */
export function parseTagText(text: string): string[] {
  return [...new Set(text.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean))];
}

/** The chooser's filter when it opens: images when replacing an overlay's asset (overlays use
 * images; a video would turn it into picture-in-picture), otherwise everything — a filter
 * chosen earlier is never carried over, so no asset seems to be missing. */
export function chooserFilter(replacingMode: string | null): VisualFilter {
  return replacingMode === "overlay" ? "image" : "all";
}

export function chooserHint(replacingMode: string | null): string | null {
  return replacingMode === "overlay" ? "Overlays use images. Choosing a video turns this visual into picture-in-picture." : null;
}
