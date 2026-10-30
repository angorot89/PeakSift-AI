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
