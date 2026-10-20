"use client";

import {
  CheckCircle2,
  Clapperboard,
  Film,
  Image as ImageIcon,
  Layers,
  PictureInPicture2,
  Plus,
  RotateCcw,
  Sparkles,
  Trash2,
  Undo2,
  Wand2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { AssetChooser } from "@/components/app/editor/asset-chooser";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Spinner } from "@/components/ui/progress";
import { errorMessage } from "@/lib/api";
import {
  BROLL_ACTIVE,
  brollStage,
  getBrollState,
  methodNote,
  retryBroll,
  setSuggestionStatus,
  startBroll,
  type BrollState,
  type BrollSuggestion,
} from "@/lib/broll";
import { usePolling } from "@/lib/use-polling";
import {
  elementProblems,
  FADE_RANGE,
  formatSeconds,
  fulfills,
  MAX_ELEMENTS,
  MODE_LABELS,
  newElement,
  OPACITY_RANGE,
  overlapProblems,
  POSITION_LABELS,
  type VisualElementDraft,
  type VisualMode,
  type VisualPosition,
} from "@/lib/visual-elements";
import { formatVisualDuration, visualThumbnailUrl, type VisualAsset } from "@/lib/visuals";

const field =
  "h-9 w-full rounded-lg border border-border bg-white/[0.03] px-2.5 text-sm text-foreground outline-none focus:border-accent/60 focus-visible:ring-2 focus-visible:ring-accent/40";

type Chooser = { suggestion: BrollSuggestion | null; replace: string | null } | null;

