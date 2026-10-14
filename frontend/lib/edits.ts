import { API_URL, apiFetch, postJson } from "@/lib/api";
import { stageRanks } from "@/lib/status-sync";

export type EditStatus = "queued" | "rendering" | "validating" | "ready" | "failed";
export type Layout = "center_crop" | "blur_background" | "fit" | "smart_reframe" | "manual_crop";
export type CaptionStyle = "clean" | "bold" | "creator";
export type CaptionPosition = "top" | "center" | "bottom";

/** The only options the API accepts (it rejects anything else). */
export type EditRequest = {
  aspect_ratio: "9:16";
  layout: Layout;
  captions_enabled: boolean;
  caption_style?: CaptionStyle;
  caption_position?: CaptionPosition;
  /** smart_reframe only: a completed analysis of this clip. */
  reframe_analysis_id?: string;
  /** manual_crop only: the focal point, fractions of the frame (0..1). */
  focus_x?: number;
  focus_y?: number;
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
  reframe_analysis_id: string | null;
  focus_x: number | null;
  focus_y: number | null;
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

/** What the layout picker offers; manual crop is chosen inside the Smart reframe panel. */
export type PickableLayout = "center_crop" | "blur_background" | "fit" | "smart_reframe";

export const LAYOUT_OPTIONS: Array<{ value: PickableLayout; label: string; hint: string }> = [
  { value: "smart_reframe", label: "Smart reframe", hint: "Follows faces with a smooth vertical crop" },
  { value: "center_crop", label: "Center crop", hint: "Fills the vertical screen, edges cropped" },
  { value: "blur_background", label: "Blur background", hint: "Full original frame over a blurred fill" },
  { value: "fit", label: "Fit", hint: "Full original frame on a dark background" },
];

const LAYOUT_LABELS: Record<Layout, string> = {
  smart_reframe: "Smart reframe",
  manual_crop: "Manual crop",
  center_crop: "Center crop",
  blur_background: "Blur background",
  fit: "Fit",
};

export const STYLE_OPTIONS: Array<{ value: CaptionStyle; label: string; hint: string }> = [
  { value: "clean", label: "Clean", hint: "Regular white, thin outline" },
  { value: "bold", label: "Bold", hint: "Large heavy white, thick outline" },
  { value: "creator", label: "Creator", hint: "Bold yellow on a dark box" },
];

export const POSITION_OPTIONS: Array<{ value: CaptionPosition; label: string }> = [
  { value: "top", label: "Top" },
  { value: "center", label: "Center" },
  { value: "bottom", label: "Bottom" },
];

export const layoutLabel = (layout: Layout) => LAYOUT_LABELS[layout] ?? layout;
export const positionLabel = (position: CaptionPosition) =>
  POSITION_OPTIONS.find((o) => o.value === position)?.label ?? position;
export const styleLabel = (style: CaptionStyle) =>
  STYLE_OPTIONS.find((o) => o.value === style)?.label ?? style;

export const ACTIVE_EDIT_STATUSES: EditStatus[] = ["queued", "rendering", "validating"];
export const isEditActive = (status: EditStatus) => ACTIVE_EDIT_STATUSES.includes(status);
/** Status order within one render attempt (see lib/status-sync.ts). */
export const EDIT_STAGES = stageRanks(ACTIVE_EDIT_STATUSES, ["ready", "failed"]);

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

const round3 = (value: number | null | undefined) => (value == null ? null : Math.round(value * 1000) / 1000);

/** Whether an existing edit was made with exactly these settings, normalized like the
 * server's fingerprint (focal points to 0.1 %). */
export function sameSettings(edit: ClipEdit, request: EditRequest) {
  return (
    edit.layout === request.layout &&
    edit.captions_enabled === request.captions_enabled &&
    (!request.captions_enabled ||
      (edit.caption_style === request.caption_style && edit.caption_position === request.caption_position)) &&
    (request.layout !== "smart_reframe" || edit.reframe_analysis_id === request.reframe_analysis_id) &&
    (request.layout !== "manual_crop" ||
      (round3(edit.focus_x) === round3(request.focus_x) && round3(edit.focus_y) === round3(request.focus_y)))
  );
}

/** "Bold captions · Bottom" or "No captions". */
export function captionSummary(edit: Pick<ClipEdit, "captions_enabled" | "caption_style" | "caption_position">) {
  return edit.captions_enabled && edit.caption_style && edit.caption_position
    ? `${styleLabel(edit.caption_style)} captions · ${positionLabel(edit.caption_position)}`
    : "No captions";
}

/** Creator-facing explanation of a failed render; infrastructure details stay server-side. */
export function friendlyEditError(edit: Pick<ClipEdit, "error_code">): string {
  switch (edit.error_code) {
    case "ffmpeg_missing":
    case "captions_unavailable":
    case "caption_font_unavailable":
      return "The video renderer isn't available right now. Try again in a little while.";
    case "transcript_unavailable":
      return "Captions need a completed transcript for this video.";
    case "clip_missing":
    case "clip_not_ready":
    case "source_missing":
    case "source_unreadable":
      return "The source clip couldn't be read. Regenerate the clip, then try again.";
    case "render_timeout":
    case "time_limit":
      return "Rendering took too long. Try again.";
    case "storage_failure":
    case "artifact_missing":
      return "The finished short couldn't be saved. Try again.";
    case "reframe_unavailable":
    case "invalid_path":
      return "The smart framing for this clip is no longer usable. Analyze the framing again, or set a focal point.";
    case "queue_unavailable":
      return "The rendering queue is busy or offline. Try again in a moment.";
    default:
      return "Something went wrong while rendering. Try again.";
  }
}

export const editorHref = (projectId: string, clipId: string) => `/projects/${projectId}/clips/${clipId}`;

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
