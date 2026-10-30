"use client";

import { Captions, ImageIcon, Music, Plus, Sparkles, Type, type LucideIcon } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { Waveform } from "@/components/app/editor/audio-timeline";
import { TimelineTrack, useTimelineScale } from "@/components/app/editor/timeline/timeline";
import type { PreviewCue } from "@/lib/caption-timing";
import { captionRegions, fractionAt, timeRange, type ItemKind, type TimelineItem } from "@/lib/timeline";

const KIND_STYLE: Record<ItemKind, string> = {
  hook: "border-accent/70 bg-accent/25 text-orange-50",
  cutaway: "border-info/60 bg-info/20 text-sky-50",
  pip: "border-violet/60 bg-violet/20 text-violet-50",
  overlay: "border-violet/60 bg-violet/20 text-violet-50",
  sfx: "border-success/70 bg-success/30 text-emerald-50",
  music: "border-success/40 bg-success/10 text-emerald-100",
};

export type TrackActions = {
  selectedId: string | null;
  onSelect: (item: TimelineItem) => void;
};

/** One item as a block (or a diamond marker for a sound effect), placed by its timing. */
export function ItemBlock({
  item,
  lanes = 1,
  selected,
  onSelect,
  children,
}: {
  item: TimelineItem;
  lanes?: 1 | 2;
  selected: boolean;
  onSelect: (item: TimelineItem) => void;
  children?: ReactNode;
}) {
  const { duration } = useTimelineScale();
  const left = fractionAt(item.start, duration) * 100;
  const width = Math.max(0, fractionAt(item.end, duration) - fractionAt(item.start, duration)) * 100;
  const vertical = lanes === 2 ? (item.lane === 0 ? "top-1 h-[calc(50%-0.375rem)]" : "bottom-1 h-[calc(50%-0.375rem)]") : "inset-y-1.5";
  const label = `${item.label === item.name ? item.label : `${item.label}: ${item.name}`}, ${timeRange(item.start, item.end)}`;
  if (item.kind === "sfx") {
    return (
      <button
        type="button"
        data-timeline-item={item.id}
        aria-label={label}
        aria-pressed={selected}
        title={label}
        onClick={() => onSelect(item)}
        className="group absolute inset-y-0 z-10 flex w-8 -translate-x-1/2 items-center justify-center outline-none pointer-coarse:w-11"
        style={{ left: `${left}%` }}
      >
        <span
          aria-hidden="true"
          className={`size-3 rotate-45 rounded-[3px] border transition-transform duration-150 group-hover:scale-125 group-focus-visible:ring-2 group-focus-visible:ring-accent ${KIND_STYLE.sfx} ${
            selected ? "scale-125 ring-2 ring-accent ring-offset-2 ring-offset-surface" : ""
          }`}
        />
      </button>
    );
  }
  return (
    <button
      type="button"
      data-timeline-item={item.id}
      aria-label={label}
      aria-pressed={selected}
      title={label}
      onClick={() => onSelect(item)}
      className={`absolute z-10 flex min-w-1.5 items-center gap-1.5 overflow-hidden rounded-control border px-2 text-left text-caption font-medium whitespace-nowrap transition-[box-shadow,filter] duration-150 outline-none hover:brightness-125 focus-visible:ring-2 focus-visible:ring-accent ${vertical} ${KIND_STYLE[item.kind]} ${
        selected ? "ring-2 ring-accent ring-offset-1 ring-offset-surface" : ""
      }`}
      style={{ left: `${left}%`, width: `${width}%` }}
    >
      {children ?? (
        <span className="truncate">
          {item.label}
          {item.name !== item.label ? <span className="font-normal opacity-75"> · {item.name.replace(/\.[a-z0-9]+$/i, "")}</span> : null}
        </span>
      )}
    </button>
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
          <ItemBlock key={item.id} item={item} lanes={lanes} selected={actions.selectedId === item.id} onSelect={actions.onSelect} />
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
        <ItemBlock item={item} selected={actions.selectedId === item.id} onSelect={actions.onSelect}>
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
  const { duration } = useTimelineScale();
  if (!enabled) {
    return (
      <TimelineTrack label="Captions" icon={Captions}>
        <EmptyLane text="Captions off" action="Turn on captions" onAction={onAdd} />
      </TimelineTrack>
    );
  }
  const regions = captionRegions(cues ?? []);
  const timed = (cues ?? []).some((c) => c.timed);
  return (
    <TimelineTrack label="Captions" icon={Captions}>
      <button
        type="button"
        data-timeline-item="captions"
        aria-pressed={selected}
        aria-label={`Captions: ${(cues ?? []).length} lines${timed ? ", timed word by word" : ""}`}
        onClick={onSelect}
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
        {timed ? <WordTicks cues={cues ?? []} /> : null}
        {cues === null ? <span className="absolute inset-y-0 left-2 flex items-center text-caption text-subtle">Loading captions…</span> : null}
      </button>
    </TimelineTrack>
  );
}
