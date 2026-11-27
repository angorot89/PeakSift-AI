/**
 * Tighten: the parts of a clip a Short leaves out (pauses, or segments the creator deleted).
 *
 * Removed ranges are in the clip's own time. The editor's timeline, the hook, visuals and
 * sounds are on the *Short's* timeline (what is left, back to back); `toOutput` / `toSource`
 * move between the two. Mirrors the server's normalization (backend
 * `services/clip_edit/cuts.py`), which validates again: rounded to a millisecond, sorted,
 * merged, slivers folded away, tiny cuts dropped. Pure, no imports: unit-tested with node --test.
 */

export type Range = [number, number];

export const MIN_CUT_SECONDS = 0.05;
export const MIN_PIECE_SECONDS = 0.04;
export const MIN_KEPT_SECONDS = 1;
export const MAX_CUTS = 300;
/** The pause length below which a gap stays, as StreamLadder's default (0.5 s). */
export const DEFAULT_PAUSE_SECONDS = 0.5;
export const PAUSE_CHOICES = [0.2, 0.3, 0.5, 0.75, 1, 1.5];
/** Speech kept on each side of a removed pause, so a word's first and last sound survive. */
export const PAUSE_PADDING_SECONDS = 0.08;

const round3 = (value: number) => Math.round(value * 1000) / 1000;

/** Sorted, merged and rounded removed ranges; [] when nothing is removed. */
export function normalizeCuts(ranges: readonly Range[]): Range[] {
  const spans = ranges
    .filter(([start, end]) => Number.isFinite(start) && Number.isFinite(end))
    .map(([start, end]) => [round3(Math.max(0, start)), round3(end)] as Range)
    .filter(([start, end]) => end > start)
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged: Range[] = [];
  for (const [start, end] of spans) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1] + MIN_PIECE_SECONDS) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }
  return merged.filter(([start, end]) => end - start >= MIN_CUT_SECONDS);
}

/** The parts of [0, duration] that stay, in order. */
export function keptRanges(cuts: readonly Range[], duration: number): Range[] {
  const pieces: Range[] = [];
  let cursor = 0;
  for (const [start, end] of cuts) {
    if (start - cursor >= MIN_PIECE_SECONDS) pieces.push([cursor, Math.min(start, duration)]);
    cursor = Math.max(cursor, end);
    if (cursor >= duration) break;
  }
  if (duration - cursor >= MIN_PIECE_SECONDS) pieces.push([cursor, duration]);
  return pieces.filter(([s, e]) => e > s);
}

export const outputDuration = (cuts: readonly Range[], duration: number) =>
  keptRanges(cuts, duration).reduce((sum, [s, e]) => sum + (e - s), 0);

/** Clip time → Short time; a time inside a removed range lands on its join. */
export function toOutput(cuts: readonly Range[], t: number): number {
  let shift = 0;
  for (const [start, end] of cuts) {
    if (t >= end) shift += end - start;
    else if (t > start) return start - shift;
    else break;
  }
  return t - shift;
}

/** Short time → clip time (the first moment of the clip shown at that point). */
export function toSource(cuts: readonly Range[], duration: number, t: number): number {
  let elapsed = 0;
  const kept = keptRanges(cuts, duration);
  for (const [start, end] of kept) {
    if (t < elapsed + (end - start)) return start + Math.max(0, t - elapsed);
    elapsed += end - start;
  }
  return kept.length ? kept[kept.length - 1][1] : 0;
}

/** Where playback continues from clip time `t`: past the removed range it is in, else `t`. */
export function skipRemoved(cuts: readonly Range[], t: number): number {
  for (const [start, end] of cuts) {
    if (t >= start && t < end - 0.001) return end;
    if (start > t) break;
  }
  return t;
}

export type TimedWord = { start: number; end: number };

/**
 * The pauses longer than `minPause` between spoken words, as ranges to remove: each keeps
 * `padding` of silence next to the words around it. Silence before the first word and after
 * the last counts too. Words are the clip's real word timings (never estimated).
 */
export function findPauses(
  words: readonly TimedWord[],
  duration: number,
  minPause = DEFAULT_PAUSE_SECONDS,
  padding = PAUSE_PADDING_SECONDS,
): Range[] {
  const sorted = [...words].filter((w) => w.end > w.start).sort((a, b) => a.start - b.start);
  if (!sorted.length) return [];
  const gaps: Range[] = [[0, sorted[0].start]];
  let spoken = sorted[0].end;
  for (const word of sorted.slice(1)) {
    if (word.start > spoken) gaps.push([spoken, word.start]);
    spoken = Math.max(spoken, word.end);
  }
  gaps.push([spoken, duration]);
  const pauses: Range[] = [];
  gaps.forEach(([start, end], index) => {
    if (end - start < minPause) return;
    const first = index === 0;
    const last = index === gaps.length - 1;
    const from = first ? 0 : start + padding;
    const to = last ? duration : end - padding;
    if (to - from >= MIN_CUT_SECONDS) pauses.push([from, to]);
  });
  return normalizeCuts(pauses);
}

