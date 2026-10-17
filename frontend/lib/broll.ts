import { apiFetch, postJson } from "@/lib/api";
import type { VisualLayout } from "@/lib/visual-elements";

export type BrollMethod = "local_ai" | "keyword" | "keyword_fallback";
export type BrollStatus = "queued" | "analyzing" | "validating" | "completed" | "failed";
export type SuggestionStatus = "suggested" | "accepted" | "dismissed";

/** One run of B-roll suggestions for a clip (never prompts, scores or provider internals). */
export type BrollAnalysis = {
  id: string;
  clip_id: string;
  status: BrollStatus;
  progress_percent: number;
  attempt: number;
  is_stale: boolean;
  generation: number;
  method: BrollMethod;
  suggestion_count: number | null;
  rejected_count: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

/** What visual would help, and when (clip-local seconds). */
export type BrollSuggestion = {
  id: string;
  analysis_id: string;
  start: number;
  end: number;
  query: string;
  reason: string;
  status: SuggestionStatus;
};

export type BrollState = { analysis: BrollAnalysis | null; suggestions: BrollSuggestion[] };

const base = (projectId: string, videoId: string, clipId: string) =>
  `/projects/${projectId}/videos/${videoId}/clips/${clipId}/broll`;

export const getBrollState = (p: string, v: string, c: string) => apiFetch<BrollState>(base(p, v, c));
export const startBroll = (p: string, v: string, c: string, regenerate = false) =>
  postJson<BrollAnalysis>(`${base(p, v, c)}/analyses`, { regenerate });
export const retryBroll = (p: string, v: string, c: string, analysisId: string) =>
  postJson<BrollAnalysis>(`${base(p, v, c)}/analyses/${analysisId}/retry`, {});
export const setSuggestionStatus = (p: string, v: string, c: string, id: string, status: SuggestionStatus) =>
  apiFetch<BrollSuggestion>(`${base(p, v, c)}/suggestions/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });

export const getVisualLayout = () => apiFetch<VisualLayout>("/visual-layout");

export const BROLL_ACTIVE: BrollStatus[] = ["queued", "analyzing", "validating"];

/** A plain-language stage for the analysis (never a fake percentage). */
export function brollStage(analysis: BrollAnalysis): string {
  if (analysis.status === "queued") return "Waiting to start…";
  if (analysis.status === "analyzing") return "Reading the transcript…";
  if (analysis.status === "validating") return "Checking the suggestions…";
  if (analysis.status === "failed") return "Suggestions could not be made";
  return analysis.suggestion_count ? `${analysis.suggestion_count} suggestion${analysis.suggestion_count === 1 ? "" : "s"}` : "No visual moments found";
}

/** Where the suggestions came from, said honestly. */
export function methodNote(method: BrollMethod): string | null {
  if (method === "keyword_fallback") return "The local AI was unavailable, so these are based on names mentioned in the clip.";
  if (method === "keyword") return "Based on names mentioned in the clip.";
  return null;
}
