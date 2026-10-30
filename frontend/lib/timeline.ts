// The editor timeline's pure rules (no React): the time scale, ruler ticks, time labels and the
// mapping between positions and seconds. Unit-tested with node --test.
//
// The timeline only *shows* the edit: every item is derived from the editor's own settings
// (hook, visuals, captions, sound) and every change goes back through the same setters the
// forms use. There is no second copy of the edit here.

/** The narrowest a second may be drawn, so short labels stay readable; longer Shorts scroll. */
export const MIN_PX_PER_SECOND = 28;

/** Steps the ruler may use, in seconds; the smallest that keeps labels this far apart wins. */
const TICK_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60];
const MIN_TICK_GAP_PX = 64;

/** How wide the time canvas is: the container when the whole Short fits, wider (scrolling)
 * when a second would get narrower than `MIN_PX_PER_SECOND`. */
export function canvasWidth(duration: number, containerWidth: number, minPxPerSecond = MIN_PX_PER_SECOND): number {
  const safe = Math.max(0.1, duration);
  return Math.max(containerWidth, Math.ceil(safe * minPxPerSecond));
}

export function tickStep(duration: number, width: number): number {
  const pxPerSecond = width / Math.max(0.1, duration);
  return TICK_STEPS.find((step) => step * pxPerSecond >= MIN_TICK_GAP_PX) ?? TICK_STEPS[TICK_STEPS.length - 1];
}

/** Ruler ticks from 0 to the end (the end itself is not labelled twice). */
export function ticks(duration: number, step: number): number[] {
  const out: number[] = [];
  for (let t = 0; t < duration - step * 0.25; t = Math.round((t + step) * 1000) / 1000) out.push(t);
  return out;
}

/** A position along the canvas (0..1) as seconds, clamped to the Short. */
export function timeAtFraction(fraction: number, duration: number): number {
  return Math.min(duration, Math.max(0, fraction * duration));
}

/** Seconds as a fraction (0..1) of the Short. */
export function fractionAt(seconds: number, duration: number): number {
  return Math.min(1, Math.max(0, seconds / Math.max(0.1, duration)));
}

/** A ruler label: "0:00", "0:10", "1:05"; half seconds read "0:02.5". */
export function rulerLabel(seconds: number): string {
  const whole = Math.floor(seconds + 1e-6);
  const m = Math.floor(whole / 60);
  const s = String(whole % 60).padStart(2, "0");
  const tenths = Math.round((seconds - whole) * 10);
  return `${m}:${s}${tenths ? `.${tenths}` : ""}`;
}

/** A precise time for tooltips and readouts: "0:12.4". */
export function timecode(seconds: number): string {
  const safe = Math.max(0, seconds);
  const m = Math.floor(safe / 60);
  const rest = safe - m * 60;
  const s = rest.toFixed(1).padStart(4, "0");
  return `${m}:${s === "60.0" ? "59.9" : s}`;
}

/** A span for tooltips: "0:12.4–0:15.2". */
export const timeRange = (start: number, end: number) => `${timecode(start)}–${timecode(end)}`;

/** Keyboard seeking: the new time for a key (arrows ±1 s, Shift ±5 s, Home/End), or null. */
export function seekForKey(key: string, shift: boolean, now: number, duration: number): number | null {
  const step = shift ? 5 : 1;
  const moves: Record<string, number> = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step };
  if (key in moves) return Math.min(duration, Math.max(0, now + moves[key]));
  if (key === "Home") return 0;
  if (key === "End") return duration;
  return null;
}

/** How many still frames the video track shows: about one per 90 px, never more than 12. */
export function filmFrameCount(width: number): number {
  return Math.min(12, Math.max(3, Math.round(width / 90)));
}

/** The seconds those frames come from: the middle of each equal slice of the Short. */
export function filmFrameTimes(duration: number, count: number): number[] {
  const slice = Math.max(0.1, duration) / count;
  return Array.from({ length: count }, (_, i) => Math.round((i + 0.5) * slice * 100) / 100);
}

// --- Items: everything a track shows, derived from the editor's own settings -------------------

export type TrackKey = "opening" | "visuals" | "captions" | "sound" | "music";
export type ItemKind = "hook" | "cutaway" | "pip" | "overlay" | "sfx" | "music";

/** What an item stands for in the editor's state (never a database id or a copy of it). */
export type ItemRef = { type: "hook" } | { type: "visual"; key: string } | { type: "sfx"; index: number } | { type: "music" };

