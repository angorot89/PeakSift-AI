/** The short-form editor's settings as one value, and loading them from a stored configuration
 * (a rendered version or an Auto Edit plan) — so the editor opens with exactly what was saved,
 * never silently with defaults. Type imports only: unit-tested with node --test. */
import type { AudioRequest, DuckingStrength } from "@/lib/audio-mix";
import type { CaptionTiming, DynamicPreset, HookPosition, HookStyle } from "@/lib/captions";
import { cutsFromConfiguration, type Range } from "./cuts.ts";
import type { CaptionPosition, PickableLayout } from "@/lib/edits";
import type {
  VisualElementDraft,
  VisualFit,
  VisualMode,
  VisualPosition,
  VisualSize,
  VisualTransition,
} from "@/lib/visual-elements";

export type FramingMode = "auto" | "manual";

export type EditorDraft = {
  layout: PickableLayout;
  framingMode: FramingMode;
  focus: { x: number; y: number };
  captions: boolean;
  preset: DynamicPreset;
  position: CaptionPosition;
  timing: CaptionTiming;
  hookOn: boolean;
  /** null keeps the editor's current text (for example the candidate's suggested hook). */
  hookText: string | null;
  hookStyle: HookStyle;
  hookPosition: HookPosition;
  hookDuration: number;
  audio: AudioRequest;
  /** Whether the edit has an audio section at all (a stored "normalize only" section counts:
   * dropping it would render without loudness normalization). */
  audioSection: boolean;
  visuals: VisualElementDraft[];
  /** The version's brand section (without its version tag), kept as it was. */
  brand: Record<string, unknown> | null;
  /** Tighten: the parts of the clip this Short leaves out, in the clip's own time. */
  cuts: Range[];
};

export const DEFAULT_DRAFT: EditorDraft = {
  layout: "blur_background",
  framingMode: "auto",
  focus: { x: 0.5, y: 0.5 },
  captions: true,
  preset: "focus",
  position: "bottom",
  timing: "aligned_word",
  hookOn: false,
  hookText: null,
  hookStyle: "headline",
  hookPosition: "top",
  hookDuration: 2,
  audio: { source_gain_db: 0, normalize: true, music: null, sfx: [] },
  audioSection: false,
  visuals: [],
  brand: null,
  cuts: [],
};

/** The analysis and word track the editor would use today (to say when a stored one differs). */
export type CurrentInputs = { analysisId: string | null; trackId: string | null };

export type Hydration = { draft: EditorDraft; notes: string[] };

/** V0.6 phrase-caption styles are shown with the closest dynamic preset (and said so). */
const CLASSIC_STYLES: Record<string, DynamicPreset> = { clean: "minimal", bold: "punch", creator: "boxed" };
const DYNAMIC = new Set<string>(["focus", "punch", "minimal", "boxed"]);
const LAYOUTS = new Set<string>(["center_crop", "blur_background", "fit", "smart_reframe"]);
const DUCKING = new Set<string>(["off", "light", "medium", "strong"]);

type Snapshot = Record<string, unknown>;
const obj = (value: unknown): Snapshot | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Snapshot) : null;
const num = (value: unknown, fallback: number) => (typeof value === "number" && Number.isFinite(value) ? value : fallback);
const str = (value: unknown) => (typeof value === "string" ? value : null);

function audioFrom(value: unknown): AudioRequest {
  const audio = obj(value);
  if (!audio) return { source_gain_db: 0, normalize: true, music: null, sfx: [] };
  const music = obj(audio.music);
  const ducking = str(music?.ducking);
  return {
    source_gain_db: num(audio.source_gain_db, 0),
    normalize: audio.normalize !== false,
    music:
      music && str(music.asset_id)
        ? {
            asset_id: str(music.asset_id) as string,
            gain_db: num(music.gain_db, -16),
            source_start_seconds: num(music.source_start_seconds, 0),
            loop: music.loop !== false,
            fade_in_seconds: num(music.fade_in_seconds, 0.5),
            fade_out_seconds: num(music.fade_out_seconds, 1),
            ducking: (ducking && DUCKING.has(ducking) ? ducking : "medium") as DuckingStrength,
          }
        : null,
    sfx: Array.isArray(audio.sfx)
      ? audio.sfx.flatMap((cue) => {
          const c = obj(cue);
          const id = str(c?.asset_id);
          return c && id ? [{ asset_id: id, at_seconds: num(c.at_seconds, 0), gain_db: num(c.gain_db, -6) }] : [];
        })
      : [],
  };
}

