"use client";

import { AlertTriangle, CheckCircle2, Crosshair, ScanFace, Users } from "lucide-react";
import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { WorkingState } from "@/components/ui/progress";
import {
  analysisErrorCopy,
  analysisStageLabel,
  clampedCenter,
  confidenceCopy,
  cropGeometry,
  isAnalysisActive,
  type ReframeAnalysis,
} from "@/lib/reframe";

export type FramingMode = "auto" | "manual";

/** Automatic (face tracking) vs manual focal point — a real radio group. */
function ModeSwitch({ mode, onChange, name }: { mode: FramingMode; onChange: (m: FramingMode) => void; name: string }) {
  const options: Array<{ value: FramingMode; label: string }> = [
    { value: "auto", label: "Automatic" },
    { value: "manual", label: "Focal point" },
  ];
  return (
    <fieldset className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-surface-2 p-0.5">
      <legend className="sr-only">Framing mode</legend>
      {options.map((option) => (
        <label
          key={option.value}
          className={`flex h-8 cursor-pointer items-center justify-center gap-1.5 rounded-md text-small font-medium transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
            mode === option.value ? "bg-surface-3 text-foreground shadow-sm" : "text-muted hover:text-foreground"
          }`}
        >
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={mode === option.value}
            onChange={() => onChange(option.value)}
            className="sr-only"
          />
          {option.value === "auto" ? <ScanFace aria-hidden="true" className="size-3.5" /> : <Crosshair aria-hidden="true" className="size-3.5" />}
          {option.label}
        </label>
      ))}
    </fieldset>
  );
}

function AnalysisSummary({ analysis }: { analysis: ReframeAnalysis }) {
  const copy = confidenceCopy(analysis.confidence_level);
  const level = analysis.confidence_level;
  const Icon = level === "high" ? CheckCircle2 : level === "mixed" ? Users : AlertTriangle;
  const tone = level === "high" ? "text-success" : level === "mixed" ? "text-accent-soft" : "text-warning";
  const fallback = Math.round((analysis.fallback_fraction ?? 0) * 100);
  const faces = analysis.tracks_count ?? 0;
  return (
    <div className="space-y-2 rounded-xl border border-border bg-surface-2 p-3.5" role="status">
      <p className="flex items-center gap-2 text-sm font-medium text-foreground">
        <CheckCircle2 aria-hidden="true" className={`size-4 ${level === "fallback" ? "text-subtle" : "text-success"}`} />
        {level === "fallback" ? "Framing analyzed" : "Smart framing ready"}
      </p>
      <p className="flex items-start gap-2 text-sm">
        <Icon aria-hidden="true" className={`mt-0.5 size-4 shrink-0 ${tone}`} />
        <span>
          <span className="font-medium text-foreground">{copy.label}</span>
          <span className="block text-xs text-subtle">{copy.hint}</span>
        </span>
      </p>
      <p className="tabular text-xs text-subtle">
        {faces === 0 ? "No faces found" : `${faces} face track${faces === 1 ? "" : "s"}`}
        {` · ${fallback}% centered fallback`}
      </p>
    </div>
  );
}

/**
 * The full source frame with the 9:16 crop outlined. Click/tap or drag to choose what stays
 * in frame; arrow keys (Shift for bigger steps) and the sliders do the same without a pointer.
 */
