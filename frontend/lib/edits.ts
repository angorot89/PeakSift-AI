import { visualsFromConfiguration, visualsKey, visualsSummary, type VisualElementRequest } from "@/lib/visual-elements";
import { API_URL, apiFetch, postJson } from "@/lib/api";
import { audioFromConfiguration, audioSummary, normalizeAudio, sameAudio, type AudioRequest } from "@/lib/audio-mix";
import type { CaptionTiming, DynamicPreset, HookPosition, HookStyle } from "@/lib/captions";
import { stageRanks } from "@/lib/status-sync";

export type EditStatus = "queued" | "rendering" | "validating" | "ready" | "failed";
export type Layout = "center_crop" | "blur_background" | "fit" | "smart_reframe" | "manual_crop";
/** Clean / Bold / Creator: V0.6 phrase captions (caption_v1, still rendered for existing
 * versions); Focus / Punch / Minimal / Boxed: dynamic word-aware captions (caption_v2). */
export type CaptionStyle = "clean" | "bold" | "creator" | DynamicPreset;
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
  /** Dynamic captions: word-synced (needs a completed word timing track) or phrase timed. */
  caption_timing?: CaptionTiming;
  caption_track_id?: string;
  /** The optional opening hook (plain text, escaped by the server). */
  hook_enabled?: boolean;
  hook_text?: string;
  hook_style?: HookStyle;
  hook_position?: HookPosition;
  hook_duration_seconds?: number;
  /** Optional audio finishing (music, sound effects, levels, normalization). Omitted keeps
   * the clip's own audio exactly as before. */
  audio?: AudioRequest;
  /** Optional B-roll cutaways, picture-in-picture and overlays from the project's visuals. */
  visuals?: { elements: VisualElementRequest[] };
  /** Optional brand identity (logo, caption emphasis, hook accent, end card), validated by the
   * server; copied into the version so later brand changes never alter it. */
  brand?: Record<string, unknown>;
  /** Display only: the template these settings started from. */
  origin_template_id?: string;
};

