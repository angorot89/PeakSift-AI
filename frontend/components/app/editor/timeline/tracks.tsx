"use client";

import { Captions, ImageIcon, Music, Plus, Sparkles, Type, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent, type ReactNode } from "react";
import { Waveform } from "@/components/app/editor/audio-timeline";
import { TimelineTrack, useTimelineScale } from "@/components/app/editor/timeline/timeline";
import { cueAt, type PreviewCue } from "@/lib/caption-timing";
import {
  captionRegions,
  dragTimes,
  fractionAt,
  keyEdit,
  roundTime,
  snapDelta,
  itemTooltip,
  timecode,
  timeRange,
  type Bounds,
  type DragMode,
  type Edges,
  type ItemKind,
  type TimelineItem,
} from "@/lib/timeline";

const KIND_STYLE: Record<ItemKind, string> = {
  hook: "border-accent/70 bg-accent/25 text-orange-50",
  cutaway: "border-info/60 bg-info/20 text-sky-50",
  pip: "border-violet/60 bg-violet/20 text-violet-50",
  overlay: "border-violet/60 bg-violet/20 text-violet-50",
  sfx: "border-success/70 bg-success/30 text-emerald-50",
  music: "border-success/40 bg-success/10 text-emerald-100",
};

export type ItemEdit = {
  edges: Edges;
  bounds: Bounds;
  /** Where edges may snap (taken when a drag starts): the playhead, the ends, other items. */
  snapPoints: () => number[];
  /** Why this timing cannot be used (an overlap, a limit), or null. */
  validate: (start: number, end: number) => string | null;
  commit: (start: number, end: number) => void;
  remove?: () => void;
};

export type TrackActions = {
  selectedId: string | null;
  onSelect: (item: TimelineItem) => void;
  /** How an item may be edited on the timeline (null: select only). */
  editFor?: (item: TimelineItem) => ItemEdit | null;
  /** Says something politely (a move that was undone, and why). */
  onMessage?: (text: string) => void;
};

type Ghost = { start: number; end: number; problem: string | null; snap: number | null };

/** One item as a block (or a diamond marker for a sound effect), placed by its timing. Items
 * that support it can be dragged, resized by their handles, or moved with the keyboard. */
