/** Visual elements of an edit (B-roll cutaways, picture-in-picture, overlays): types and the
 * pure rules shared by the editor and its preview. They mirror the server (the API is the
 * authority): `app/services/visuals/config.py`, `assets.py`, `transitions.py`, `layout.py`.
 * No imports: unit-tested with node --test. */

export type VisualMode = "cutaway" | "pip" | "overlay";
export type VisualFit = "fill" | "fit";
export type VisualPosition = "top_left" | "top_right" | "bottom_left" | "bottom_right" | "center";
export type VisualSize = "small" | "medium" | "large";
export type VisualTransition = "none" | "fade";

/** One element as the editor holds it (`key` is local only, never sent). */
export type VisualElementDraft = {
  key: string;
  asset_id: string;
  mode: VisualMode;
  start_seconds: number;
  end_seconds: number;
  fit: VisualFit;
  position: VisualPosition;
  size: VisualSize;
  opacity: number;
  asset_offset_seconds: number;
  loop: boolean;
  transition: VisualTransition;
  transition_seconds: number;
};

/** What the request carries for one element (options that do not apply are left out). */
export type VisualElementRequest = {
  asset_id: string;
  mode: VisualMode;
  start_seconds: number;
  end_seconds: number;
  fit?: VisualFit;
  position?: VisualPosition;
  size?: VisualSize;
  opacity?: number;
  asset_offset_seconds?: number;
  loop?: boolean;
  transition?: VisualTransition;
  transition_seconds?: number;
};

/** The part of a visual asset the rules need. */
export type AssetFacts = { kind: "image" | "video"; duration_seconds: number | null; width: number; height: number };

/** Published by the server (`GET /visual-layout`): where insets sit in the 1080 × 1920 frame. */
export type VisualLayout = {
  output: { width: number; height: number };
  margins: { top: number; bottom: number; left: number; right: number };
  inset_width_fraction: Record<VisualSize, number>;
  inset_max_aspect: number;
  pip_border: number;
  background: string;
};

export const MAX_ELEMENTS = 12;
export const MIN_ELEMENT_SECONDS = 0.5;
export const FADE_RANGE = { min: 0.1, max: 0.5, default: 0.3 };
export const OPACITY_RANGE = { min: 0.2, max: 1 };
export const DEFAULT_ELEMENT_SECONDS = 3;

export const MODE_LABELS: Record<VisualMode, string> = {
  cutaway: "Cutaway",
  pip: "Picture-in-picture",
  overlay: "Overlay",
};
export const POSITION_LABELS: Record<VisualPosition, string> = {
  top_left: "Top left",
  top_right: "Top right",
  bottom_left: "Bottom left",
  bottom_right: "Bottom right",
  center: "Centre",
};

const round = (value: number, decimals = 2) => {
  const f = 10 ** decimals;
  return Math.round(value * f) / f + 0;
};

let counter = 0;
/** A new element for `asset`, starting at `at` (clamped so it fits in the short). */
export function newElement(
  assetId: string,
  asset: AssetFacts,
  at: number,
  clipDuration: number,
  mode?: VisualMode,
  end?: number,
): VisualElementDraft {
  counter += 1;
  const start = round(Math.max(0, Math.min(at, Math.max(0, clipDuration - MIN_ELEMENT_SECONDS))));
  const maxLength = asset.kind === "video" && asset.duration_seconds ? asset.duration_seconds : DEFAULT_ELEMENT_SECONDS;
  const stop = end ?? Math.min(clipDuration, start + Math.min(DEFAULT_ELEMENT_SECONDS, maxLength));
  return {
    key: `v${Date.now().toString(36)}${counter}`,
    asset_id: assetId,
    mode: mode ?? "cutaway",
    start_seconds: start,
    end_seconds: round(Math.max(start + MIN_ELEMENT_SECONDS, Math.min(clipDuration, stop))),
    fit: "fill",
    position: "top_right",
    size: "medium",
    opacity: 1,
    asset_offset_seconds: 0,
    loop: false,
    transition: "none",
    transition_seconds: FADE_RANGE.default,
  };
}

