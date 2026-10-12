"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ErrorState, LoadingState } from "@/components/app/states";
import { StatusBadge } from "@/components/app/status-badge";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { ApiError, errorMessage } from "@/lib/api";
import {
  detectionStageLabel,
  getRun,
  isDetectionActive,
  listProviders,
  listRuns,
  retryRun,
  startDetection,
  type DetectionRun,
  type ProviderOption,
} from "@/lib/clip-detection";
import { formatDate } from "@/lib/format";
import type { Transcription } from "@/lib/transcription";

const POLL_INTERVAL_MS = 4000;
const HISTORY_SIZE = 10;

type Props = {
  projectId: string;
  videoId: string;
  /** The video's transcription as known by the page; null when none exists yet. */
  transcription: Transcription | null;
  transcriptionLoaded: boolean;
  /** Rendered below a completed run (the candidate review, added separately). */
  renderResults?: (run: DetectionRun) => ReactNode;
};

const selectClasses =
  "h-11 w-full rounded-lg border border-border bg-white/[0.03] px-3.5 text-[15px] text-foreground outline-none transition-colors focus:border-accent/60 focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-60";

/** Provider + model choice from the server's allow-lists, then Start. */
function StartForm({
  providers,
  busy,
  onStart,
}: {
  providers: ProviderOption[];
  busy: boolean;
  onStart: (provider: string, model: string) => void;
}) {
  const usable = providers.filter((p) => p.configured && p.available !== false);
  const [provider, setProvider] = useState<string>(() => usable[0]?.name ?? providers[0]?.name ?? "");
  const current = providers.find((p) => p.name === provider) ?? null;
  const [model, setModel] = useState<string>(() => current?.default_model ?? "");
  const canStart = !!current && current.configured && current.available !== false && !!model;

  function choose(name: string) {
    setProvider(name);
    setModel(providers.find((p) => p.name === name)?.default_model ?? "");
  }

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (canStart) onStart(provider, model);
      }}
    >
      <p className="text-sm text-muted">
        Find the moments in this transcript worth clipping. The analysis runs in the
        background; results are ranked editorial suggestions, not performance predictions.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor="clip-provider" className="block text-sm font-medium text-foreground">
            AI provider
          </label>
          <select
            id="clip-provider"
            value={provider}
            onChange={(event) => choose(event.target.value)}
            disabled={busy}
            className={selectClasses}
          >
            {providers.map((p) => (
              <option key={p.name} value={p.name}>
                {p.label}
                {!p.configured || p.available === false ? " — unavailable" : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <label htmlFor="clip-model" className="block text-sm font-medium text-foreground">
            Model
          </label>
          <select
            id="clip-model"
            value={model}
            onChange={(event) => setModel(event.target.value)}
            disabled={busy || !current || current.models.length === 0}
            className={selectClasses}
          >
            {current && current.models.length > 0 ? (
              current.models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))
            ) : (
              <option value="">No models available</option>
            )}
          </select>
        </div>
      </div>
      {current && (!current.configured || current.available === false) ? (
        <p role="status" className="text-sm text-amber-200">
          {current.detail ?? "This provider is not available right now."}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button type="submit" disabled={busy || !canStart}>
          {busy ? "Starting…" : "Find clip moments"}
        </Button>
      </div>
    </form>
  );
}

function RunProgress({ run }: { run: DetectionRun }) {
  return (
    <div className="space-y-3">
      <p className="flex items-center gap-3 text-sm text-muted" role="status" aria-live="polite">
        <span
          aria-hidden="true"
          className="size-4 animate-spin rounded-full border-2 border-white/15 border-t-accent"
        />
        {detectionStageLabel(run)}
        {run.progress_percent > 0 ? ` — ${run.progress_percent}%` : ""}
      </p>
      {run.progress_percent > 0 ? (
        <div
          role="progressbar"
          aria-label="Clip detection progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={run.progress_percent}
          className="h-2 overflow-hidden rounded-full bg-white/10"
        >
          <div
            className="h-full bg-accent transition-[width]"
            style={{ width: `${run.progress_percent}%` }}
          />
        </div>
      ) : null}
      <p className="text-xs text-muted">
        {run.provider} / {run.model}
        {run.attempt > 1 ? ` · attempt ${run.attempt}` : ""}
      </p>
    </div>
  );
}

function RunHistory({
  runs,
  selectedId,
  onSelect,
}: {
  runs: DetectionRun[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (runs.length < 2) return null;
  return (
    <details className="rounded-xl border border-border">
      <summary className="cursor-pointer px-4 py-2.5 text-sm text-muted">
        Previous runs ({runs.length})
      </summary>
      <ul className="divide-y divide-border border-t border-border">
        {runs.map((run) => (
          <li key={run.id}>
            <button
              type="button"
              onClick={() => onSelect(run.id)}
              aria-current={run.id === selectedId ? "true" : undefined}
              className={`flex w-full flex-col gap-1 px-4 py-2.5 text-left text-sm hover:bg-white/[0.04] sm:flex-row sm:items-center sm:justify-between ${
                run.id === selectedId ? "bg-white/[0.04]" : ""
              }`}
            >
              <span className="min-w-0 truncate text-foreground">
                {run.provider} / {run.model}
                <span className="text-muted"> · {formatDate(run.created_at)}</span>
              </span>
              <span className="flex items-center gap-2 text-muted">
                {run.status === "completed" ? `${run.candidate_count} candidates` : null}
                <StatusBadge status={run.status} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** The AI Clip Detection section of a ready video. Polls only while a run is active. */
export function ClipDetectionPanel({
  projectId,
  videoId,
  transcription,
  transcriptionLoaded,
  renderResults,
}: Props) {
  const { setUser } = useAuth();
  const [providers, setProviders] = useState<ProviderOption[] | null>(null);
  const [runs, setRuns] = useState<DetectionRun[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [startingNew, setStartingNew] = useState(false);

  const handleError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) setUser(null);
      return errorMessage(err);
    },
    [setUser],
  );

  const transcriptReady = transcription?.status === "completed";

  // Initial load: provider options (probed once) and the run history.
  useEffect(() => {
    if (!transcriptReady) return;
    let cancelled = false;
    Promise.all([listProviders(true), listRuns(projectId, videoId, HISTORY_SIZE)])
      .then(([options, page]) => {
        if (cancelled) return;
        setProviders(options);
        setRuns(page.runs);
        setSelectedId(page.runs[0]?.id ?? null);
        setLoadError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(handleError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, videoId, transcriptReady, handleError]);

  const selected = runs?.find((run) => run.id === selectedId) ?? null;

  const replaceRun = useCallback((updated: DetectionRun) => {
    setRuns((previous) => {
      if (!previous) return [updated];
      const exists = previous.some((run) => run.id === updated.id);
      return exists
        ? previous.map((run) => (run.id === updated.id ? updated : run))
        : [updated, ...previous].slice(0, HISTORY_SIZE);
    });
  }, []);

  // Poll the selected run while it is active; the timer is cleared on unmount/completion.
  const active = selected !== null && isDetectionActive(selected.status);
  useEffect(() => {
    if (!active || !selected) return;
    const runId = selected.id;
    const timer = window.setInterval(() => {
      getRun(projectId, videoId, runId)
        .then(replaceRun)
        .catch((err: unknown) => setActionError(handleError(err)));
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [active, selected, projectId, videoId, replaceRun, handleError]);

  async function run(action: () => Promise<DetectionRun>) {
    setBusy(true);
    setActionError(null);
    try {
      const updated = await action();
      replaceRun(updated);
      setSelectedId(updated.id);
      setStartingNew(false);
    } catch (err) {
      setActionError(handleError(err));
    } finally {
      setBusy(false);
    }
  }

  const start = (provider: string, model: string) =>
    run(() => startDetection(projectId, videoId, provider, model));

  let body: ReactNode;
  if (!transcriptionLoaded) {
    body = <LoadingState label="Checking transcript…" />;
  } else if (!transcriptReady) {
    body = (
      <p className="text-sm text-muted">
        Clip detection reads the transcript, so transcribe the video first. The{" "}
        <strong className="font-medium text-foreground">Find clip moments</strong> button appears
        here once the transcript is ready.
      </p>
    );
  } else if (loadError) {
    body = <ErrorState message={loadError} onRetry={() => window.location.reload()} />;
  } else if (providers === null || runs === null) {
    body = <LoadingState label="Loading clip detection…" />;
  } else if (selected === null || startingNew) {
    body = (
      <div className="space-y-4">
        <StartForm providers={providers} busy={busy} onStart={start} />
        {startingNew ? (
          <div className="flex justify-end">
            <Button variant="secondary" onClick={() => setStartingNew(false)} disabled={busy}>
              Back to results
            </Button>
          </div>
        ) : null}
      </div>
    );
  } else if (isDetectionActive(selected.status) && selected.is_stale) {
    body = (
      <div className="space-y-4">
        <div
          role="alert"
          className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5 text-sm text-amber-100"
        >
          <p className="font-medium">This detection appears to have stalled</p>
          <p className="mt-1">The worker stopped reporting progress. You can start it again.</p>
        </div>
        <Button
          variant="secondary"
          onClick={() => run(() => retryRun(projectId, videoId, selected.id))}
          disabled={busy}
        >
          {busy ? "Restarting…" : "Retry detection"}
        </Button>
      </div>
    );
  } else if (isDetectionActive(selected.status)) {
    body = <RunProgress run={selected} />;
  } else if (selected.status === "failed") {
    body = (
      <div className="space-y-4">
        <div
          role="alert"
          className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3.5 py-2.5 text-sm text-rose-200"
        >
          <p className="font-medium">Clip detection failed</p>
          {selected.error_message ? <p className="mt-1">{selected.error_message}</p> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {selected.transcript_current ? (
            <Button
              variant="secondary"
              onClick={() => run(() => retryRun(projectId, videoId, selected.id))}
              disabled={busy}
            >
              {busy ? "Retrying…" : "Retry detection"}
            </Button>
          ) : null}
          <Button onClick={() => setStartingNew(true)} disabled={busy}>
            Start a new detection
          </Button>
        </div>
      </div>
    );
  } else {
    body = (
      <div className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted">
            {selected.candidate_count} candidate{selected.candidate_count === 1 ? "" : "s"} ·{" "}
            {selected.provider} / {selected.model}
            {selected.completed_at ? ` · ${formatDate(selected.completed_at)}` : ""}
          </p>
          <Button variant="secondary" onClick={() => setStartingNew(true)} disabled={busy}>
            Run again
          </Button>
        </div>
        {!selected.transcript_current ? (
          <p
            role="status"
            className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5 text-sm text-amber-100"
          >
            The transcript has changed since these candidates were generated. Run the detection
            again for suggestions that match the current transcript.
          </p>
        ) : null}
        {renderResults ? renderResults(selected) : null}
      </div>
    );
  }

  return (
    <section aria-labelledby="clip-detection-heading" className="mt-6 border-t border-border pt-5">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h3 id="clip-detection-heading" className="font-medium">
          AI clip detection
        </h3>
        {selected ? <StatusBadge status={selected.status} /> : null}
      </div>

      {body}

      {runs && runs.length > 1 ? (
        <div className="mt-4">
          <RunHistory
            runs={runs}
            selectedId={selectedId}
            onSelect={(id) => {
              setSelectedId(id);
              setStartingNew(false);
            }}
          />
        </div>
      ) : null}

      <div className="mt-3">
        <FormError>{actionError}</FormError>
      </div>
    </section>
  );
}