export function ItemBlock({
  item,
  lanes = 1,
  selected,
  actions,
  children,
}: {
  item: TimelineItem;
  lanes?: 1 | 2;
  selected: boolean;
  actions: TrackActions;
  children?: ReactNode;
}) {
  const { duration, width } = useTimelineScale();
  const edit = actions.editFor?.(item) ?? null;
  const [ghost, setGhost] = useState<Ghost | null>(null);
  const ghostRef = useRef<Ghost | null>(null);
  const drag = useRef<{ mode: DragMode; x: number; moved: boolean; points: number[] } | null>(null);
  const pxPerSecond = width / Math.max(0.1, duration);

  const shown = ghost ?? { start: item.start, end: item.end, problem: null, snap: null };
  const left = fractionAt(shown.start, duration) * 100;
  const span = Math.max(0, fractionAt(shown.end, duration) - fractionAt(shown.start, duration)) * 100;
  const vertical = lanes === 2 ? (item.lane === 0 ? "top-1 h-[calc(50%-0.375rem)]" : "bottom-1 h-[calc(50%-0.375rem)]") : "inset-y-1.5";
  // (On touch screens the rows are taller, so each lane stays at least 44 px high.)
  const timing = item.kind === "sfx" ? timecode(shown.start) : timeRange(shown.start, shown.end);
  const label = `${item.label === item.name ? item.label : `${item.label}: ${item.name}`}, ${timeRange(item.start, item.end)}`;
  const hint = edit
    ? edit.edges.move
      ? `. Drag to move${edit.edges.end ? " or drag its edges to change the timing" : ""}; arrow keys move it${edit.edges.end ? ", Alt + arrows change its end" : ""}${edit.remove ? ", Delete removes it" : ""}.`
      : edit.edges.end
        ? ". Drag its end, or use the arrow keys, to change how long it lasts."
        : ""
    : "";

  function start(event: PointerEvent<HTMLElement>) {
    if (event.button !== 0) return;
    event.stopPropagation();
    // The block moves; its edge handles (data-drag="start" / "end") change one end.
    const mode = ((event.target as HTMLElement).closest("[data-drag]")?.getAttribute("data-drag") ?? "move") as DragMode;
    if (!edit || !edit.edges[mode]) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { mode, x: event.clientX, moved: false, points: edit.snapPoints() };
  }
  function move(event: PointerEvent<HTMLElement>) {
    const d = drag.current;
    if (!d || !edit) return;
    const dx = event.clientX - d.x;
    if (!d.moved && Math.abs(dx) < 3) return; // a click, not a drag
    d.moved = true;
    const delta = dx / pxPerSecond;
    const moving = d.mode === "move" ? [item.start, item.end] : d.mode === "start" ? [item.start] : [item.end];
    const snapped = event.altKey ? { delta, point: null } : snapDelta(moving, delta, d.points, 8 / pxPerSecond);
    const next = dragTimes(d.mode, item.start, item.end, snapped.delta, edit.bounds);
    const g = { ...next, problem: edit.validate(roundTime(next.start), roundTime(next.end)), snap: snapped.point };
    ghostRef.current = g;
    setGhost(g);
  }
  function end(event: PointerEvent<HTMLElement>) {
    const d = drag.current;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    const g = ghostRef.current;
    ghostRef.current = null;
    setGhost(null);
    if (!d?.moved || !g || !edit) return;
    if (g.problem) actions.onMessage?.(`${g.problem} It went back to where it was.`);
    else edit.commit(roundTime(g.start), roundTime(g.end));
  }
  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!edit) return;
    if ((event.key === "Delete" || event.key === "Backspace") && edit.remove) {
      event.preventDefault();
      edit.remove();
      return;
    }
    const change = keyEdit(event.key, event.shiftKey, event.altKey, edit.edges);
    if (!change) return;
    event.preventDefault();
    const next = dragTimes(change.mode, item.start, item.end, change.delta, edit.bounds);
    const s = roundTime(next.start);
    const e = roundTime(next.end);
    const problem = edit.validate(s, e);
    if (problem) actions.onMessage?.(problem);
    else edit.commit(s, e);
  }

  const handlers = {
    onPointerDown: start,
    onPointerMove: move,
    onPointerUp: end,
    onPointerCancel: end,
    onKeyDown,
    onClick: () => actions.onSelect(item),
  };
  const common = {
    type: "button" as const,
    "data-timeline-item": item.id,
    "data-start": item.start,
    "data-end": item.kind === "sfx" ? Math.max(item.end, item.start + 0.25) : item.end,
    "aria-label": label + hint,
    "aria-pressed": selected,
  };
  const tooltip = ghost ? null : (
    <span
      role="presentation"
      className="pointer-events-none absolute -top-7 z-40 -translate-x-1/2 rounded-md border border-border-strong bg-surface-3 px-1.5 py-0.5 text-[0.6875rem] font-medium whitespace-nowrap text-foreground opacity-0 shadow-raised transition-opacity duration-150 peer-hover:opacity-100 peer-focus-visible:opacity-100"
      style={{ left: `${left + (item.kind === "sfx" ? 0 : span / 2)}%` }}
    >
      {itemTooltip(item, duration)}
    </span>
  );
  const bubble = ghost ? (
    <span
      role="presentation"
      className={`tabular pointer-events-none absolute -top-7 z-40 -translate-x-1/2 rounded-md px-1.5 py-0.5 text-[0.6875rem] font-medium whitespace-nowrap shadow-raised ${
        ghost.problem ? "bg-danger text-white" : "bg-foreground text-background"
      }`}
      style={{ left: `${left + span / 2}%` }}
    >
      {ghost.problem ? "Overlaps" : timing}
    </span>
  ) : null;
  const guide =
    ghost?.snap != null ? (
      <span aria-hidden="true" className="pointer-events-none absolute -inset-y-1 z-30 w-px bg-accent-soft" style={{ left: `${fractionAt(ghost.snap, duration) * 100}%` }} />
    ) : null;

  if (item.kind === "sfx") {
    return (
      <span className="contents">
        {guide}
        {bubble}
        <button
          {...common}
          {...handlers}
          className={`peer group absolute inset-y-0 z-10 flex w-8 -translate-x-1/2 touch-none items-center justify-center outline-none pointer-coarse:w-11 ${edit?.edges.move ? "cursor-grab active:cursor-grabbing" : ""}`}
          style={{ left: `${left}%` }}
        >
          <span
            aria-hidden="true"
            className={`size-3 rotate-45 rounded-[3px] border transition-transform duration-150 group-hover:scale-125 group-data-[active=true]:scale-150 group-data-[active=true]:bg-success/70 group-focus-visible:ring-2 group-focus-visible:ring-accent ${
              ghost?.problem ? "border-danger bg-danger/40" : KIND_STYLE.sfx
            } ${selected || ghost ? "scale-125 ring-2 ring-accent ring-offset-2 ring-offset-surface" : ""}`}
          />
        </button>
        {tooltip}
      </span>
    );
  }
  const handle = (side: "start" | "end") =>
    edit?.edges[side] ? (
      <span
        aria-hidden="true"
        data-drag={side}
        className={`absolute inset-y-0 z-20 w-2.5 cursor-ew-resize touch-none pointer-coarse:w-5 ${side === "start" ? "left-0" : "right-0"} ${
          selected ? "opacity-100" : "opacity-0 group-hover:opacity-100"
        }`}
      >
        <span className={`absolute inset-y-1.5 w-1 rounded-full bg-white/80 ${side === "start" ? "left-0.5" : "right-0.5"}`} />
      </span>
    ) : null;
  return (
    <span className="contents">
      {guide}
      {bubble}
      <button
        {...common}
        {...handlers}
        className={`peer group absolute z-10 flex min-w-1.5 touch-none items-center data-[active=true]:shadow-[0_0_0_1px_rgb(255_255_255/0.35),0_0_16px_-4px_currentColor] data-[active=true]:brightness-125 gap-1.5 overflow-hidden rounded-control border px-2 text-left text-caption font-medium whitespace-nowrap transition-[box-shadow,filter] duration-150 outline-none hover:brightness-125 focus-visible:ring-2 focus-visible:ring-accent ${vertical} ${
          ghost?.problem ? "border-danger bg-danger/25 text-rose-50" : KIND_STYLE[item.kind]
        } ${selected || ghost ? "ring-2 ring-accent ring-offset-1 ring-offset-surface" : ""} ${ghost ? "shadow-raised" : ""} ${
          edit?.edges.move ? "cursor-grab active:cursor-grabbing" : ""
        }`}
        style={{ left: `${left}%`, width: `${span}%` }}
      >
        {handle("start")}
        {children ?? (
          <span className="pointer-events-none truncate">
            {item.label}
            {item.name !== item.label ? <span className="font-normal opacity-75"> · {item.name.replace(/\.[a-z0-9]+$/i, "")}</span> : null}
          </span>
        )}
        {handle("end")}
      </button>
      {tooltip}
    </span>
  );
}