/** The removed ranges that came from pauses, kept apart from segments the creator deleted. */
export function withPauses(cuts: readonly Range[], pauses: readonly Range[], previousPauses: readonly Range[]): Range[] {
  const manual = cuts.filter(([s, e]) => !previousPauses.some(([ps, pe]) => Math.abs(ps - s) < 0.002 && Math.abs(pe - e) < 0.002));
  return normalizeCuts([...manual, ...pauses]);
}

const sameRange = (a: Range, b: Range) => Math.abs(a[0] - b[0]) < 0.002 && Math.abs(a[1] - b[1]) < 0.002;

/**
 * Which stored cuts are pauses (a reopened version keeps only its ranges). The rest stay the
 * creator's own cuts.
 */
export function recognizePauses(
  cuts: readonly Range[],
  words: readonly TimedWord[],
  duration: number,
): { pauseCuts: Range[]; pauseSeconds: number } | null {
  // The most pauses that are all among the cuts; of lengths that find the same pauses, the longest.
  let best: { pauseCuts: Range[]; pauseSeconds: number } | null = null;
  for (const seconds of PAUSE_CHOICES) {
    const pauses = findPauses(words, duration, seconds);
    if (!pauses.length || !pauses.every((pause) => cuts.some((cut) => sameRange(cut, pause)))) continue;
    if (!best || pauses.length >= best.pauseCuts.length) best = { pauseCuts: pauses, pauseSeconds: seconds };
  }
  return best;
}

/** Undo one removed part. A part cut by hand may have merged with removed pauses inside it:
 * those pauses stay removed (they are undone with "Put the pauses back"). */
export function restorePart(cuts: readonly Range[], pauseCuts: readonly Range[], part: Range): Range[] {
  const kept = cuts.filter((cut) => !sameRange(cut, part));
  const inside = pauseCuts.filter(([s, e]) => s >= part[0] - 0.002 && e <= part[1] + 0.002 && !sameRange([s, e], part));
  return normalizeCuts([...kept, ...inside]);
}

export type Segment = { start: number; end: number; removed: boolean };

/** The clip split at the creator's split points and at every cut, in clip time. */
export function segmentsOf(cuts: readonly Range[], splits: readonly number[], duration: number): Segment[] {
  const marks = new Set<number>([0, duration]);
  for (const [s, e] of cuts) {
    marks.add(Math.max(0, s));
    marks.add(Math.min(duration, e));
  }
  for (const s of splits) if (s > 0 && s < duration) marks.add(round3(s));
  const points = [...marks].sort((a, b) => a - b);
  const segments: Segment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [start, end] = [points[i], points[i + 1]];
    if (end - start < 0.001) continue;
    const middle = (start + end) / 2;
    segments.push({ start, end, removed: cuts.some(([s, e]) => middle > s && middle < e) });
  }
  return segments;
}

/** Why a set of cuts cannot be rendered, in the creator's words; null when it can. */
export function cutsProblem(cuts: readonly Range[], duration: number): string | null {
  if (cuts.length > MAX_CUTS) return `A Short can leave out at most ${MAX_CUTS} parts. Use a longer pause length.`;
  if (cuts.length && outputDuration(cuts, duration) < MIN_KEPT_SECONDS) return "Leave at least one second of the clip.";
  return null;
}

/** The removed ranges stored in an edit's configuration (none when it has no cuts section). */
export function cutsFromConfiguration(configuration: Record<string, unknown> | null | undefined): Range[] {
  const section = configuration?.cuts as { removed?: unknown } | undefined;
  if (!section || !Array.isArray(section.removed)) return [];
  return normalizeCuts(
    section.removed.filter(
      (r): r is Range => Array.isArray(r) && r.length === 2 && typeof r[0] === "number" && typeof r[1] === "number",
    ),
  );
}

export const cutsKey = (cuts: readonly Range[]) => JSON.stringify(normalizeCuts(cuts));

/** "1.7 s shorter · 10 pauses" style summary pieces. */
export function formatSeconds(seconds: number): string {
  return seconds >= 10 ? `${Math.round(seconds)} s` : `${(Math.round(seconds * 10) / 10).toFixed(1)} s`;
}
