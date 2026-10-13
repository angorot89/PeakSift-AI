import { API_URL, ApiError, apiFetch, postJson } from "@/lib/api";

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

/** Owner-only, Range-capable stream for <video> (the session cookie goes along, same-site). */
export const clipContentUrl = (clipId: string) => `${API_URL}/clips/${clipId}/content`;

/** Same bytes as an attachment with a safe server-chosen filename. */
export const clipDownloadUrl = (clipId: string) => `${API_URL}/clips/${clipId}/download`;

/** Creator-facing explanation of a failed clip render; infrastructure details stay server-side. */
export function friendlyClipError(clip: Pick<GeneratedClip, "error_code">): string {
  switch (clip.error_code) {
    case "ffmpeg_missing":
      return "The video renderer isn't available right now. Try again in a little while.";
    case "source_missing":
    case "source_unreadable":
    case "video_not_ready":
      return "The original video couldn't be read.";
    case "invalid_range":
      return "This moment falls outside the video. Run clip detection again.";
    case "render_timeout":
    case "time_limit":
      return "Rendering took too long. Try again.";
    case "storage_failure":
    case "artifact_missing":
      return "The finished clip couldn't be saved. Try again.";
    case "queue_unavailable":
      return "The rendering queue is busy or offline. Try again in a moment.";
    default:
      return "Something went wrong while rendering. Try again.";
  }
}
