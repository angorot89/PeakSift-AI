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
