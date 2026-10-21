import { API_URL, ApiError, apiFetch, messageFrom } from "@/lib/api";
import type { VisualAsset, VisualKind } from "@/lib/visual-rules";
import { searchText, type VisualSearchResults } from "@/lib/visual-search";

export * from "@/lib/visual-rules";
export * from "@/lib/visual-search";

export type VisualUploadLimits = {
  max_bytes: number;
  max_video_duration_seconds: number;
  max_image_pixels: number;
  max_video_pixels: number;
  accepted_extensions: string[];
};

const base = (projectId: string) => `/projects/${projectId}/visual-assets`;

export function listVisuals(projectId: string, filters: { kind?: VisualKind | null; q?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.kind) params.set("kind", filters.kind);
  const q = filters.q?.trim();
  if (q) params.set("q", q.slice(0, 100));
  const query = params.toString();
  return apiFetch<VisualAsset[]>(`${base(projectId)}${query ? `?${query}` : ""}`);
}

/** Search the project's visuals by what they show and by their names, descriptions and tags. */
export function searchVisuals(projectId: string, text: string, options: { kind?: VisualKind | null; limit?: number } = {}) {
  const params = new URLSearchParams({ q: searchText(text) });
  if (options.kind) params.set("kind", options.kind);
  if (options.limit) params.set("limit", String(options.limit));
  return apiFetch<VisualSearchResults<VisualAsset>>(`${base(projectId)}/search?${params.toString()}`);
}

/** Analyse an asset again for visual search (after a failure; no re-upload). */
export const retryVisualSearch = (projectId: string, assetId: string) =>
  apiFetch<VisualAsset>(`${base(projectId)}/${assetId}/visual-search/retry`, { method: "POST" });

export const getVisualUploadLimits = () => apiFetch<VisualUploadLimits>("/visual-upload-limits");

export const deleteVisual = (projectId: string, assetId: string) =>
  apiFetch<{ media_files_removed: number; media_files_pending_cleanup: number }>(`${base(projectId)}/${assetId}`, {
    method: "DELETE",
  });

/** Rename an asset or describe and tag it (omitted fields are kept). */
export const updateVisual = (
  projectId: string,
  assetId: string,
  details: { display_name?: string; description?: string; tags?: string[] },
) => apiFetch<VisualAsset>(`${base(projectId)}/${assetId}`, { method: "PATCH", body: JSON.stringify(details) });

/** Owner-only streams (session cookie, same-site): the stored file and its small preview. */
export const visualContentUrl = (projectId: string, assetId: string) => `${API_URL}${base(projectId)}/${assetId}/content`;
export const visualThumbnailUrl = (projectId: string, assetId: string) =>
  `${API_URL}${base(projectId)}/${assetId}/thumbnail`;

export const VISUAL_ACCEPT =
  ".jpg,.jpeg,.png,.webp,.mp4,.m4v,.mov,.webm,image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm";

/** Upload with byte progress (XMLHttpRequest; cookies via `withCredentials`). Resolves with the
 * asset and whether it already existed in this project (the same file uploaded before). */
export function uploadVisual(
  projectId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<{ asset: VisualAsset; existing: boolean }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}${base(projectId)}`);
    xhr.withCredentials = true;
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve({ asset: xhr.response as VisualAsset, existing: xhr.status === 200 });
      } else reject(new ApiError(xhr.status, messageFrom(xhr.response, xhr.status)));
    };
    xhr.onerror = () => reject(new ApiError(0, "Could not reach the server. Check your connection and try again."));
    xhr.onabort = () => reject(new ApiError(0, "Upload cancelled."));
    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}
