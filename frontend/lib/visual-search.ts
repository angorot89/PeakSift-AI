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

/** `local`: in a local market's project, the asset is local to that market. */
export type VisualSearchHit<A> = { asset: A; match: VisualMatch; local?: boolean };

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

/** A short, creator-facing label for an asset's visual-search state (null: nothing to show). */
export function searchStateLabel(status: Pick<VisualSearchStatus, "state" | "frames_done" | "frames_total"> | null | undefined): string | null {
  switch (status?.state) {
    case "ready":
      return "Visual search ready";
    case "failed":
      return "Visual search unavailable";
    case "indexing":
      return status.frames_total
        ? `Preparing visual search (${status.frames_done ?? 0} of ${status.frames_total} frames)`
        : "Preparing visual search";
    case "queued":
    case "not_indexed":
    case "stale":
      return "Preparing visual search";
    default:
      return null; // turned off on this server: name, description and tag search only
  }
}

/** A server message as a sentence ("…in this video" → "…in this video."). */
export function asSentence(text: string): string {
  const trimmed = text.trim();
  return /[.!?…]$/.test(trimmed) ? trimmed : `${trimmed}.`;
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

/** Where a video element of ``elementSeconds`` should start inside the video so the matched scene
 * is in the middle — never before 0, never past the end (no black tail); 0 when unknown. The same
 * rule as the server's (semantic/matching.py asset_offset). */
export function sceneOffset(scene: number | null | undefined, elementSeconds: number, videoSeconds: number | null | undefined): number {
  if (scene == null || videoSeconds == null) return 0;
  if (![scene, elementSeconds, videoSeconds].every(Number.isFinite)) return 0;
  if (elementSeconds <= 0 || videoSeconds <= elementSeconds) return 0;
  const start = Math.min(Math.max(0, scene - elementSeconds / 2), videoSeconds - elementSeconds);
  return Math.floor(start * 100) / 100;
}

/** How a suggestion's asset matched, for the match card ("Matched visually to “bridge joint”"). */
export function matchedTo(method: MatchMethod, query: string): string {
  if (method === "metadata") return "Matched by its name or tags";
  return `Matched visually to “${query}”`;
}

/** "Best at 0:08" for a video's matched scene (seconds rounded down to whole seconds). */
export function bestSceneLabel(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  const whole = Math.floor(seconds);
  return `Best at ${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** Search results in two tiers: strong matches ("Best matches") first, then everything else
 * ("More results"), each in the server's order. Unmatched entries count as "more". */
export function splitByStrength<T extends { match?: Pick<VisualMatch, "strength"> | null }>(hits: T[]): { best: T[]; more: T[] } {
  return {
    best: hits.filter((hit) => hit.match?.strength === "strong"),
    more: hits.filter((hit) => hit.match?.strength !== "strong"),
  };
}

/** In a local market: the strong matches split into local ones and Global ones (each in the
 * server's order); weaker matches stay below both, so a strong Global match is never buried
 * under a weaker local one. Without local hits there is nothing to split. */
export function splitLocal<T extends { local?: boolean; match?: Pick<VisualMatch, "strength"> | null }>(
  hits: T[],
): { local: T[]; global: T[]; more: T[] } | null {
  if (!hits.some((hit) => hit.local)) return null;
  const { best, more } = splitByStrength(hits);
  return { local: best.filter((hit) => hit.local), global: best.filter((hit) => !hit.local), more };
}

/** Whether search by what visuals show can be offered as such (at least one asset is ready). */
export function canSearchByContent(statuses: (Pick<VisualSearchStatus, "state"> | null | undefined)[]): boolean {
  return statuses.some((status) => status?.state === "ready");
}