/** A track with nothing on it yet: what is missing, and the one way to add it. */
function EmptyLane({ text, action, onAction }: { text: string; action: string; onAction: () => void }) {
  return (
    <div className="absolute inset-y-0 left-2 flex items-center gap-3">
      <span className="text-caption text-subtle">{text}</span>
      <button
        type="button"
        onClick={onAction}
        className="inline-flex min-h-8 items-center gap-1 rounded-control border border-dashed border-border-strong px-2.5 text-caption font-medium text-muted transition-colors hover:border-accent/50 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent pointer-coarse:min-h-11"
      >
        <Plus aria-hidden="true" className="size-3.5" />
        {action}
      </button>
    </div>
  );
}

function ItemsTrack({
  label,
  icon,
  items,
  lanes = 1,
  empty,
  actions,
}: {
  label: string;
  icon: LucideIcon;
  items: TimelineItem[];
  lanes?: 1 | 2;
  empty: { text: string; action: string; onAction: () => void };
  actions: TrackActions;
}) {
  return (
    <TimelineTrack label={label} icon={icon} tall={lanes === 2}>
      {items.length ? (
        items.map((item) => (
          <ItemBlock key={item.id} item={item} lanes={lanes} selected={actions.selectedId === item.id} actions={actions} />
        ))
      ) : (
        <EmptyLane {...empty} />
      )}
    </TimelineTrack>
  );
}

export function OpeningTrack({ items, actions, onAdd }: { items: TimelineItem[]; actions: TrackActions; onAdd: () => void }) {
  return <ItemsTrack label="Opening" icon={Type} items={items} actions={actions} empty={{ text: "No hook", action: "Add a hook", onAction: onAdd }} />;
}

export function VisualsTrack({ items, actions, onAdd }: { items: TimelineItem[]; actions: TrackActions; onAdd: () => void }) {
  const twoLanes = items.some((i) => i.lane === 1) && items.some((i) => i.lane === 0);
  return (
    <ItemsTrack
      label="Visuals"
      icon={ImageIcon}
      items={items}
      lanes={twoLanes ? 2 : 1}
      actions={actions}
      empty={{ text: "No visuals added", action: "Add visual", onAction: onAdd }}
    />
  );
}

export function SoundTrack({ items, actions, onAdd }: { items: TimelineItem[]; actions: TrackActions; onAdd: () => void }) {
  return <ItemsTrack label="Sound" icon={Sparkles} items={items} actions={actions} empty={{ text: "No sound effects", action: "Add effect", onAction: onAdd }} />;
}

