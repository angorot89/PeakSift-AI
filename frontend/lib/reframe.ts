import { ApiError, apiFetch, postJson } from "@/lib/api";
import { stageRanks } from "@/lib/status-sync";

export type ReframeStatus = "queued" | "sampling" | "detecting" | "tracking" | "planning" | "completed" | "failed";
export type ConfidenceLevel = "high" | "mixed" | "fallback";

/** A smart-reframing analysis as the API reports it (no task ids, paths or model details). */
export type ReframeAnalysis = {
  id: string;
  clip_id: string;
  status: ReframeStatus;
  progress_percent: number;
  attempt: number;
  is_stale: boolean;
  provider: string;
  algorithm_version: string;
  sample_fps: number;
  target_aspect_ratio: string;
  source_width: number | null;
  source_height: number | null;
  overall_confidence: number | null;
  confidence_level: ConfidenceLevel | null;
  frames_sampled: number | null;
  detections_count: number | null;
  tracks_count: number | null;
  subject_switches: number | null;
  fallback_fraction: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

/** One crop-path point: clip-local seconds, fractions of the display-oriented source frame. */
export type CropKeyframe = {
  timestamp: number;
  center_x: number;
  center_y: number;
  crop_width: number;
  crop_height: number;
  confidence: number;
  mode: "tracked" | "group" | "fallback";
};

export type CropPath = {
  analysis_id: string;
  source_width: number;
  source_height: number;
  target_aspect_ratio: string;
  keyframes: CropKeyframe[];
};

const ACTIVE: ReframeStatus[] = ["queued", "sampling", "detecting", "tracking", "planning"];
export const isAnalysisActive = (status: ReframeStatus) => ACTIVE.includes(status);
/** Status order within one analysis attempt (see lib/status-sync.ts). */
export const ANALYSIS_STAGES = stageRanks(ACTIVE, ["completed", "failed"]);

const base = (projectId: string, videoId: string, clipId: string) =>
  `/projects/${projectId}/videos/${videoId}/clips/${clipId}/reframe`;

/** The analysis for the server's current configuration, or null when there is none yet. */
export async function getCurrentAnalysis(projectId: string, videoId: string, clipId: string) {
  try {
    return await apiFetch<ReframeAnalysis>(`${base(projectId, videoId, clipId)}/current`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export const startAnalysis = (projectId: string, videoId: string, clipId: string) =>
  postJson<ReframeAnalysis>(base(projectId, videoId, clipId), undefined);

export const getAnalysis = (projectId: string, videoId: string, clipId: string, id: string) =>
  apiFetch<ReframeAnalysis>(`${base(projectId, videoId, clipId)}/${id}`);

export const getCropPath = (projectId: string, videoId: string, clipId: string, id: string) =>
  apiFetch<CropPath>(`${base(projectId, videoId, clipId)}/${id}/path`);

export const retryAnalysis = (projectId: string, videoId: string, clipId: string, id: string) =>
  postJson<ReframeAnalysis>(`${base(projectId, videoId, clipId)}/${id}/retry`, undefined);

/** Honest stage copy, without computer-vision jargon. */
export function analysisStageLabel(analysis: ReframeAnalysis): string {
  switch (analysis.status) {
    case "queued":
      return "Waiting for a worker";
    case "sampling":
      return "Reading frames";
    case "detecting":
      return "Finding faces";
    case "tracking":
      return "Following the subject";
    case "planning":
      return "Planning the camera path";
    case "completed":
      return "Smart framing ready";
    case "failed":
      return "Framing analysis failed";
  }
}

/**
 * Plain-language confidence (documented thresholds in the backend), never a fake accuracy:
 * high = a subject was followed for most of the clip; mixed = tracked in parts with centre
 * fallback elsewhere; fallback = little usable subject, mostly centre framing.
 */
export function confidenceCopy(level: ConfidenceLevel | null): { label: string; hint: string } {
  switch (level) {
    case "high":
      return { label: "Strong tracking", hint: "A face was followed for most of the clip." };
    case "mixed":
      return { label: "Some center fallback", hint: "Followed in parts; centered where no face was clear." };
    default:
      return { label: "Manual framing recommended", hint: "No clear face to follow — the crop stays centered." };
  }
}

/** Plain-language failure copy; infrastructure detail stays server-side. */
export function analysisErrorCopy(analysis: ReframeAnalysis): string {
  switch (analysis.error_code) {
    case "detector_unavailable":
    case "ffmpeg_missing":
    case "ffprobe_missing":
      return "Smart framing isn't available on this server right now.";
    case "detector_failed":
      // A broken detector is never reported as "no faces": the analysis failed.
      return "The face detector stopped while analyzing this clip. Try again, or set a focal point.";
    case "clip_missing":
    case "source_missing":
    case "clip_not_ready":
    case "source_unreadable":
    case "sampling_failed":
      return "The clip couldn't be read for analysis. Regenerate the clip, then try again.";
    case "sampling_timeout":
    case "time_limit":
      return "The analysis took too long. Try again.";
    case "queue_unavailable":
      return "The analysis queue is busy or offline. Try again in a moment.";
    default:
      return "We couldn't analyze the framing of this clip. Try again, or set the framing manually.";
  }
}

/** The renderer's semantics: linear interpolation between keyframes, held at both ends. */
export function cropCenterAt(keyframes: CropKeyframe[], t: number): { x: number; y: number } {
  if (keyframes.length === 0) return { x: 0.5, y: 0.5 };
  const first = keyframes[0];
  const last = keyframes[keyframes.length - 1];
  if (t <= first.timestamp) return { x: first.center_x, y: first.center_y };
  if (t >= last.timestamp) return { x: last.center_x, y: last.center_y };
  let lo = 0;
  let hi = keyframes.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (keyframes[mid].timestamp <= t) lo = mid;
    else hi = mid;
  }
  const a = keyframes[lo];
  const b = keyframes[hi];
  const f = b.timestamp > a.timestamp ? (t - a.timestamp) / (b.timestamp - a.timestamp) : 0;
  return { x: a.center_x + (b.center_x - a.center_x) * f, y: a.center_y + (b.center_y - a.center_y) * f };
}

/** The fixed 9:16 crop for a source (fractions), matching the backend's CropGeometry. */
export function cropGeometry(width: number, height: number) {
  const ratio = 9 / 16;
  const source = width / height;
  if (Math.abs(source - ratio) / ratio < 1e-3) return { cropWidth: 1, cropHeight: 1, axis: null as null };
  if (source > ratio) return { cropWidth: Math.min(1, (height * ratio) / width), cropHeight: 1, axis: "x" as const };
  return { cropWidth: 1, cropHeight: Math.min(1, width / ratio / height), axis: "y" as const };
}

/** Clamp a focal point to a crop centre that keeps the crop inside the source. */
export function clampedCenter(width: number, height: number, focusX: number, focusY: number) {
  const g = cropGeometry(width, height);
  return {
    x: Math.min(1 - g.cropWidth / 2, Math.max(g.cropWidth / 2, focusX)),
    y: Math.min(1 - g.cropHeight / 2, Math.max(g.cropHeight / 2, focusY)),
  };
}