export type TimelineItem = {
  id: string;
  track: TrackKey;
  /** Visuals use two lanes: cutaways (0) and picture-in-picture / overlays (1). */
  lane: 0 | 1;
  kind: ItemKind;
  start: number;
  end: number;
  /** A short name for the block ("B-roll", "Whoosh"). */
  label: string;
  /** What it is, for tooltips and screen readers ("lava-pit.png"). */
  name: string;
  ref: ItemRef;
};

export type TimelineInput = {
  duration: number;
  hook: { on: boolean; text: string; seconds: number };
  visuals: { key: string; mode: "cutaway" | "pip" | "overlay"; start: number; end: number; name: string }[];
  sfx: { name: string; at: number; seconds: number | null }[];
  music: { name: string; end: number } | null;
};

export const KIND_LABELS: Record<ItemKind, string> = {
  hook: "Hook",
  cutaway: "B-roll",
  pip: "PiP",
  overlay: "Overlay",
  sfx: "Sound effect",
  music: "Music",
};

/** A sound effect's length on the timeline: the file's length, or a short marker when unknown. */
const SFX_FALLBACK_SECONDS = 0.4;

/** Every item on the timeline, from the editor's settings, clamped to the Short. */
export function timelineItems(input: TimelineInput): TimelineItem[] {
  const d = Math.max(0.1, input.duration);
  const clamp = (t: number) => Math.min(d, Math.max(0, t));
  const items: TimelineItem[] = [];
  if (input.hook.on) {
    const text = input.hook.text.trim();
    items.push({
      id: "hook",
      track: "opening",
      lane: 0,
      kind: "hook",
      start: 0,
      end: clamp(input.hook.seconds),
      label: "Hook",
      name: text || "Opening hook",
      ref: { type: "hook" },
    });
  }
  for (const v of input.visuals) {
    items.push({
      id: `visual:${v.key}`,
      track: "visuals",
      lane: v.mode === "cutaway" ? 0 : 1,
      kind: v.mode,
      start: clamp(v.start),
      end: clamp(Math.max(v.start, v.end)),
      label: KIND_LABELS[v.mode],
      name: v.name,
      ref: { type: "visual", key: v.key },
    });
  }
  input.sfx.forEach((cue, index) => {
    const start = clamp(cue.at);
    items.push({
      id: `sfx:${index}`,
      track: "sound",
      lane: 0,
      kind: "sfx",
      start,
      end: clamp(start + (cue.seconds ?? SFX_FALLBACK_SECONDS)),
      label: cue.name,
      name: cue.name,
      ref: { type: "sfx", index },
    });
  });
  if (input.music) {
    items.push({
      id: "music",
      track: "music",
      lane: 0,
      kind: "music",
      start: 0,
      end: clamp(input.music.end),
      label: input.music.name,
      name: input.music.name,
      ref: { type: "music" },
    });
  }
  return items;
}

/** Where the music is heard: from the start, to the end of the Short when it loops, otherwise
 * until the track (from its start point) runs out. */
export function musicEnd(loop: boolean, trackSeconds: number, sourceStart: number, duration: number): number {
  if (loop || trackSeconds <= 0) return duration;
  return Math.min(duration, Math.max(0, trackSeconds - sourceStart));
}

/** Whether the visuals need their second lane (any picture-in-picture or overlay). */
export const usesInsetLane = (items: TimelineItem[]) => items.some((i) => i.track === "visuals" && i.lane === 1);

/** Caption lines grouped into readable regions: lines closer than `gap` seconds join. */
export function captionRegions(cues: { start: number; end: number }[], gap = 0.6): { start: number; end: number; lines: number }[] {
  const sorted = [...cues].sort((a, b) => a.start - b.start);
  const regions: { start: number; end: number; lines: number }[] = [];
  for (const cue of sorted) {
    const last = regions[regions.length - 1];
    if (last && cue.start - last.end <= gap) {
      last.end = Math.max(last.end, cue.end);
      last.lines += 1;
    } else regions.push({ start: cue.start, end: cue.end, lines: 1 });
  }
  return regions;
}

/** The editor tool that edits an item. */
export function toolForItem(ref: ItemRef): "opening" | "visuals" | "sound" {
  if (ref.type === "hook") return "opening";
  if (ref.type === "visual") return "visuals";
  return "sound";
}

// --- Editing on the timeline: only what the edit already supports ------------------------------

export type DragMode = "move" | "start" | "end";
export type Edges = { move: boolean; start: boolean; end: boolean };

/** What may change by dragging: visuals move and resize; a sound effect moves (it plays its
 * whole file); the hook always starts at 0, so only its end moves; music and captions follow
 * the Short and do not drag. */
export function editableEdges(kind: ItemKind): Edges {
  if (kind === "cutaway" || kind === "pip" || kind === "overlay") return { move: true, start: true, end: true };
  if (kind === "sfx") return { move: true, start: false, end: false };
  if (kind === "hook") return { move: false, start: false, end: true };
  return { move: false, start: false, end: false };
}

