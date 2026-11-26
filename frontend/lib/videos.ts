import { API_URL, ApiError, apiFetch, messageFrom } from "@/lib/api";
import type { Project } from "@/lib/projects";

export type VideoStatus = "uploaded" | "processing_metadata" | "ready" | "failed";

export type Video = {
  id: string;
  project_id: string;
  original_filename: string;
  content_type: string;
  file_size: number;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  status: VideoStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export const ACCEPTED_EXTENSIONS = [".mp4", ".mov", ".webm"] as const;
export const ACCEPTED_LABEL = "MP4, MOV or WebM";
/** Value for the file input's `accept` attribute. */
export const ACCEPT_ATTRIBUTE = [
  ...ACCEPTED_EXTENSIONS,
  "video/mp4",
  "video/quicktime",
  "video/webm",
].join(",");

export function hasAcceptedExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export const listProjectVideos = (projectId: string) =>
  apiFetch<Video[]>(`/projects/${projectId}/videos`);

/** Authenticated, owner-only stream of the source bytes (supports Range requests). */
export const videoContentUrl = (videoId: string) => `${API_URL}/videos/${videoId}/content`;

/**
 * POST a form with real byte progress. `fetch` cannot report upload progress, so this
 * uses XMLHttpRequest; cookies are sent with `withCredentials`.
 */
function postForm<T>(path: string, form: FormData, onProgress?: (percent: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}${path}`);
    xhr.withCredentials = true;
    xhr.responseType = "json";

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as T);
      } else {
        reject(new ApiError(xhr.status, messageFrom(xhr.response, xhr.status)));
      }
    };
    xhr.onerror = () =>
      reject(new ApiError(0, "Could not reach the server. Check your connection and try again."));
    xhr.onabort = () => reject(new ApiError(0, "Upload cancelled."));

    xhr.send(form);
  });
}

/** Upload a project's source video. */
export function uploadProjectVideo(
  projectId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<Video> {
  const form = new FormData();
  form.append("file", file, file.name);
  return postForm<Video>(`/projects/${projectId}/videos`, form, onProgress);
}

export type QuickStartResult = {
  project: Project;
  video: Video;
  /** False when the file is not usable video or the job could not be queued. */
  transcription_started: boolean;
};

/**
 * Quick start: one upload becomes a project that transcribes itself and then finds moments.
 * `name` is optional (the server names the project from the file); `market` defaults to the
 * creator's own.
 */
export function quickStart(
  file: File,
  options: { name?: string; market?: string } = {},
  onProgress?: (percent: number) => void,
): Promise<QuickStartResult> {
  const form = new FormData();
  form.append("file", file, file.name);
  if (options.name?.trim()) form.append("name", options.name.trim());
  if (options.market) form.append("market", options.market);
  return postForm<QuickStartResult>("/quick-start", form, onProgress);
}
