/**
 * Which caption is on screen, and which word is being spoken, at a clip time. Pure (no React,
 * no imports) so it is unit-tested directly. The cues come from the server's caption preview,
 * so these are the renderer's own cues, lines and word intervals.
 */

export type PreviewWord = { text: string; start: number; end: number; attached: boolean };
export type PreviewCue = { start: number; end: number; timed: boolean; lines: PreviewWord[][] };

/** The cue showing at `t` (binary search; cues never overlap), or -1. */
export function cueAt(cues: PreviewCue[], t: number): number {
  let lo = 0;
  let hi = cues.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (t < cues[mid].start) hi = mid - 1;
    else if (t >= cues[mid].end) lo = mid + 1;
    else return mid;
  }
  return -1;
}

/**
 * A key for what is on screen at `t`: the cue and the active words ("line:word"), or "" when
 * no caption shows. Pieces of one split word share its interval, so they light up together.
 * Phrase-timed cues never have active words. Changes only when the picture changes, so a
 * preview can re-render on change instead of on every frame.
 */
export function stateAt(cues: PreviewCue[], t: number): string {
  const index = cueAt(cues, t);
  if (index < 0) return "";
  const cue = cues[index];
  const active: string[] = [];
  if (cue.timed) {
    cue.lines.forEach((line, l) =>
      line.forEach((word, w) => {
        if (word.start <= t && t < word.end) active.push(`${l}:${w}`);
      }),
    );
  }
  return `${index}|${active.join(",")}`;
}

export function parseState(state: string): { cue: number; active: Set<string> } | null {
  if (!state) return null;
  const [cue, words] = state.split("|");
  return { cue: Number(cue), active: new Set(words ? words.split(",") : []) };
}
