import { ApiError, apiFetch, postJson } from "@/lib/api";

export type TranscriptionStatus =
  | "queued"
  | "extracting_audio"
  | "transcribing"
  | "completed"
  | "failed";

export type Transcription = {
  id: string;
  video_id: string;
  status: TranscriptionStatus;
  provider: string;
  model: string;
  language: string | null;
  language_probability: number | null;
  progress_percent: number;
  segment_count: number;
  is_stale: boolean;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type TranscriptSegment = {
  sequence_index: number;
  start: number;
  end: number;
  text: string;
  speaker: string | null;
};

export type TranscriptPage = {
  transcription_id: string;
  total: number;
  offset: number;
  limit: number;
  segments: TranscriptSegment[];
  full_text: string | null;
};

export const ACTIVE_STATUSES: TranscriptionStatus[] = ["queued", "extracting_audio", "transcribing"];
export const isActive = (status: TranscriptionStatus) => ACTIVE_STATUSES.includes(status);

export const TRANSCRIPT_PAGE_SIZE = 200;

const base = (projectId: string, videoId: string) => `/projects/${projectId}/videos/${videoId}`;

/** The current transcription, or null when none has been started (404). */
export async function getTranscription(projectId: string, videoId: string): Promise<Transcription | null> {
  try {
    return await apiFetch<Transcription>(`${base(projectId, videoId)}/transcription`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export const startTranscription = (projectId: string, videoId: string) =>
  postJson<Transcription>(`${base(projectId, videoId)}/transcription`, undefined);

export const retryTranscription = (projectId: string, videoId: string) =>
  postJson<Transcription>(`${base(projectId, videoId)}/transcription/retry`, undefined);

export function getTranscriptPage(
  projectId: string,
  videoId: string,
  offset: number,
  limit = TRANSCRIPT_PAGE_SIZE,
  includeText = false,
): Promise<TranscriptPage> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (includeText) params.set("include_text", "true");
  return apiFetch<TranscriptPage>(`${base(projectId, videoId)}/transcript?${params}`);
}
