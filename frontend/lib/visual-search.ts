// Semantic visual search, as the creator sees it: plain states and strength tiers — never
// scores, percentages or model names. Pure helpers (unit-tested); the API calls live in visuals.ts.

/** Whether an asset can be found by what it shows (the server derives it per model). */
export type VisualSearchState = "unavailable" | "not_indexed" | "queued" | "indexing" | "ready" | "failed" | "stale";

export type VisualSearchStatus = {
  state: VisualSearchState;
  /** Videos while indexing: real progress (frames analysed of frames selected). */
  frames_done: number | null;
  frames_total: number | null;
  /** Failed only: a safe, creator-facing reason. */
  message: string | null;
  can_retry: boolean;
};

export type MatchStrength = "strong" | "possible";
export type MatchMethod = "visual" | "metadata" | "visual_and_metadata";

export type VisualMatch = {
  strength: MatchStrength;
  method: MatchMethod;
  /** Videos found by what they show: where the best scene is (seconds). */
  best_frame_time: number | null;
};

export type VisualSearchHit<A> = { asset: A; match: VisualMatch };

export type VisualSearchResults<A> = {
  query: string;
  visual_search_used: boolean;
  assets_preparing: number;
  results: VisualSearchHit<A>[];
};

export const SEARCH_MAX_CHARS = 100;
export const SEARCH_DEBOUNCE_MS = 300;

/** The text actually sent: single spaces, at most 100 characters ("" means no search). */
export function searchText(text: string): string {
  return text.replace(/\s+/g, " ").trim().slice(0, SEARCH_MAX_CHARS).trim();
}

export const STRENGTH_LABEL: Record<MatchStrength, string> = {
  strong: "Strong match",
  possible: "Possible match",
};

/** Why an asset was found, in plain words. */
export function matchReason(match: Pick<VisualMatch, "method">): string {
  switch (match.method) {
    case "visual":
      return "Matched by what it shows";
    case "metadata":
      return "Matched by its name, description or tags";
    default:
      return "Matched by what it shows and its details";
  }
}

/** Not searchable by what it shows yet, but on its way (or waiting for a refresh). */
export function isPreparing(state: VisualSearchState | undefined | null): boolean {
  return state === "not_indexed" || state === "queued" || state === "indexing" || state === "stale";
}

/** A quiet note under the search box, or null when visual search fully took part. */
export function searchNote(results: Pick<VisualSearchResults<unknown>, "visual_search_used" | "assets_preparing"> | null): string | null {
  if (!results) return null;
  const n = results.assets_preparing;
  if (n > 0) {
    return `Visual search is still preparing for ${n} visual${n === 1 ? "" : "s"}. Names, descriptions and tags already work.`;
  }
  if (!results.visual_search_used) return "Searching names, descriptions and tags only right now.";
  return null;
}

/** "Best at 0:08" for a video's matched scene (seconds rounded down to whole seconds). */
export function bestSceneLabel(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  const whole = Math.floor(seconds);
  return `Best at ${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