export type Bounds = { duration: number; minLength: number; maxLength?: number };

/** The item's new timing after dragging by `delta` seconds, kept inside the Short and its own
 * length limits (moving keeps the length). */
export function dragTimes(mode: DragMode, start: number, end: number, delta: number, bounds: Bounds): { start: number; end: number } {
  const { duration, minLength } = bounds;
  const maxLength = bounds.maxLength ?? duration;
  if (mode === "move") {
    const length = end - start;
    const s = Math.min(Math.max(0, start + delta), Math.max(0, duration - length));
    return { start: s, end: s + length };
  }
  if (mode === "start") {
    const s = Math.min(Math.max(0, start + delta, end - maxLength), end - minLength);
    return { start: s, end };
  }
  const e = Math.max(Math.min(duration, end + delta, start + maxLength), start + minLength);
  return { start, end: e };
}

/** Snapping: the delta that brings the nearest dragged edge onto a point within `tolerance`
 * seconds, and the point it snapped to (or the delta unchanged). */
export function snapDelta(edges: number[], delta: number, points: number[], tolerance: number): { delta: number; point: number | null } {
  let best: { delta: number; point: number; distance: number } | null = null;
  for (const edge of edges) {
    for (const point of points) {
      const distance = Math.abs(edge + delta - point);
      if (distance <= tolerance && (!best || distance < best.distance)) best = { delta: point - edge, point, distance };
    }
  }
  return best ? { delta: best.delta, point: best.point } : { delta, point: null };
}

/** Times are stored to the nearest 0.05 s (what the forms show and the renderer accepts). */
export const roundTime = (seconds: number) => Math.round(seconds * 20) / 20;

/** Keyboard editing of a selected item: ←/→ move it (Shift: 1 s, else 0.1 s); with Alt they
 * change its end (resizable items only). Null when the key does nothing for this item. */
export function keyEdit(key: string, shift: boolean, alt: boolean, edges: Edges): { mode: DragMode; delta: number } | null {
  const step = shift ? 1 : 0.1;
  const sign = key === "ArrowRight" ? 1 : key === "ArrowLeft" ? -1 : 0;
  if (!sign) return null;
  if (alt) return edges.end ? { mode: "end", delta: sign * step } : null;
  return edges.move ? { mode: "move", delta: sign * step } : edges.end ? { mode: "end", delta: sign * step } : null;
}

/** Where the preview goes when an item is selected: the middle of a visual (it is on screen),
 * just before a sound effect (so it is heard when playing), the start of the hook; music and
 * captions keep the current time. */
export function representativeTime(item: Pick<TimelineItem, "start" | "end" | "ref">): number | null {
  if (item.ref.type === "visual") return (item.start + item.end) / 2;
  if (item.ref.type === "sfx") return Math.max(0, item.start - 0.5);
  if (item.ref.type === "hook") return 0;
  return null;
}

/** Whether an item is playing at `t` — the same half-open interval the preview uses. */
export const activeAt = (start: number, end: number, t: number) => t >= start && t < end;

/** A tooltip for an item: "B-roll · 0:12.4–0:15.2", "Whoosh · 0:10.2", "Music · Full Short". */
export function itemTooltip(item: Pick<TimelineItem, "kind" | "label" | "start" | "end">, duration: number): string {
  if (item.kind === "sfx") return `${item.label} · ${timecode(item.start)}`;
  if (item.kind === "music" && item.start <= 0.01 && item.end >= duration - 0.01) return `${item.label} · Full Short`;
  return `${item.label} · ${timeRange(item.start, item.end)}`;
}

export type RenderState = "blocked" | "attention" | "rendering" | "rendered" | "unrendered";

/** The editor's render state in creator words. Settings are saved as a version only when
 * rendered — there is no autosave, so nothing claims "Saved" before that. */
export const RENDER_STATE: Record<RenderState, { label: string; tone: "warning" | "danger" | "processing" | "success" | "neutral" }> = {
  blocked: { label: "Needs a fix to render", tone: "warning" },
  attention: { label: "Needs attention", tone: "danger" },
  rendering: { label: "Rendering…", tone: "processing" },
  rendered: { label: "Rendered", tone: "success" },
  unrendered: { label: "Not rendered yet", tone: "neutral" },
};

export function renderState(s: { blocked: boolean; stuck: boolean; active: boolean; ready: boolean }): RenderState {
  if (s.blocked) return "blocked";
  if (s.stuck) return "attention";
  if (s.active) return "rendering";
  if (s.ready) return "rendered";
  return "unrendered";
}