function visualsFrom(value: unknown): VisualElementDraft[] {
  const elements = obj(value)?.elements;
  if (!Array.isArray(elements)) return [];
  return elements.flatMap((raw, index) => {
    const e = obj(raw);
    const id = str(e?.asset_id);
    if (!e || !id) return [];
    return [
      {
        key: `stored-${index}-${id.slice(0, 8)}`,
        asset_id: id,
        mode: (str(e.mode) ?? "cutaway") as VisualMode,
        start_seconds: num(e.start_seconds, 0),
        end_seconds: num(e.end_seconds, 0),
        fit: (str(e.fit) ?? "fill") as VisualFit,
        position: (str(e.position) ?? "top_right") as VisualPosition,
        size: (str(e.size) ?? "medium") as VisualSize,
        opacity: num(e.opacity, 1),
        asset_offset_seconds: num(e.asset_offset_seconds, 0),
        loop: e.loop === true,
        transition: (str(e.transition) ?? "none") as VisualTransition,
        transition_seconds: num(e.transition_seconds, 0.3),
      },
    ];
  });
}

/** The editor settings that reproduce `configuration`, and notes for anything that could not
 * be reproduced exactly (shown to the creator; nothing changes silently). */
export function draftFromConfiguration(configuration: Snapshot | null | undefined, current: CurrentInputs): Hydration {
  const notes: string[] = [];
  const config = obj(configuration) ?? {};
  const draft: EditorDraft = { ...DEFAULT_DRAFT, focus: { ...DEFAULT_DRAFT.focus } };

  const layout = str(config.layout);
  if (layout === "manual_crop") {
    const focus = obj(config.focus);
    draft.layout = "smart_reframe";
    draft.framingMode = "manual";
    draft.focus = { x: num(focus?.x, 0.5), y: num(focus?.y, 0.5) };
  } else if (layout && LAYOUTS.has(layout)) {
    draft.layout = layout as PickableLayout;
    if (layout === "smart_reframe") {
      const stored = str(obj(config.reframe)?.analysis_id);
      if (!current.analysisId) notes.push("This version's framing analysis is not current; analyze the framing again to render it.");
      else if (stored && stored !== current.analysisId) notes.push("Framing uses this clip's current analysis.");
    }
  }

  const captions = obj(config.captions);
  draft.captions = captions?.enabled === true;
  if (draft.captions && captions) {
    const style = str(captions.style) ?? "focus";
    if (DYNAMIC.has(style)) {
      draft.preset = style as DynamicPreset;
      draft.timing = str(captions.timing) === "phrase_fallback" ? "phrase_fallback" : "aligned_word";
    } else {
      draft.preset = CLASSIC_STYLES[style] ?? "focus";
      draft.timing = "phrase_fallback";
      notes.push("This version used a classic caption style; the closest current style is selected.");
    }
    const position = str(captions.position);
    if (position === "top" || position === "center" || position === "bottom") draft.position = position;
    if (draft.timing === "aligned_word") {
      const stored = str(captions.track_id);
      if (!current.trackId) notes.push("Word timing for this version is not current; generate word sync or use phrase timing.");
      else if (stored && stored !== current.trackId) notes.push("Captions use this clip's current word timing.");
    }
  }

  const hook = obj(config.hook);
  if (hook && str(hook.text)) {
    draft.hookOn = true;
    draft.hookText = str(hook.text);
    draft.hookStyle = (str(hook.style) ?? "headline") as HookStyle;
    draft.hookPosition = str(hook.position) === "center" ? "center" : "top";
    draft.hookDuration = num(hook.duration, 2);
  }

  draft.audio = audioFrom(config.audio);
  draft.audioSection = obj(config.audio) !== null;
  draft.visuals = visualsFrom(config.visuals);
  draft.cuts = cutsFromConfiguration(config);
  const brand = obj(config.brand);
  if (brand) {
    const kept = { ...brand };
    delete kept.version;
    draft.brand = kept;
  }
  return { draft, notes };
}