export function FocalPointPicker({
  posterSrc,
  sourceWidth,
  sourceHeight,
  focusX,
  focusY,
  onChange,
}: {
  posterSrc: string;
  sourceWidth: number;
  sourceHeight: number;
  focusX: number;
  focusY: number;
  onChange: (x: number, y: number) => void;
}) {
  const area = useRef<HTMLDivElement>(null);
  const geometry = cropGeometry(sourceWidth, sourceHeight);
  const center = clampedCenter(sourceWidth, sourceHeight, focusX, focusY);
  const clamp = (v: number) => Math.min(1, Math.max(0, Math.round(v * 1000) / 1000));

  function fromPointer(event: PointerEvent<HTMLDivElement>) {
    const rect = area.current?.getBoundingClientRect();
    if (!rect) return;
    onChange(clamp((event.clientX - rect.left) / rect.width), clamp((event.clientY - rect.top) / rect.height));
  }

  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey ? 0.1 : 0.02;
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0],
      ArrowRight: [step, 0],
      ArrowUp: [0, -step],
      ArrowDown: [0, step],
    };
    const move = moves[event.key];
    if (!move) return;
    event.preventDefault();
    onChange(clamp(focusX + move[0]), clamp(focusY + move[1]));
  }

  if (geometry.axis === null) {
    return <p className="text-xs text-subtle">This clip is already vertical, so the whole frame is used.</p>;
  }
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  return (
    <div className="space-y-3">
      <div
        ref={area}
        role="group"
        tabIndex={0}
        aria-label={`Focal point ${pct(focusX)} from the left, ${pct(focusY)} from the top. Use arrow keys to move it.`}
        onKeyDown={onKey}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          fromPointer(event);
        }}
        onPointerMove={(event) => {
          if (event.buttons === 1) fromPointer(event);
        }}
        className="relative w-full cursor-crosshair touch-none overflow-hidden rounded-lg border border-border bg-black select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        style={{ aspectRatio: `${sourceWidth} / ${sourceHeight}` }}
      >
        <video
          aria-hidden="true"
          tabIndex={-1}
          muted
          playsInline
          preload="metadata"
          src={`${posterSrc}#t=1`}
          className="pointer-events-none absolute inset-0 size-full object-cover"
        />
        {/* Outside the crop is dimmed; the crop itself is outlined. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 rounded-sm border-2 border-accent shadow-[0_0_0_9999px_rgb(0_0_0/0.55)] transition-[left,top] duration-150 motion-reduce:transition-none"
          style={
            geometry.axis === "x"
              ? { left: `${(center.x - geometry.cropWidth / 2) * 100}%`, width: `${geometry.cropWidth * 100}%` }
              : { top: `${(center.y - geometry.cropHeight / 2) * 100}%`, height: `${geometry.cropHeight * 100}%`, left: 0, right: 0 }
          }
        />
        <span
          aria-hidden="true"
          className="pointer-events-none absolute size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-accent shadow"
          style={{ left: `${focusX * 100}%`, top: `${focusY * 100}%` }}
        />
      </div>
      <label className="block space-y-1">
        <span className="flex justify-between text-xs text-muted">
          <span>{geometry.axis === "x" ? "Horizontal position" : "Vertical position"}</span>
          <span className="tabular text-subtle">{pct(geometry.axis === "x" ? focusX : focusY)}</span>
        </span>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={Math.round((geometry.axis === "x" ? focusX : focusY) * 100)}
          onChange={(e) => {
            const v = Number(e.target.value) / 100;
            if (geometry.axis === "x") onChange(v, focusY);
            else onChange(focusX, v);
          }}
          className="w-full cursor-pointer accent-[var(--accent)]"
        />
      </label>
    </div>
  );
}

type PanelProps = {
  name: string;
  mode: FramingMode;
  onModeChange: (mode: FramingMode) => void;
  analysis: ReframeAnalysis | null | undefined;
  busy: boolean;
  onAnalyze: () => void;
  onRetry: () => void;
  posterSrc: string;
  sourceWidth: number;
  sourceHeight: number;
  focusX: number;
  focusY: number;
  onFocusChange: (x: number, y: number) => void;
};

/** Everything Smart reframe needs, in plain language: analysis state, confidence, manual fallback. */
export function SmartReframePanel(props: PanelProps) {
  const { analysis, mode } = props;
  let body;
  if (mode === "manual") {
    body = (
      <div className="space-y-3">
        <p className="text-xs text-muted">Click or tap the frame to choose what stays in view. The crop stays fixed on that point.</p>
        <FocalPointPicker
          posterSrc={props.posterSrc}
          sourceWidth={props.sourceWidth}
          sourceHeight={props.sourceHeight}
          focusX={props.focusX}
          focusY={props.focusY}
          onChange={props.onFocusChange}
        />
      </div>
    );
  } else if (analysis === undefined) {
    body = <WorkingState label="Checking framing analysis" />;
  } else if (analysis === null) {
    body = (
      <div className="space-y-3 rounded-xl border border-dashed border-border-strong p-3.5">
        <p className="text-sm text-muted">
          PeakSift finds the faces in this clip and plans a smooth vertical camera path that keeps them in frame.
        </p>
        <Button className="w-full" onClick={props.onAnalyze} disabled={props.busy}>
          <ScanFace aria-hidden="true" />
          {props.busy ? "Starting…" : "Analyze framing"}
        </Button>
      </div>
    );
  } else if (analysis.status === "failed" || (isAnalysisActive(analysis.status) && analysis.is_stale)) {
    body = (
      <div className="space-y-2">
        <InlineAlert tone={analysis.status === "failed" ? "danger" : "warning"} title={analysis.status === "failed" ? "Framing analysis failed" : "Framing analysis stalled"}>
          {analysis.status === "failed" ? analysisErrorCopy(analysis) : "The analysis stopped responding."}
        </InlineAlert>
        <div className="grid grid-cols-2 gap-2">
          <Button variant="secondary" onClick={props.onRetry} disabled={props.busy}>
            {props.busy ? "Retrying…" : "Retry"}
          </Button>
          <Button variant="ghost" onClick={() => props.onModeChange("manual")}>
            <Crosshair aria-hidden="true" />
            Set focal point
          </Button>
        </div>
      </div>
    );
  } else if (isAnalysisActive(analysis.status)) {
    body = (
      <div className="rounded-xl border border-border bg-surface-2 p-3.5">
        <WorkingState
          label={`Analyzing framing · ${analysisStageLabel(analysis)}`}
          progress={analysis.status === "queued" ? null : analysis.progress_percent}
          progressLabel="Framing analysis progress"
          detail="Runs in the background. Captions can be set meanwhile."
        />
      </div>
    );
  } else {
    body = (
      <div className="space-y-2">
        <AnalysisSummary analysis={analysis} />
        {analysis.confidence_level === "fallback" ? (
          <Button variant="secondary" className="w-full" onClick={() => props.onModeChange("manual")}>
            <Crosshair aria-hidden="true" />
            Set a focal point instead
          </Button>
        ) : null}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <ModeSwitch mode={mode} onChange={props.onModeChange} name={props.name} />
      {body}
    </div>
  );
}
