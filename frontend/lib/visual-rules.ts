/** Types and pure rules for visual assets (no imports: unit-tested with node --test). */

export type VisualKind = "image" | "video";

/** A project's uploaded image or B-roll video (no storage keys, hashes or paths). */
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
  created_at: string;
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

/** The same rule as the API's search: every word must appear in the name (case-insensitive). */
export function filterVisuals<T extends Pick<VisualAsset, "kind" | "display_name">>(
  assets: T[],
  filter: VisualFilter,
  query: string,
): T[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return assets.filter(
    (asset) =>
      (filter === "all" || asset.kind === filter) &&
      words.every((word) => asset.display_name.toLowerCase().includes(word)),
  );
}
