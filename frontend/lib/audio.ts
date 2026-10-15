import { API_URL, ApiError, apiFetch, messageFrom } from "@/lib/api";

export type AudioKind = "music" | "sfx";

/** A project's uploaded music track or sound effect (no storage keys, hashes or paths). */
export type AudioAsset = {
  id: string;
  project_id: string;
  kind: AudioKind;
  display_name: string;
  content_type: string;
  file_size: number;
  duration_seconds: number;
  sample_rate: number;
  channels: number;
  codec: string;
  container: string;
  created_at: string;
};

/** Peak amplitude per bucket, 0-100 % of full scale, evenly spread over the duration. */
export type AudioWaveform = { asset_id: string; duration_seconds: number; buckets: number; peaks: number[] };

export type AudioUploadLimits = {
  max_bytes: number;
  music_max_duration_seconds: number;
  sfx_max_duration_seconds: number;
  accepted_extensions: string[];
};

const base = (projectId: string) => `/projects/${projectId}/audio-assets`;

export const listAudio = (projectId: string) => apiFetch<AudioAsset[]>(base(projectId));

export const getWaveform = (projectId: string, assetId: string) =>
  apiFetch<AudioWaveform>(`${base(projectId)}/${assetId}/waveform`);

export const getAudioUploadLimits = () => apiFetch<AudioUploadLimits>("/audio-upload-limits");

/** Owner-only, Range-capable stream of an uploaded sound (session cookie, same-site). */
export const audioContentUrl = (projectId: string, assetId: string) => `${API_URL}${base(projectId)}/${assetId}/content`;

export const AUDIO_ACCEPT = ".mp3,.wav,.m4a,.aac,.ogg,.opus,audio/mpeg,audio/wav,audio/mp4,audio/aac,audio/ogg";

/** Upload with byte progress (XMLHttpRequest; cookies via `withCredentials`). The same file
 * uploaded again for the same purpose returns the existing asset. */
export function uploadAudio(
  projectId: string,
  file: File,
  kind: AudioKind,
  onProgress?: (percent: number) => void,
): Promise<AudioAsset> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}${base(projectId)}`);
    xhr.withCredentials = true;
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as AudioAsset);
      else reject(new ApiError(xhr.status, messageFrom(xhr.response, xhr.status)));
    };
    xhr.onerror = () => reject(new ApiError(0, "Could not reach the server. Check your connection and try again."));
    xhr.onabort = () => reject(new ApiError(0, "Upload cancelled."));
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("kind", kind);
    xhr.send(form);
  });
}

/** "2:05" or "0:03.4" for short effects. */
export function formatAudioDuration(seconds: number) {
  if (seconds < 10) return `0:${seconds.toFixed(1).padStart(4, "0")}`;
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
