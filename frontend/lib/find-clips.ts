import { apiFetch } from "@/lib/api";
import type { ClipCandidate } from "@/lib/clip-detection";

export type FoundLine = { start: number; end: number; text: string };

/** A span of the creator's own transcript where the request was heard. */
export type FoundClip = {
  start: number;
  end: number;
  duration: number;
  excerpt: string;
  lines: FoundLine[];
  matched: string[];
  related: string[];
  /** 0–100: the share of the request heard here. A search match, not a rating. */
  score: number;
  /** Set when this exact span is already one of the video's moments. */
  candidate_id: string | null;
};

export type FindClipsResponse = {
  query: string;
  terms: string[];
  related: string[];
  results: FoundClip[];
};

const base = (projectId: string, videoId: string) => `/projects/${projectId}/videos/${videoId}/find-clips`;

export const findClips = (projectId: string, videoId: string, query: string) =>
  apiFetch<FindClipsResponse>(`${base(projectId, videoId)}?q=${encodeURIComponent(query)}`);

/** Keep a found span as a saved moment (idempotent). */
export const keepFoundClip = (projectId: string, videoId: string, query: string, found: Pick<FoundClip, "start" | "end">) =>
  apiFetch<ClipCandidate>(`${base(projectId, videoId)}/keep`, {
    method: "POST",
    body: JSON.stringify({ query, start: found.start, end: found.end }),
  });