/** The request for one element: rounded like the server, options for its mode only. */
export function elementRequest(element: VisualElementDraft, asset?: AssetFacts): VisualElementRequest {
  const request: VisualElementRequest = {
    asset_id: element.asset_id,
    mode: element.mode,
    start_seconds: round(element.start_seconds),
    end_seconds: round(element.end_seconds),
  };
  if (element.mode === "cutaway") request.fit = element.fit;
  else {
    request.position = element.mode === "pip" && element.position === "center" ? "top_right" : element.position;
    request.size = element.size;
  }
  if (element.mode === "overlay") request.opacity = round(element.opacity);
  if (asset?.kind === "video") {
    request.asset_offset_seconds = round(element.asset_offset_seconds);
    request.loop = element.loop;
  }
  if (element.transition === "fade") {
    request.transition = "fade";
    request.transition_seconds = round(element.transition_seconds);
  }
  return request;
}

/** Problems with one element, in the server's words (empty when it is valid). */
export function elementProblems(element: VisualElementDraft, asset: AssetFacts | undefined, clipDuration: number): string[] {
  const problems: string[] = [];
  if (!asset) return ["This visual is no longer in the project."];
  const { start_seconds: start, end_seconds: end } = element;
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0) problems.push("Start must be 0 or later.");
  else if (end - start < MIN_ELEMENT_SECONDS) problems.push(`A visual must last at least ${MIN_ELEMENT_SECONDS} seconds.`);
  if (end > clipDuration + 0.01) problems.push("A visual ends after the end of the clip.");
  if (element.mode === "overlay" && asset.kind === "video") problems.push("Overlays use images; use picture-in-picture for a video.");
  if (element.mode === "overlay" && (element.opacity < OPACITY_RANGE.min || element.opacity > OPACITY_RANGE.max))
    problems.push("Opacity must be between 20 % and 100 %.");
  if (asset.kind === "video") {
    const length = asset.duration_seconds ?? 0;
    if (element.asset_offset_seconds < 0 || element.asset_offset_seconds >= length)
      problems.push("The video start is after the end of the video.");
    else if (!element.loop && element.asset_offset_seconds + (end - start) > length + 0.05)
      problems.push("This video is shorter than the visual: shorten it, start earlier in the video, or turn on loop.");
  }
  if (element.transition === "fade") {
    const ramp = element.transition_seconds;
    if (ramp < FADE_RANGE.min || ramp > FADE_RANGE.max) problems.push("A fade lasts between 0.1 and 0.5 seconds.");
    else if (ramp * 2 > end - start) problems.push("A fade cannot be longer than half the visual.");
  }
  return problems;
}

/** Overlap problems across elements: one cutaway and one inset at a time. */
export function overlapProblems(elements: VisualElementDraft[]): Map<string, string> {
  const problems = new Map<string, string>();
  const groups: [VisualElementDraft[], string][] = [
    [elements.filter((e) => e.mode === "cutaway"), "Two cutaways cannot overlap."],
    [elements.filter((e) => e.mode !== "cutaway"), "Two picture-in-picture or overlay visuals cannot overlap."],
  ];
  for (const [group, message] of groups) {
    const sorted = [...group].sort((a, b) => a.start_seconds - b.start_seconds || a.end_seconds - b.end_seconds);
    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i].start_seconds < sorted[i - 1].end_seconds) {
        problems.set(sorted[i].key, message);
        problems.set(sorted[i - 1].key, message);
      }
    }
  }
  return problems;
}

/** How visible an element is at short time `t` (0..1), before overlay opacity — the
 * renderer's linear fade ramp (`transitions.py: opacity_at`). */
export function opacityAt(element: VisualElementDraft, t: number): number {
  if (t < element.start_seconds || t >= element.end_seconds) return 0;
  if (element.transition !== "fade" || !element.transition_seconds) return 1;
  const ramp = element.transition_seconds;
  return Math.max(0, Math.min(1, (t - element.start_seconds) / ramp, (element.end_seconds - t) / ramp));
}

/** Where a video asset is at short time `t`: its offset plus the time elapsed, wrapping to the
 * start when looping (FFmpeg's `-stream_loop`), or `null` outside the element. */
export function assetTimeAt(element: VisualElementDraft, t: number, assetDuration: number): number | null {
  if (t < element.start_seconds || t >= element.end_seconds || assetDuration <= 0) return null;
  const position = element.asset_offset_seconds + (t - element.start_seconds);
  if (!element.loop) return Math.min(position, assetDuration);
  return position % assetDuration;
}

