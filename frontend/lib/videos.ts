import { API_URL, ApiError, apiFetch, messageFrom } from "@/lib/api";

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
 * Upload with real byte progress. `fetch` cannot report upload progress, so this
 * uses XMLHttpRequest; cookies are sent with `withCredentials`.
 */
export function uploadProjectVideo(
  projectId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<Video> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/projects/${projectId}/videos`);
    xhr.withCredentials = true;
    xhr.responseType = "json";

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as Video);
      } else {
        reject(new ApiError(xhr.status, messageFrom(xhr.response, xhr.status)));
      }
    };
    xhr.onerror = () =>
      reject(new ApiError(0, "Could not reach the server. Check your connection and try again."));
    xhr.onabort = () => reject(new ApiError(0, "Upload cancelled."));

    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}
