"use client";

import { Scissors, Trash2, Undo2, Wand2 } from "lucide-react";
import { useMemo } from "react";
import { ControlGroup } from "@/components/app/editor/controls";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  cutsProblem,
  findPauses,
  formatSeconds,
  normalizeCuts,
  outputDuration,
  PAUSE_CHOICES,
  restorePart,
  segmentsOf,
  withPauses,
  type Range,
  type TimedWord,
} from "@/lib/cuts";

/** What Tighten works on: removed ranges (all of them), which of them came from pauses, and the
 * creator's split points (editor-only marks; a split alone changes nothing). Clip time. */
export type TightenState = { cuts: Range[]; pauseCuts: Range[]; splits: number[]; pauseSeconds: number };

function clock(seconds: number) {
  const s = Math.max(0, seconds);
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
}

const same = (a: Range, b: Range) => Math.abs(a[0] - b[0]) < 0.002 && Math.abs(a[1] - b[1]) < 0.002;

/**
 * Tighten: remove the pauses between words (from the clip's real word timing) and cut parts by
 * hand (split at the playhead, then remove the part the playhead is in). Everything is undoable
 * here; the render follows exactly these cuts, and captions follow the words.
 */
export function TightenPanel({
  state,
  onChange,
  clipSeconds,
  words,
  wordsNote,
  playhead,
  onSeek,
}: {
  state: TightenState;
  onChange: (next: TightenState) => void;
  clipSeconds: number;
  /** The clip's word timing; null while it is not available (`wordsNote` says why). */
  words: TimedWord[] | null;
  wordsNote: React.ReactNode;
  /** The preview's clip time now. */
  playhead: () => number;
  onSeek: (clipTime: number) => void;
}) {
  const { cuts, pauseCuts, splits, pauseSeconds } = state;
  const found = useMemo(
    () => (words ? findPauses(words, clipSeconds, pauseSeconds) : []),
    [words, clipSeconds, pauseSeconds],
  );
  const pausesOn = pauseCuts.length > 0;
  const saved = found.reduce((sum, [s, e]) => sum + (e - s), 0);
  const manual = cuts.filter((range) => !pauseCuts.some((p) => same(p, range)));
  const shortSeconds = outputDuration(cuts, clipSeconds);
  const problem = cutsProblem(cuts, clipSeconds);

  function setPauseLength(seconds: number) {
    const next = { ...state, pauseSeconds: seconds };
    if (pausesOn && words) {
      // Already removed: follow the new length straight away (the creator's own cuts stay).
      const pauses = findPauses(words, clipSeconds, seconds);
      next.cuts = withPauses(cuts, pauses, pauseCuts);
      next.pauseCuts = pauses;
    }
    onChange(next);
  }
  function removePauses() {
    onChange({ ...state, cuts: withPauses(cuts, found, pauseCuts), pauseCuts: found });
  }
  function keepPauses() {
    onChange({ ...state, cuts: withPauses(cuts, [], pauseCuts), pauseCuts: [] });
  }
  function split() {
    const at = Math.round(playhead() * 1000) / 1000;
    if (at <= 0.05 || at >= clipSeconds - 0.05 || splits.some((s) => Math.abs(s - at) < 0.05)) return;
    onChange({ ...state, splits: [...splits, at].sort((a, b) => a - b) });
  }
  // Read when clicked: the playhead moves without re-rendering this panel.
  function removeCurrent() {
    const t = playhead();
    const current = segmentsOf(cuts, splits, clipSeconds).find(
      (segment) => !segment.removed && t >= segment.start && t < segment.end,
    );
    if (!current || (current.start <= 0.001 && current.end >= clipSeconds - 0.001)) return;
    onChange({ ...state, cuts: normalizeCuts([...cuts, [current.start, current.end]]) });
  }
  function restore(range: Range) {
    onChange({ ...state, cuts: restorePart(cuts, pauseCuts, range) });
  }

  return (
    <div className="space-y-6">
      <p className="text-small text-pretty text-muted">
        Make the Short move: leave out the pauses between your words, or cut a part yourself. Captions, the opening
        and everything on the timeline follow the shorter Short.
      </p>

      <ControlGroup legend="Remove pauses" hint={words ? undefined : "Needs word timing"}>
        {words ? (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <p className="text-caption text-subtle">Remove pauses longer than</p>
              <SegmentedControl
                label="Pause length"
                size="sm"
                wrap
                options={PAUSE_CHOICES.map((s) => ({ value: String(s), label: `${s} s` }))}
                value={String(pauseSeconds)}
                onChange={(value) => setPauseLength(Number(value))}
              />
            </div>
            <p className="text-small text-muted" aria-live="polite">
              {found.length ? (
                <>
                  <span className="font-semibold text-foreground">
                    {found.length} {found.length === 1 ? "pause" : "pauses"}
                  </span>{" "}
                  longer than {pauseSeconds} s · {formatSeconds(saved)} shorter
                </>
              ) : (
                `No pauses longer than ${pauseSeconds} s.`
              )}
            </p>
            {pausesOn ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-small text-success">Pauses removed</span>
                <Button variant="ghost" size="sm" onClick={keepPauses}>
                  <Undo2 aria-hidden="true" />
                  Put the pauses back
                </Button>
              </div>
            ) : (
              <Button onClick={removePauses} disabled={!found.length}>
                <Wand2 aria-hidden="true" />
                {found.length ? `Remove ${found.length} ${found.length === 1 ? "pause" : "pauses"}` : "Remove pauses"}
              </Button>
            )}
          </div>
        ) : (
          <div className="text-small text-muted">{wordsNote}</div>
        )}
      </ControlGroup>

      <ControlGroup legend="Cut by hand" hint="At the playhead">
        <p className="text-caption text-pretty text-subtle">
          Split before and after a part, then remove the part the playhead is in.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={split}>
            <Scissors aria-hidden="true" />
            Split at playhead
          </Button>
          <Button variant="secondary" size="sm" onClick={removeCurrent} disabled={!splits.length}>
            <Trash2 aria-hidden="true" />
            Remove this part
          </Button>
        </div>
        {splits.length ? (
          <p className="text-caption text-subtle">
            {splits.length} {splits.length === 1 ? "split" : "splits"} ·{" "}
            <button
              type="button"
              className="inline-flex min-h-11 items-center text-accent-soft underline-offset-2 hover:underline pointer-fine:min-h-0"
              onClick={() => onChange({ ...state, splits: [] })}
            >
              Clear splits
            </button>
          </p>
        ) : null}
        {manual.length ? (
          <ul className="space-y-1.5" aria-label="Parts you removed">
            {manual.map((range) => (
              <li
                key={`${range[0]}-${range[1]}`}
                className="flex items-center justify-between gap-2 rounded-control border border-border bg-surface-2 px-3 py-1.5 text-small"
              >
                <button
                  type="button"
                  className="tabular min-h-11 text-left text-muted hover:text-foreground pointer-fine:min-h-0"
                  onClick={() => onSeek(range[0])}
                >
                  {clock(range[0])}–{clock(range[1])} · {formatSeconds(range[1] - range[0])}
                </button>
                <Button variant="ghost" size="sm" onClick={() => restore(range)}>
                  Restore
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </ControlGroup>

      {cuts.length ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-border bg-surface-2 px-3 py-2.5">
          <p className="tabular text-small text-muted">
            Clip {formatSeconds(clipSeconds)} → Short{" "}
            <span className="font-semibold text-foreground">{formatSeconds(shortSeconds)}</span>
          </p>
          <Button variant="ghost" size="sm" onClick={() => onChange({ ...state, cuts: [], pauseCuts: [], splits: [] })}>
            <Undo2 aria-hidden="true" />
            Restore everything
          </Button>
        </div>
      ) : null}
      {problem ? <InlineAlert title="This cannot be rendered yet">{problem}</InlineAlert> : null}
    </div>
  );
}
