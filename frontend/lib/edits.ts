import { API_URL, apiFetch, postJson } from "@/lib/api";

export type EditStatus = "queued" | "rendering" | "validating" | "ready" | "failed";
export type Layout = "center_crop" | "blur_background" | "fit";
export type CaptionStyle = "clean" | "bold" | "creator";
export type CaptionPosition = "top" | "center" | "bottom";

/** The only options the API accepts (it rejects anything else). */
export type EditRequest = {
  aspect_ratio: "9:16";
  layout: Layout;
  captions_enabled: boolean;
  caption_style?: CaptionStyle;
  caption_position?: CaptionPosition;
};

export type ClipEdit = {
  id: string;
  clip_id: string;
  video_id: string;
  status: EditStatus;
  progress_percent: number;
  attempt: number;
  is_stale: boolean;
  configuration: Record<string, unknown>;
  aspect_ratio: string;
  layout: Layout;
  captions_enabled: boolean;
  caption_style: CaptionStyle | null;
  caption_position: CaptionPosition | null;
  output_width: number;
  output_height: number;
  render_profile: string;
  caption_cue_count: number | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  file_size: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type ClipEditPage = { total: number; offset: number; limit: number; edits: ClipEdit[] };

export const LAYOUT_OPTIONS: Array<{ value: Layout; label: string; hint: string }> = [
  { value: "blur_background", label: "Blur background", hint: "Whole frame over a blurred fill" },
  { value: "center_crop", label: "Center crop", hint: "Fill the frame, crop the sides" },
  { value: "fit", label: "Fit", hint: "Whole frame on a dark background" },
];

export const STYLE_OPTIONS: Array<{ value: CaptionStyle; label: string; hint: string }> = [
  { value: "bold", label: "Bold", hint: "Large white text, heavy outline" },
  { value: "clean", label: "Clean", hint: "Smaller white text, thin outline" },
  { value: "creator", label: "Creator", hint: "Yellow text on a dark box" },
];

export const POSITION_OPTIONS: Array<{ value: CaptionPosition; label: string }> = [
  { value: "top", label: "Top" },
  { value: "center", label: "Center" },
  { value: "bottom", label: "Bottom" },
];

export const layoutLabel = (layout: Layout) =>
  LAYOUT_OPTIONS.find((o) => o.value === layout)?.label ?? layout;
export const styleLabel = (style: CaptionStyle) =>
  STYLE_OPTIONS.find((o) => o.value === style)?.label ?? style;

export const ACTIVE_EDIT_STATUSES: EditStatus[] = ["queued", "rendering", "validating"];
export const isEditActive = (status: EditStatus) => ACTIVE_EDIT_STATUSES.includes(status);

/** Honest stage copy; the percentage is the backend's stage progress, never animated. */
export function editStageLabel(edit: ClipEdit): string {
  switch (edit.status) {
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

/** "Blur background · Bold captions, bottom" — enough to tell variants apart. */
export function describeEdit(edit: Pick<ClipEdit, "layout" | "captions_enabled" | "caption_style" | "caption_position">) {
  const captions =
    edit.captions_enabled && edit.caption_style && edit.caption_position
      ? `${styleLabel(edit.caption_style)} captions, ${edit.caption_position}`
      : "No captions";
  return `${layoutLabel(edit.layout)} · ${captions}`;
}

const base = (projectId: string, videoId: string, clipId: string) =>
  `/projects/${projectId}/videos/${videoId}/clips/${clipId}/edits`;

export const createEdit = (projectId: string, videoId: string, clipId: string, body: EditRequest) =>
  postJson<ClipEdit>(base(projectId, videoId, clipId), body);

export const listEdits = (projectId: string, videoId: string, clipId: string) =>
  apiFetch<ClipEditPage>(`${base(projectId, videoId, clipId)}?limit=50`);

export const getEdit = (projectId: string, videoId: string, clipId: string, editId: string) =>
  apiFetch<ClipEdit>(`${base(projectId, videoId, clipId)}/${editId}`);

export const retryEdit = (projectId: string, videoId: string, clipId: string, editId: string) =>
  postJson<ClipEdit>(`${base(projectId, videoId, clipId)}/${editId}/retry`, undefined);

/** Owner-only, Range-capable stream of the edited short (session cookie, same-site). */
export const editContentUrl = (editId: string) => `${API_URL}/edits/${editId}/content`;
export const editDownloadUrl = (editId: string) => `${API_URL}/edits/${editId}/download`;
