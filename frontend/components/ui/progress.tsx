/** Determinate progress from real backend values only (never animated or estimated). */
export function ProgressBar({ value, label }: { value: number; label: string }) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
      className="h-1.5 overflow-hidden rounded-full bg-white/10"
    >
      <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${clamped}%` }} />
    </div>
  );
}

/** Small indeterminate spinner for "working" states. */
export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-white/15 border-t-accent ${className}`}
    />
  );
}

/** A live, labelled working state: spinner + specific words + optional real progress. */
export function WorkingState({
  label,
  detail,
  progress,
  progressLabel,
}: {
  label: string;
  detail?: string;
  progress?: number | null;
  progressLabel?: string;
}) {
  return (
    <div className="space-y-2.5">
      <p className="flex items-center gap-2.5 text-sm text-foreground" role="status" aria-live="polite">
        <Spinner />
        <span>
          {label}
          {progress != null && progress > 0 ? <span className="tabular text-muted"> · {progress}%</span> : null}
        </span>
      </p>
      {progress != null && progress > 0 ? (
        <ProgressBar value={progress} label={progressLabel ?? label} />
      ) : null}
      {detail ? <p className="text-xs text-subtle">{detail}</p> : null}
    </div>
  );
}