export function MusicTrack({
  item,
  peaks,
  actions,
  onAdd,
}: {
  item: TimelineItem | null;
  peaks: number[] | null;
  actions: TrackActions;
  onAdd: () => void;
}) {
  return (
    <TimelineTrack label="Music" icon={Music}>
      {item ? (
        <ItemBlock item={item} selected={actions.selectedId === item.id} actions={actions}>
          {peaks?.length ? <Waveform peaks={peaks} className="absolute inset-x-1 inset-y-1.5 w-auto text-emerald-300/60" /> : null}
          <span className="relative truncate">{item.label}</span>
        </ItemBlock>
      ) : (
        <EmptyLane text="No music" action="Add music" onAction={onAdd} />
      )}
    </TimelineTrack>
  );
}

/** Word ticks for the whole Short on one canvas (never a DOM node per word). */
function WordTicks({ cues }: { cues: PreviewCue[] }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const { duration, width } = useTimelineScale();
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const ratio = window.devicePixelRatio || 1;
    element.width = Math.max(1, Math.round(element.clientWidth * ratio));
    element.height = Math.max(1, Math.round(element.clientHeight * ratio));
    const context = element.getContext("2d");
    if (!context) return;
    context.clearRect(0, 0, element.width, element.height);
    context.fillStyle = getComputedStyle(element).color;
    for (const cue of cues) {
      if (!cue.timed) continue;
      for (const line of cue.lines) {
        for (const word of line) {
          const x = (word.start / Math.max(0.1, duration)) * element.width;
          context.fillRect(Math.round(x), element.height * 0.25, Math.max(1, ratio), element.height * 0.5);
        }
      }
    }
  }, [cues, duration, width]);
  return <canvas ref={canvas} aria-hidden="true" className="pointer-events-none absolute inset-x-0 inset-y-1.5 h-[calc(100%-0.75rem)] w-full text-white/35" />;
}

/** Captions as density, not hundreds of blocks: grouped regions, with word ticks when timed. */
export function CaptionsTrack({
  enabled,
  cues,
  selected,
  onSelect,
  onAdd,
}: {
  enabled: boolean;
  cues: PreviewCue[] | null;
  selected: boolean;
  onSelect: () => void;
  onAdd: () => void;
}) {
  const { duration, seek } = useTimelineScale();
  if (!enabled) {
    return (
      <TimelineTrack label="Captions" icon={Captions}>
        <EmptyLane text="Captions off" action="Turn on captions" onAction={onAdd} />
      </TimelineTrack>
    );
  }
  const regions = captionRegions(cues ?? []);
  const timed = (cues ?? []).some((c) => c.timed);
  const lines = cues ?? [];
  // A click shows the caption line under the pointer from its start (the same line the preview
  // shows there), or seeks to that moment between lines.
  const showLine = (event: MouseEvent<HTMLButtonElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const at = ((event.clientX - box.left) / Math.max(1, box.width)) * duration;
    const index = cueAt(lines, at);
    seek(index >= 0 ? lines[index].start + 0.02 : at);
    onSelect();
  };
  return (
    <TimelineTrack label="Captions" icon={Captions}>
      <button
        type="button"
        data-timeline-item="captions"
        aria-pressed={selected}
        aria-label={`Captions: ${(cues ?? []).length} lines${timed ? ", timed word by word" : ""}`}
        onClick={showLine}
        className={`absolute inset-0 z-10 rounded-control outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset ${selected ? "bg-white/[0.04]" : ""}`}
      >
        {regions.map((region) => (
          <span
            key={region.start}
            aria-hidden="true"
            className={`absolute inset-y-2 rounded-[6px] border ${selected ? "border-white/40 bg-white/20" : "border-white/15 bg-white/10"}`}
            style={{
              left: `${fractionAt(region.start, duration) * 100}%`,
              width: `${Math.max(0, fractionAt(region.end, duration) - fractionAt(region.start, duration)) * 100}%`,
            }}
          />
        ))}
        {lines.map((cue) => (
          <span
            key={`${cue.start}-${cue.end}`}
            aria-hidden="true"
            data-start={cue.start}
            data-end={cue.end}
            className="absolute inset-y-3 rounded-[4px] transition-colors duration-150 data-[active=true]:bg-white/45"
            style={{
              left: `${fractionAt(cue.start, duration) * 100}%`,
              width: `${Math.max(0, fractionAt(cue.end, duration) - fractionAt(cue.start, duration)) * 100}%`,
            }}
          />
        ))}
        {timed ? <WordTicks cues={lines} /> : null}
        {cues === null ? <span className="absolute inset-y-0 left-2 flex items-center text-caption text-subtle">Loading captions…</span> : null}
      </button>
    </TimelineTrack>
  );
}
