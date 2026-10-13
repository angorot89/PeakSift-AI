import { ApiError, apiFetch, postJson } from "@/lib/api";

export type ClipStatus = "queued" | "rendering" | "validating" | "ready" | "failed";

/** A rendered clip as the API reports it (no storage keys, paths or task ids). */
export type GeneratedClip = {
  id: string;
  candidate_id: string;
  run_id: string;
  video_id: string;
  title: string;
  status: ClipStatus;
  progress_percent: number;
  attempt: number;
  is_stale: boolean;
  start_time: number;
  end_time: number;
  duration_seconds: number;
  render_profile: string;
  content_type: string;
  file_size: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type ClipPage = { total: number; offset: number; limit: number; clips: GeneratedClip[] };

export const ACTIVE_CLIP_STATUSES: ClipStatus[] = ["queued", "rendering", "validating"];
export const isClipActive = (status: ClipStatus) => ACTIVE_CLIP_STATUSES.includes(status);

/** Honest stage copy; the percentage is the backend's stage progress, never animated. */
export function clipStageLabel(clip: GeneratedClip): string {
  switch (clip.status) {
    case "queued":
      return "Queued — waiting for a worker";
    case "rendering":
      return "Rendering…";
    case "validating":
      return "Validating…";
    case "ready":
      return "Ready";
    case "failed":
      return "Render failed";
  }
}

const candidateBase = (projectId: string, videoId: string, runId: string, candidateId: string) =>
  `/projects/${projectId}/videos/${videoId}/clip-detection/${runId}/candidates/${candidateId}/clip`;

export const generateClip = (projectId: string, videoId: string, runId: string, candidateId: string) =>
  postJson<GeneratedClip>(candidateBase(projectId, videoId, runId, candidateId), undefined);

export const retryClip = (projectId: string, videoId: string, runId: string, candidateId: string) =>
  postJson<GeneratedClip>(`${candidateBase(projectId, videoId, runId, candidateId)}/retry`, undefined);

/** The candidate's clip, or null when none has been generated (404). */
export async function getClip(
  projectId: string,
  videoId: string,
  runId: string,
  candidateId: string,
): Promise<GeneratedClip | null> {
  try {
    return await apiFetch<GeneratedClip>(candidateBase(projectId, videoId, runId, candidateId));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function listVideoClips(projectId: string, videoId: string, limit = 100, offset = 0) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return apiFetch<ClipPage>(`/projects/${projectId}/videos/${videoId}/clips?${params}`);
}