/** Where a version's settings came from (display only; the render reads the snapshot). */
export type EditOrigin = {
  template?: { id: string; name: string; version: number };
  brand?: { name: string };
  auto_edit_plan_id?: string;
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
  origin?: EditOrigin | null;
  aspect_ratio: string;
  layout: Layout;
  captions_enabled: boolean;
  caption_style: CaptionStyle | null;
  caption_position: CaptionPosition | null;
  caption_renderer: "caption_v1" | "caption_v2" | null;
  caption_timing: CaptionTiming | null;
  caption_track_id: string | null;
  hook_enabled: boolean;
  hook_text: string | null;
  hook_style: HookStyle | null;
  hook_position: HookPosition | null;
  hook_duration_seconds: number | null;
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

const DYNAMIC_LABELS: Record<DynamicPreset, string> = {
  focus: "Focus",
  punch: "Punch",
  minimal: "Minimal",
  boxed: "Boxed",
};

export const POSITION_OPTIONS: Array<{ value: CaptionPosition; label: string }> = [
  { value: "top", label: "Top" },
  { value: "center", label: "Center" },
  { value: "bottom", label: "Bottom" },
];

export const layoutLabel = (layout: Layout) => LAYOUT_LABELS[layout] ?? layout;
export const positionLabel = (position: CaptionPosition) =>
  POSITION_OPTIONS.find((o) => o.value === position)?.label ?? position;
export const styleLabel = (style: CaptionStyle) =>
  DYNAMIC_LABELS[style as DynamicPreset] ?? STYLE_OPTIONS.find((o) => o.value === style)?.label ?? style;

export const ACTIVE_EDIT_STATUSES: EditStatus[] = ["queued", "rendering", "validating"];
export const isEditActive = (status: EditStatus) => ACTIVE_EDIT_STATUSES.includes(status);
/** Status order within one render attempt (see lib/status-sync.ts). */
export const EDIT_STAGES = stageRanks(ACTIVE_EDIT_STATUSES, ["ready", "failed"]);

/** Honest stage copy; the percentage is the backend's stage progress, never animated. */
export function editStageLabel(edit: ClipEdit): string {
  switch (edit.status) {
    case "queued":
      return "Waiting to start";
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

type Described = Pick<
  ClipEdit,
  "layout" | "captions_enabled" | "caption_style" | "caption_position" | "caption_timing" | "hook_enabled"
> &
  Partial<Pick<ClipEdit, "configuration">>;

/** "Smart reframe · Focus captions · Bottom · Hook · Music" — enough to tell variants apart. */
export function describeEdit(edit: Described) {
  const audio = audioSummary(audioFromConfiguration(edit.configuration));
  const visuals = visualsSummary(visualsFromConfiguration(edit.configuration).length);
  return `${layoutLabel(edit.layout)} · ${captionSummary(edit)}${audio ? ` · ${audio}` : ""}${visuals ? ` · ${visuals}` : ""}`;
}

const round3 = (value: number | null | undefined) => (value == null ? null : Math.round(value * 1000) / 1000);
const round1 = (value: number | null | undefined) => (value == null ? null : Math.round(value * 10) / 10);
/** The server's hook text normalization: whitespace (and line breaks) collapse. */
export const normalizeHookText = (text: string) => text.split(/\s+/).filter(Boolean).join(" ");

/** Whether an existing edit was made with exactly these settings, normalized like the
 * server's fingerprint (focal points to 0.1 %). */
/** The parts of a brand section that change the picture (the server drops unreadable colours). */
function brandKey(value: unknown): string {
  const brand = value && typeof value === "object" ? (value as Record<string, unknown>) : null;
  if (!brand) return "";
  return JSON.stringify([brand.name, brand.logo ?? null, brand.end_card ?? null]);
}

export function sameSettings(edit: ClipEdit, request: EditRequest) {
  return (
    edit.layout === request.layout &&
    edit.captions_enabled === request.captions_enabled &&
    (!request.captions_enabled ||
      (edit.caption_style === request.caption_style && edit.caption_position === request.caption_position)) &&
    (request.layout !== "smart_reframe" || edit.reframe_analysis_id === request.reframe_analysis_id) &&
    (request.layout !== "manual_crop" ||
      (round3(edit.focus_x) === round3(request.focus_x) && round3(edit.focus_y) === round3(request.focus_y))) &&
    (!request.captions_enabled ||
      ((edit.caption_timing ?? undefined) === request.caption_timing &&
        (edit.caption_track_id ?? undefined) === request.caption_track_id)) &&
    edit.hook_enabled === !!request.hook_enabled &&
    (!request.hook_enabled ||
      (edit.hook_text === normalizeHookText(request.hook_text ?? "") &&
        edit.hook_style === request.hook_style &&
        edit.hook_position === request.hook_position &&
        round1(edit.hook_duration_seconds) === round1(request.hook_duration_seconds))) &&
    sameAudio(audioFromConfiguration(edit.configuration), normalizeAudio(request.audio)) &&
    visualsKey(visualsFromConfiguration(edit.configuration)) === visualsKey(request.visuals?.elements) &&
    brandKey(edit.configuration.brand) === brandKey(request.brand)
  );
}

/** "Focus captions · Bottom · Hook", "Punch captions (phrase timed) · Top" or "No captions".
 * Phrase-timed dynamic captions say so: they are never presented as word-synced. */
export function captionSummary(
  edit: Pick<ClipEdit, "captions_enabled" | "caption_style" | "caption_position"> &
    Partial<Pick<ClipEdit, "caption_timing" | "hook_enabled">>,
) {
  const captions =
    edit.captions_enabled && edit.caption_style && edit.caption_position
      ? `${styleLabel(edit.caption_style)} captions${edit.caption_timing === "phrase_fallback" ? " (phrase timed)" : ""} · ${positionLabel(edit.caption_position)}`
      : "No captions";
  return edit.hook_enabled ? `${captions} · Hook` : captions;
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
    case "caption_track_unavailable":
    case "caption_track_invalid":
      return "The word timing for these captions is no longer usable. Generate word sync again, or use phrase timing.";
    case "reframe_unavailable":
    case "invalid_path":
      return "The smart framing for this clip is no longer usable. Analyze the framing again, or set a focal point.";
    case "queue_unavailable":
      return "The rendering queue is busy or offline. Try again in a moment.";
    case "audio_asset_unavailable":
      return "A selected music track or sound effect is no longer available. Choose it again, then render.";
    case "audio_mix_failed":
    case "loudness_failed":
      return "The audio couldn't be mixed. Try again, or try another music file.";
    case "audio_clipped":
      return "The finished audio would clip. Lower the music or effect volume, or turn on normalization.";
    default:
      return "Something went wrong while rendering. Try again.";
  }
}

export const editorHref = (projectId: string, clipId: string) => `/projects/${projectId}/clips/${clipId}`;
/** The start of making a Short from a clip: Auto Edit (recommended) or starting manually. */
export const createHref = (projectId: string, clipId: string) => `/projects/${projectId}/clips/${clipId}/create`;

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
