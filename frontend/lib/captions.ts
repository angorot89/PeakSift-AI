import { ApiError, apiFetch, postJson } from "@/lib/api";
import { stageRanks } from "@/lib/status-sync";

export type DynamicPreset = "focus" | "punch" | "minimal" | "boxed";
export type HookStyle = "headline" | "boxed" | "minimal";
export type HookPosition = "top" | "center";
export type CaptionTiming = "aligned_word" | "phrase_fallback";

/** The renderer's own numbers (GET /caption-styles): the preview never keeps a copy. */
export type Placement = { alignment: number; margin_v: number; margin_h: number };
export type PresetSpec = {
  name: DynamicPreset;
  label: string;
  size: number;
  bold: boolean;
  uppercase: boolean;
  text: string;
  active: string;
  outline_colour: string;
  outline: number;
  shadow: number;
  box: boolean;
  box_alpha: number;
  fade_ms: number;
  grow_from: number;
  grow_ms: number;
};
export type CaptionStyles = {
  renderer: string;
  emoji: "monochrome" | "omitted";
  output_width: number;
  output_height: number;
  font: { family: string; em_per_size: number };
  safe_area: { version: string; top: number; bottom: number; left: number; right: number };
  positions: Record<"top" | "center" | "bottom", Placement>;
  presets: PresetSpec[];
  hook: {
    max_chars: number;
    max_lines: number;
    min_seconds: number;
    max_seconds: number;
    default_seconds: number;
    fade_in_ms: number;
    fade_out_ms: number;
    styles: Array<{
      name: HookStyle;
      label: string;
      size: number;
      bold: boolean;
      text: string;
      outline_colour: string;
      outline: number;
      shadow: number;
      box: boolean;
      box_alpha: number;
      max_line_width: number;
    }>;
    positions: Record<HookPosition, Placement>;
  };
};

export type CaptionTrackStatus = "queued" | "preparing_audio" | "aligning" | "validating" | "completed" | "failed";

/** Word timing of a clip (no task ids, paths or model locations). Always real word timing. */
export type CaptionTrack = {
  id: string;
  clip_id: string;
  status: CaptionTrackStatus;
  progress_percent: number;
  attempt: number;
  is_stale: boolean;
  timing_mode: "aligned_word";
  provider: string;
  model: string;
  language: string | null;
  word_count: number | null;
  rejected_word_count: number | null;
  average_confidence: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type CaptionTimingOptions = {
  word_timing: "none" | "running" | "completed" | "failed";
  track: CaptionTrack | null;
  phrase_timing_available: boolean;
};

import type { PreviewCue } from "@/lib/caption-timing";

export type { PreviewCue, PreviewWord } from "@/lib/caption-timing";
export type CaptionPreview = { timing: CaptionTiming; emoji: "monochrome" | "omitted"; cues: PreviewCue[] };

const ACTIVE: CaptionTrackStatus[] = ["queued", "preparing_audio", "aligning", "validating"];
export const isTrackActive = (status: CaptionTrackStatus) => ACTIVE.includes(status);
/** Status order within one timing attempt (see lib/status-sync.ts). */
export const TRACK_STAGES = stageRanks(ACTIVE, ["completed", "failed"]);

const clipBase = (projectId: string, videoId: string, clipId: string) =>
  `/projects/${projectId}/videos/${videoId}/clips/${clipId}`;

export const getCaptionStyles = () => apiFetch<CaptionStyles>("/caption-styles");

export const getTimingOptions = (projectId: string, videoId: string, clipId: string) =>
  apiFetch<CaptionTimingOptions>(`${clipBase(projectId, videoId, clipId)}/caption-timing`);

export const startWordTiming = (projectId: string, videoId: string, clipId: string) =>
  postJson<CaptionTrack>(`${clipBase(projectId, videoId, clipId)}/caption-tracks`, undefined);

export const getTrack = (projectId: string, videoId: string, clipId: string, id: string) =>
  apiFetch<CaptionTrack>(`${clipBase(projectId, videoId, clipId)}/caption-tracks/${id}`);

export const retryWordTiming = (projectId: string, videoId: string, clipId: string, id: string) =>
  postJson<CaptionTrack>(`${clipBase(projectId, videoId, clipId)}/caption-tracks/${id}/retry`, undefined);

/** The captions exactly as the renderer lays them out; null when they cannot be built yet. */
export async function getCaptionPreview(
  projectId: string,
  videoId: string,
  clipId: string,
  params: { style: DynamicPreset; position: string; timing: CaptionTiming; trackId?: string | null },
): Promise<CaptionPreview | null> {
  const query = new URLSearchParams({ style: params.style, position: params.position, timing: params.timing });
  if (params.trackId) query.set("track_id", params.trackId);
  try {
    return await apiFetch<CaptionPreview>(`${clipBase(projectId, videoId, clipId)}/caption-preview?${query}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) return null;
    throw error;
  }
}

/** Plain-language stage copy for word timing (no model or provider jargon). */
export function timingStageLabel(track: CaptionTrack): string {
  switch (track.status) {
    case "queued":
      return "Waiting to start";
    case "preparing_audio":
      return "Reading the clip's audio";
    case "aligning":
      return "Timing every word";
    case "validating":
      return "Checking the timing";
    case "completed":
      return "Word synced";
    case "failed":
      return "Word timing failed";
  }
}

export function timingErrorCopy(track: CaptionTrack): string {
  switch (track.error_code) {
    case "model_load_failed":
    case "provider_missing":
    case "provider_capability":
      return "Word timing isn't available on this server right now.";
    case "clip_missing":
    case "clip_not_ready":
    case "audio_decode_failed":
      return "The clip's audio couldn't be read. Regenerate the clip, then try again.";
    case "time_limit":
      return "Word timing took too long. Try again.";
    case "queue_unavailable":
      return "The queue is busy or offline. Try again in a moment.";
    default:
      return "We couldn't time the words of this clip. Try again, or use phrase timing.";
  }
}