/** An inset's box in output pixels: fitted inside the size's box, plus the PiP frame. */
export function insetRect(
  element: Pick<VisualElementDraft, "mode" | "size" | "position">,
  asset: Pick<AssetFacts, "width" | "height">,
  layout: VisualLayout,
): { x: number; y: number; width: number; height: number; border: number } {
  const { width: W, height: H } = layout.output;
  const even = (v: number) => Math.max(2, Math.round(v / 2) * 2);
  const boxW = even(W * layout.inset_width_fraction[element.size]);
  const boxH = even(boxW * layout.inset_max_aspect);
  const scale = Math.min(boxW / asset.width, boxH / asset.height);
  const border = element.mode === "pip" ? layout.pip_border : 0;
  const width = even(asset.width * scale) + 2 * border;
  const height = even(asset.height * scale) + 2 * border;
  const { left, right, top, bottom } = layout.margins;
  const position = element.mode === "pip" && element.position === "center" ? "top_right" : element.position;
  const x = position.endsWith("left") ? left : position.endsWith("right") ? W - width - right : (W - width) / 2;
  const y = position.startsWith("top") ? top : position.startsWith("bottom") ? H - height - bottom : (H - height) / 2;
  return { x, y, width, height, border };
}

/** "1:05.3"-style times for timing fields and suggestion labels. */
export function formatSeconds(seconds: number): string {
  const s = Math.max(0, seconds);
  const minutes = Math.floor(s / 60);
  return `${minutes}:${(s - minutes * 60).toFixed(1).padStart(4, "0")}`;
}

/** "2 visuals" for the settings summary. */
export function visualsSummary(count: number): string | null {
  if (!count) return null;
  return `${count} visual${count === 1 ? "" : "s"}`;
}

type Comparable = {
  asset_id?: unknown;
  mode?: unknown;
  start_seconds?: unknown;
  end_seconds?: unknown;
  fit?: unknown;
  position?: unknown;
  size?: unknown;
  opacity?: unknown;
  asset_offset_seconds?: unknown;
  loop?: unknown;
  transition?: unknown;
  transition_seconds?: unknown;
};

/** A canonical key for a list of elements (a request's or a stored snapshot's), normalized
 * like the server's fingerprint: equal keys mean the same visuals. */
export function visualsKey(elements: readonly Comparable[] | null | undefined): string {
  if (!elements?.length) return "";
  const n = (value: unknown, fallback = 0) => round(typeof value === "number" ? value : fallback);
  const canon = elements.map((e) => {
    const inset = e.mode !== "cutaway";
    return [
      String(e.asset_id),
      String(e.mode),
      n(e.start_seconds),
      n(e.end_seconds),
      inset ? null : (e.fit ?? "fill"),
      inset ? (e.mode === "pip" && e.position === "center" ? "top_right" : (e.position ?? "top_right")) : null,
      inset ? (e.size ?? "medium") : null,
      e.mode === "overlay" ? n(e.opacity, 1) : null,
      n(e.asset_offset_seconds),
      e.loop === true,
      e.transition === "fade" ? n(e.transition_seconds, FADE_RANGE.default) : null,
    ];
  });
  return JSON.stringify(canon.map((c) => JSON.stringify(c)).sort());
}

/** The visuals stored in an edit's configuration snapshot. */
export function visualsFromConfiguration(configuration: Record<string, unknown> | null | undefined): Comparable[] {
  const visuals = configuration?.visuals as { elements?: Comparable[] } | undefined;
  return visuals?.elements ?? [];
}

/** Whether a visual element fulfils a suggested moment: it covers at least half of it. A
 * suggestion counts as "used" only while a current element fulfils it — removing that element
 * makes it available again (the server's "accepted" status is history, not current use). */
export function fulfills(
  element: { start_seconds: number; end_seconds: number },
  moment: { start: number; end: number },
): boolean {
  const length = moment.end - moment.start;
  const overlap = Math.min(element.end_seconds, moment.end) - Math.max(element.start_seconds, moment.start);
  return length > 0 && overlap >= length / 2 - 1e-6;
}
