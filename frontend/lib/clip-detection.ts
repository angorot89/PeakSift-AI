import { apiFetch, postJson } from "@/lib/api";

export type DetectionStatus =
  | "queued"
  | "preparing_transcript"
  | "analyzing"
  | "validating"
  | "ranking"
  | "completed"
  | "failed";

export type ProviderOption = {
  name: string;
  label: string;
  models: string[];
  default_model: string | null;
  configured: boolean;
  available: boolean | null;
  detail: string | null;
};

export type DetectionRun = {
  id: string;
  video_id: string;
  transcription_id: string;
  provider: string;
  model: string;
  status: DetectionStatus;
  progress_percent: number;
  windows_total: number | null;
  windows_done: number;
  attempt: number;
  candidate_count: number;
  is_stale: boolean;
  transcript_current: boolean;
  config: Record<string, number>;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type DetectionRunPage = {
  total: number;
  offset: number;
  limit: number;
  runs: DetectionRun[];
};

export type CandidateDecision = "undecided" | "saved" | "dismissed";

export type CandidateScores = {
  hook: number;
  entertainment: number;
  clarity: number;
  payoff: number;
  completeness: number;
};

export type ClipCandidate = {
  id: string;
  run_id: string;
  video_id: string;
  rank: number;
  start: number;
  end: number;
  duration: number;
  title: string;
  hook: string;
  rationale: string;
  category: string;
  transcript_excerpt: string;
  overall_score: number;
  scores: CandidateScores;
  decision: CandidateDecision;
  decided_at: string | null;
  created_at: string;
};

export type CandidatePage = {
  run_id: string;
  total: number;
  offset: number;
  limit: number;
  candidates: ClipCandidate[];
};

export const ACTIVE_DETECTION_STATUSES: DetectionStatus[] = [
  "queued",
  "preparing_transcript",
  "analyzing",
  "validating",
  "ranking",
];
export const isDetectionActive = (status: DetectionStatus) =>
  ACTIVE_DETECTION_STATUSES.includes(status);

/** Human copy for each stage; progress is shown only when the backend reports a real value. */
export function detectionStageLabel(run: DetectionRun): string {
  switch (run.status) {
    case "queued":
      return "Queued — waiting for a worker";
    case "preparing_transcript":
      return "Preparing transcript";
    case "analyzing":
      return run.windows_total
        ? `Analyzing transcript — window ${Math.min(run.windows_done + 1, run.windows_total)} of ${run.windows_total}`
        : "Analyzing transcript";
    case "validating":
      return "Validating candidates";
    case "ranking":
      return "Ranking candidates";
    case "completed":
      return "Candidates ready";
    case "failed":
      return "Detection failed";
  }
}

export const CANDIDATE_PAGE_SIZE = 20;

const base = (projectId: string, videoId: string) =>
  `/projects/${projectId}/videos/${videoId}/clip-detection`;

export const listProviders = (diagnose = true) =>
  apiFetch<ProviderOption[]>(`/clip-detection/providers${diagnose ? "?diagnose=true" : ""}`);

export const startDetection = (
  projectId: string,
  videoId: string,
  provider: string,
  model: string | null,
) => postJson<DetectionRun>(base(projectId, videoId), { provider, model });

export function listRuns(projectId: string, videoId: string, limit = 10, offset = 0) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return apiFetch<DetectionRunPage>(`${base(projectId, videoId)}?${params}`);
}

export const getRun = (projectId: string, videoId: string, runId: string) =>
  apiFetch<DetectionRun>(`${base(projectId, videoId)}/${runId}`);

export const retryRun = (projectId: string, videoId: string, runId: string) =>
  postJson<DetectionRun>(`${base(projectId, videoId)}/${runId}/retry`, undefined);

export function listCandidates(
  projectId: string,
  videoId: string,
  runId: string,
  offset = 0,
  limit = CANDIDATE_PAGE_SIZE,
  decision?: CandidateDecision,
) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (decision) params.set("decision", decision);
  return apiFetch<CandidatePage>(`${base(projectId, videoId)}/${runId}/candidates?${params}`);
}

export const decideCandidate = (
  projectId: string,
  videoId: string,
  runId: string,
  candidateId: string,
  action: "save" | "dismiss" | "reset",
) =>
  postJson<ClipCandidate>(
    `${base(projectId, videoId)}/${runId}/candidates/${candidateId}/${action}`,
    undefined,
  );