/** The editor's Visuals section: AI suggestions, the creator's elements, a light timeline. */
export function VisualsPanel({
  projectId,
  videoId,
  clipId,
  duration,
  video,
  assets,
  onUploaded,
  elements,
  onChange,
}: {
  projectId: string;
  videoId: string;
  clipId: string;
  duration: number;
  video: HTMLVideoElement | null;
  assets: VisualAsset[] | null;
  onUploaded: (asset: VisualAsset) => void;
  elements: VisualElementDraft[];
  onChange: (elements: VisualElementDraft[]) => void;
}) {
  const [state, setState] = useState<BrollState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chooser, setChooser] = useState<Chooser>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const byId = useMemo(() => new Map((assets ?? []).map((a) => [a.id, a])), [assets]);

  const load = useCallback(
    () =>
      getBrollState(projectId, videoId, clipId)
        .then((next) => {
          setState(next);
          setError(null);
        })
        .catch((failure) => setError(errorMessage(failure))),
    [projectId, videoId, clipId],
  );
  useEffect(() => {
    void load();
  }, [load]);
  const analysis = state?.analysis ?? null;
  const active = !!analysis && BROLL_ACTIVE.includes(analysis.status) && !analysis.is_stale;
  usePolling(active, load, analysis?.id ?? "none");

  async function suggest(kind: "start" | "regenerate" | "retry") {
    setBusy(true);
    setError(null);
    try {
      if (kind === "retry" && analysis) await retryBroll(projectId, videoId, clipId, analysis.id);
      else await startBroll(projectId, videoId, clipId, kind === "regenerate");
      await load();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  async function decide(suggestion: BrollSuggestion, status: BrollSuggestion["status"]) {
    setState((current) =>
      current ? { ...current, suggestions: current.suggestions.map((s) => (s.id === suggestion.id ? { ...s, status } : s)) } : current,
    );
    try {
      await setSuggestionStatus(projectId, videoId, clipId, suggestion.id, status);
    } catch (failure) {
      setError(errorMessage(failure));
      void load();
    }
  }

  function playhead() {
    return video ? Math.min(video.currentTime || 0, Math.max(0, duration - 0.5)) : 0;
  }

  function pick(asset: VisualAsset) {
    const context = chooser;
    setChooser(null);
    if (context) placeAsset(asset, context);
  }

  function placeAsset(asset: VisualAsset, context: NonNullable<Chooser>) {
    if (context.replace) {
      const replaced = (e: VisualElementDraft): VisualElementDraft => ({
        ...e,
        asset_id: asset.id,
        asset_offset_seconds: 0,
        loop: false,
        mode: asset.kind === "video" && e.mode === "overlay" ? "pip" : e.mode,
      });
      onChange(elements.map((e) => (e.key === context.replace ? replaced(e) : e)));
      return;
    }
    if (elements.length >= MAX_ELEMENTS) return;
    const suggestion = context.suggestion;
    const element = suggestion
      ? newElement(asset.id, asset, suggestion.start, duration, "cutaway", suggestion.end)
      : newElement(asset.id, asset, playhead(), duration);
    onChange([...elements, element].sort((a, b) => a.start_seconds - b.start_seconds));
    setSelected(element.key);
    if (suggestion) void decide(suggestion, "accepted");
  }

  const overlaps = useMemo(() => overlapProblems(elements), [elements]);
  const suggestions = state?.suggestions ?? [];
  const open = suggestions.filter((s) => s.status !== "dismissed");
  const dismissed = suggestions.filter((s) => s.status === "dismissed");
  const note = analysis?.status === "completed" ? methodNote(analysis.method) : null;

  return (
    <section aria-labelledby="visuals-heading" className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 id="visuals-heading" className="text-sm font-semibold text-foreground">
            Visuals
          </h3>
          <p className="mt-0.5 text-xs text-muted">B-roll cutaways, picture-in-picture and overlays from your visual assets.</p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setChooser({ suggestion: null, replace: null })}
          disabled={elements.length >= MAX_ELEMENTS}
        >
          <Plus aria-hidden="true" />
          Add visual
        </Button>
      </div>

      {/* --- AI suggestions --------------------------------------------------------------- */}
      <div className="space-y-3 rounded-xl border border-border bg-surface-2/60 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-[13px] font-medium text-foreground">
            <Sparkles aria-hidden="true" className="size-3.5 text-accent-soft" />
            B-roll suggestions
          </p>
          {!analysis ? (
            <Button size="sm" onClick={() => void suggest("start")} disabled={busy}>
              <Wand2 aria-hidden="true" />
              {busy ? "Starting…" : "Suggest B-roll"}
            </Button>
          ) : analysis.status === "failed" || analysis.is_stale ? (
            <Button size="sm" variant="secondary" onClick={() => void suggest("retry")} disabled={busy}>
              <RotateCcw aria-hidden="true" />
              Try again
            </Button>
          ) : analysis.status === "completed" ? (
            <Button size="sm" variant="ghost" onClick={() => void suggest("regenerate")} disabled={busy}>
              <RotateCcw aria-hidden="true" />
              Suggest again
            </Button>
          ) : null}
        </div>
        {analysis ? (
          <p role="status" className="flex items-center gap-2 text-xs text-muted">
            {active ? <Spinner /> : null}
            {brollStage(analysis)}
            {analysis.status === "failed" && analysis.error_message ? ` — ${analysis.error_message}` : ""}
          </p>
        ) : (
          <p className="text-xs text-muted">
            PeakSift reads the transcript and points out a few moments where a visual would help. You choose what to show.
          </p>
        )}
        {note ? <p className="text-xs text-subtle">{note}</p> : null}
        {open.length ? (
          <ul className="space-y-2" aria-label="Suggested visuals">
            {open.map((s) => (
              <SuggestionCard
                key={s.id}
                projectId={projectId}
                suggestion={s}
                used={elements.some((e) => fulfills(e, s))}
                matches={s.matches.map((id) => byId.get(id)).filter((a): a is VisualAsset => !!a)}
                onUseMatch={(asset) => placeAsset(asset, { suggestion: s, replace: null })}
                onUse={() => setChooser({ suggestion: s, replace: null })}
                onDismiss={() => void decide(s, "dismissed")}
                onSeek={() => {
                  if (video) video.currentTime = s.start;
                }}
                disabled={elements.length >= MAX_ELEMENTS}
              />
            ))}
          </ul>
        ) : null}
        {dismissed.length ? (
          <details className="text-xs text-muted">
            <summary className="cursor-pointer select-none text-subtle hover:text-foreground">
              Dismissed ({dismissed.length})
            </summary>
            <ul className="mt-2 space-y-1.5">
              {dismissed.map((s) => (
                <li key={s.id} className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate">
                    {formatSeconds(s.start)} · {s.query}
                  </span>
                  <Button variant="ghost" size="sm" onClick={() => void decide(s, "suggested")}>
                    <Undo2 aria-hidden="true" />
                    Restore
                  </Button>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        {error ? <InlineAlert title="Suggestions are unavailable">{error}</InlineAlert> : null}
      </div>

      {/* --- the creator's elements ------------------------------------------------------- */}
      {elements.length ? (
        <>
          <VisualsTimeline
            duration={duration}
            video={video}
            elements={elements}
            assets={byId}
            suggestions={open}
            selected={selected}
            onSelect={setSelected}
          />
          <ul className="space-y-3" aria-label="Visuals in this short">
            {elements.map((element) => (
              <ElementEditor
                key={element.key}
                projectId={projectId}
                element={element}
                asset={byId.get(element.asset_id)}
                duration={duration}
                overlap={overlaps.get(element.key) ?? null}
                selected={selected === element.key}
                onFocus={() => setSelected(element.key)}
                onChange={(next) => onChange(elements.map((e) => (e.key === element.key ? next : e)))}
                onRemove={() => onChange(elements.filter((e) => e.key !== element.key))}
                onReplace={() => setChooser({ suggestion: null, replace: element.key })}
                onPlayhead={playhead}
              />
            ))}
          </ul>
        </>
      ) : (
        <p className="text-xs text-subtle">
          No visuals yet. Use a suggestion, or add one at the playhead. Upload only media you own or have permission to use.
        </p>
      )}

      <AssetChooser
        projectId={projectId}
        open={chooser !== null}
        title={chooser?.suggestion ? `Choose a visual for “${chooser.suggestion.query}”` : "Choose a visual"}
        assets={assets}
        query={chooser?.suggestion?.query ?? null}
        matches={chooser?.suggestion?.matches ?? []}
        onPick={pick}
        onUploaded={onUploaded}
        onClose={() => setChooser(null)}
      />
    </section>
  );
}

function SuggestionCard({
  projectId,
  suggestion,
  used,
  matches,
  onUseMatch,
  onUse,
  onDismiss,
  onSeek,
  disabled,
}: {
  projectId: string;
  suggestion: BrollSuggestion;
  /** A current visual element fulfils this suggestion (not "was once used"). */
  used: boolean;
  matches: VisualAsset[];
  onUseMatch: (asset: VisualAsset) => void;
  onUse: () => void;
  onDismiss: () => void;
  onSeek: () => void;
  disabled: boolean;
}) {
  return (
    <li className="rounded-lg border border-border bg-surface px-3 py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <button
            type="button"
            onClick={onSeek}
            className="tabular -my-1 py-1 text-[11px] text-subtle underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-2 focus-visible:outline-accent"
          >
            Suggested at {formatSeconds(suggestion.start)}–{formatSeconds(suggestion.end)}
          </button>
          <p className="mt-0.5 text-sm font-medium text-pretty text-foreground">{suggestion.query}</p>
          <p className="mt-0.5 text-xs text-pretty text-muted">{suggestion.reason}</p>
        </div>
        {used ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-1 text-[11px] font-medium text-emerald-200">
            <CheckCircle2 aria-hidden="true" className="size-3" />
            Used
          </span>
        ) : null}
      </div>
      {matches.length && !used ? (
        <div className="mt-2">
          <p className="text-[11px] font-medium text-muted">Suggested assets</p>
          <ul className="mt-1 flex flex-wrap gap-1.5" aria-label={`Suggested assets for ${suggestion.query}`}>
            {matches.map((asset) => (
              <li key={asset.id}>
                <button
                  type="button"
                  onClick={() => onUseMatch(asset)}
                  disabled={disabled}
                  aria-label={`Use ${asset.display_name} here`}
                  title={asset.display_name}
                  className="flex items-center gap-1.5 rounded-md border border-border bg-surface-2 py-1 pr-2 pl-1 text-[11px] text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
                >
                  <span className={`size-7 overflow-hidden rounded ${asset.has_alpha ? "checkerboard" : "bg-black"}`}>
                    {asset.has_thumbnail ? (
                      // eslint-disable-next-line @next/next/no-img-element -- private, authenticated API image
                      <img src={visualThumbnailUrl(projectId, asset.id)} alt="" className="size-full object-cover" />
                    ) : null}
                  </span>
                  <span className="max-w-28 truncate">{asset.display_name}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" variant={used ? "ghost" : "secondary"} onClick={onUse} disabled={disabled}>
          <Plus aria-hidden="true" />
          {used ? "Use another asset" : "Use asset"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDismiss} aria-label={`Dismiss suggestion: ${suggestion.query}`}>
          <X aria-hidden="true" />
          Dismiss
        </Button>
      </div>
    </li>
  );
}

const MODE_ICONS: Record<VisualMode, typeof Clapperboard> = { cutaway: Clapperboard, pip: PictureInPicture2, overlay: Layers };
const MODE_HINTS: Record<VisualMode, string> = {
  cutaway: "Replaces the picture; the sound keeps playing",
  pip: "A framed box over the video",
  overlay: "An image on top (transparency kept)",
};

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex w-full rounded-lg border border-border bg-surface-2 p-0.5 sm:w-auto">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={`h-8 flex-1 rounded-md px-2.5 text-[12px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent sm:flex-none ${
            value === option.value ? "bg-surface-3 text-foreground" : "text-muted hover:text-foreground"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function NumberField({
  id,
  label,
  value,
  onChange,
  min,
  max,
  step = 0.1,
  suffix = "s",
}: {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
}) {
  const [text, setText] = useState(String(value));
  const [focused, setFocused] = useState(false);
  const shown = focused ? text : String(Math.round(value * 100) / 100);
  return (
    <div className="min-w-0 space-y-1">
      <label htmlFor={id} className="block text-[11px] font-medium text-muted">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type="number"
          inputMode="decimal"
          step={step}
          min={min}
          max={max}
          value={shown}
          onFocus={() => {
            setText(String(Math.round(value * 100) / 100));
            setFocused(true);
          }}
          onBlur={() => setFocused(false)}
          onChange={(event) => {
            setText(event.target.value);
            const next = Number(event.target.value);
            if (event.target.value !== "" && Number.isFinite(next)) onChange(next);
          }}
          className={`${field} tabular pr-7`}
        />
        <span aria-hidden="true" className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-[11px] text-subtle">
          {suffix}
        </span>
      </div>
    </div>
  );
}

function ElementEditor({
  projectId,
  element,
  asset,
  duration,
  overlap,
  selected,
  onFocus,
  onChange,
  onRemove,
  onReplace,
  onPlayhead,
}: {
  projectId: string;
  element: VisualElementDraft;
  asset: VisualAsset | undefined;
  duration: number;
  overlap: string | null;
  selected: boolean;
  onFocus: () => void;
  onChange: (element: VisualElementDraft) => void;
  onRemove: () => void;
  onReplace: () => void;
  onPlayhead: () => number;
}) {
  const id = useId();
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);
  const set = (patch: Partial<VisualElementDraft>) => onChange({ ...element, ...patch });
  const problems = [...elementProblems(element, asset, duration), ...(overlap ? [overlap] : [])];
  const isVideo = asset?.kind === "video";
  const positions: VisualPosition[] =
    element.mode === "overlay" ? ["top_left", "top_right", "center", "bottom_left", "bottom_right"] : ["top_left", "top_right", "bottom_left", "bottom_right"];

  return (
    <li
      ref={ref}
      onFocusCapture={onFocus}
      className={`space-y-3 rounded-xl border bg-surface-2/40 p-3 transition-colors ${selected ? "border-accent/50" : "border-border"}`}
    >
      <div className="flex items-center gap-3">
        <span className={`flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-md ${asset?.has_alpha ? "checkerboard" : "bg-black"}`}>
          {asset?.has_thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element -- private, authenticated API image
            <img src={visualThumbnailUrl(projectId, asset.id)} alt="" className="size-full object-contain" />
          ) : isVideo ? (
            <Film aria-hidden="true" className="size-4 text-subtle" />
          ) : (
            <ImageIcon aria-hidden="true" className="size-4 text-subtle" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground" title={asset?.display_name}>
            {asset?.display_name ?? "Missing visual"}
          </p>
          <p className="tabular text-[11px] text-subtle">
            {MODE_LABELS[element.mode]} · {formatSeconds(element.start_seconds)}–{formatSeconds(element.end_seconds)}
            {isVideo && asset?.duration_seconds ? ` · video ${formatVisualDuration(asset.duration_seconds)}` : ""}
          </p>
        </div>
        <Button variant="ghost" size="sm" className="px-2" onClick={onReplace} aria-label="Choose another asset">
          <RotateCcw aria-hidden="true" />
        </Button>
        <Button variant="ghost" size="sm" className="px-2" onClick={onRemove} aria-label={`Remove ${asset?.display_name ?? "visual"}`}>
          <Trash2 aria-hidden="true" />
        </Button>
      </div>

      <fieldset className="space-y-1.5">
        <legend className="text-[11px] font-medium text-muted">How it appears</legend>
        <div className="grid grid-cols-3 gap-1.5">
          {(Object.keys(MODE_LABELS) as VisualMode[]).map((mode) => {
            const Icon = MODE_ICONS[mode];
            const unavailable = mode === "overlay" && isVideo;
            return (
              <label
                key={mode}
                className={`flex min-h-16 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border px-1.5 py-2 text-center text-[11px] leading-tight has-[:checked]:border-accent/60 has-[:checked]:bg-accent/10 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
                  unavailable ? "cursor-not-allowed border-border opacity-50" : "border-border hover:border-border-strong"
                }`}
                title={unavailable ? "Overlays use images" : MODE_HINTS[mode]}
              >
                <input
                  type="radio"
                  className="sr-only"
                  name={`${id}-mode`}
                  value={mode}
                  checked={element.mode === mode}
                  disabled={unavailable}
                  onChange={() => set({ mode })}
                  aria-describedby={`${id}-mode-${mode}`}
                />
                <Icon aria-hidden="true" className="size-4" />
                <span className="font-medium text-foreground">{MODE_LABELS[mode]}</span>
                <span id={`${id}-mode-${mode}`} className="sr-only">
                  {unavailable ? "Overlays use images" : MODE_HINTS[mode]}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <NumberField id={`${id}-start`} label="Start" value={element.start_seconds} min={0} max={duration} onChange={(v) => set({ start_seconds: v })} />
        <NumberField id={`${id}-end`} label="End" value={element.end_seconds} min={0} max={duration} onChange={(v) => set({ end_seconds: v })} />
        <div className="col-span-2 flex items-end gap-2 sm:col-span-1">
          <p className="tabular pb-2 text-[11px] text-subtle">
            Lasts {Math.max(0, element.end_seconds - element.start_seconds).toFixed(1)} s
          </p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            const start = Math.round(onPlayhead() * 100) / 100;
            const length = Math.max(0.5, element.end_seconds - element.start_seconds);
            set({ start_seconds: start, end_seconds: Math.min(duration, start + length) });
          }}
        >
          Start at playhead
        </Button>
      </div>

      {element.mode === "cutaway" ? (
        <Segmented
          label="Fit"
          value={element.fit}
          options={[
            { value: "fill", label: "Fill the frame" },
            { value: "fit", label: "Fit (blurred edges)" },
          ]}
          onChange={(fit) => set({ fit })}
        />
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="space-y-1">
            <label htmlFor={`${id}-position`} className="block text-[11px] font-medium text-muted">
              Position
            </label>
            <select
              id={`${id}-position`}
              value={element.mode === "pip" && element.position === "center" ? "top_right" : element.position}
              onChange={(event) => set({ position: event.target.value as VisualPosition })}
              className={field}
            >
              {positions.map((p) => (
                <option key={p} value={p}>
                  {POSITION_LABELS[p]}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <span className="block text-[11px] font-medium text-muted">Size</span>
            <Segmented
              label="Size"
              value={element.size}
              options={[
                { value: "small", label: "S" },
                { value: "medium", label: "M" },
                { value: "large", label: "L" },
              ]}
              onChange={(size) => set({ size })}
            />
          </div>
        </div>
      )}

      {element.mode === "overlay" ? (
        <div className="space-y-1">
          <label htmlFor={`${id}-opacity`} className="flex justify-between text-[11px] font-medium text-muted">
            <span>Opacity</span>
            <span className="tabular">{Math.round(element.opacity * 100)} %</span>
          </label>
          <input
            id={`${id}-opacity`}
            type="range"
            min={OPACITY_RANGE.min}
            max={OPACITY_RANGE.max}
            step={0.05}
            value={element.opacity}
            onChange={(event) => set({ opacity: Number(event.target.value) })}
            className="w-full accent-[var(--accent)]"
          />
        </div>
      ) : null}

      {isVideo ? (
        <div className="grid grid-cols-2 items-end gap-2">
          <NumberField
            id={`${id}-offset`}
            label="Video starts at"
            value={element.asset_offset_seconds}
            min={0}
            max={asset?.duration_seconds ?? undefined}
            onChange={(v) => set({ asset_offset_seconds: v })}
          />
          <label className="flex h-9 cursor-pointer items-center gap-2 text-[12px] text-foreground">
            <input type="checkbox" checked={element.loop} onChange={(event) => set({ loop: event.target.checked })} className="size-4 accent-[var(--accent)]" />
            Loop the video
          </label>
        </div>
      ) : null}

      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <span className="block text-[11px] font-medium text-muted">Transition</span>
          <Segmented
            label="Transition"
            value={element.transition}
            options={[
              { value: "none", label: "Cut" },
              { value: "fade", label: "Fade" },
            ]}
            onChange={(transition) => set({ transition })}
          />
        </div>
        {element.transition === "fade" ? (
          <div className="w-28">
            <NumberField
              id={`${id}-fade`}
              label="Fade length"
              value={element.transition_seconds}
              min={FADE_RANGE.min}
              max={FADE_RANGE.max}
              step={0.05}
              onChange={(v) => set({ transition_seconds: v })}
            />
          </div>
        ) : null}
      </div>

      {problems.length ? (
        <ul role="alert" className="space-y-0.5 text-[12px] text-rose-300">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** A light strip over the short: cutaways on one row, insets on another, suggestion marks and
 * the playhead. Blocks are buttons (select an element); timing is edited in its fields. */
function VisualsTimeline({
  duration,
  video,
  elements,
  assets,
  suggestions,
  selected,
  onSelect,
}: {
  duration: number;
  video: HTMLVideoElement | null;
  elements: VisualElementDraft[];
  assets: Map<string, VisualAsset>;
  suggestions: BrollSuggestion[];
  selected: string | null;
  onSelect: (key: string) => void;
}) {
  const [time, setTime] = useState(0);
  useEffect(() => {
    if (!video) return;
    const update = () => setTime(video.currentTime || 0);
    update();
    video.addEventListener("timeupdate", update);
    video.addEventListener("seeked", update);
    return () => {
      video.removeEventListener("timeupdate", update);
      video.removeEventListener("seeked", update);
    };
  }, [video]);
  const pct = (t: number) => `${Math.max(0, Math.min(100, (t / Math.max(duration, 0.01)) * 100))}%`;
  const rows: { label: string; items: VisualElementDraft[] }[] = [
    { label: "Cutaways", items: elements.filter((e) => e.mode === "cutaway") },
    { label: "Insets", items: elements.filter((e) => e.mode !== "cutaway") },
  ];
  return (
    <div className="space-y-1.5" aria-label="Visuals timeline" role="group">
      <div className="relative h-2" aria-hidden="true">
        {suggestions.map((s) => (
          <span key={s.id} className="absolute top-0 h-2 rounded-sm bg-accent-soft/40" style={{ left: pct(s.start), width: pct(s.end - s.start) }} />
        ))}
      </div>
      {rows.map((row) => (
        <div key={row.label} className="flex items-center gap-2">
          <span className="w-14 shrink-0 text-[10px] text-subtle">{row.label}</span>
          <div className="relative h-7 min-w-0 flex-1 rounded-md bg-surface-3/60">
            {row.items.map((e) => (
              <button
                key={e.key}
                type="button"
                onClick={() => onSelect(e.key)}
                aria-pressed={selected === e.key}
                aria-label={`${MODE_LABELS[e.mode]}: ${assets.get(e.asset_id)?.display_name ?? "visual"}, ${formatSeconds(e.start_seconds)} to ${formatSeconds(e.end_seconds)}`}
                className={`absolute top-0.5 bottom-0.5 min-w-1.5 truncate rounded px-1 text-left text-[10px] font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent ${
                  e.mode === "cutaway" ? "bg-sky-500/70" : "bg-violet-500/70"
                } ${selected === e.key ? "ring-2 ring-white/80" : ""}`}
                style={{ left: pct(e.start_seconds), width: pct(e.end_seconds - e.start_seconds) }}
              >
                {assets.get(e.asset_id)?.display_name ?? ""}
              </button>
            ))}
            <span aria-hidden="true" className="absolute top-0 bottom-0 w-px bg-white/80" style={{ left: pct(time) }} />
          </div>
        </div>
      ))}
      <div className="flex justify-between pl-16 text-[10px] text-subtle tabular" aria-hidden="true">
        <span>0:00</span>
        <span>{formatSeconds(duration)}</span>
      </div>
    </div>
  );
}
