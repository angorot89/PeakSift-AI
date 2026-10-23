"use client";

import { RotateCcw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/app/states";
import { StatusBadge } from "@/components/app/status-badge";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Panel } from "@/components/ui/panel";
import { WorkingState } from "@/components/ui/progress";
import { selectClasses } from "@/components/ui/select-styles";
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
        PeakSift reads the transcript and ranks the moments worth clipping. Rankings are editorial
        suggestions, not predictions of views.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor="clip-provider" className="block text-sm font-medium text-foreground">
            AI service
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
          <Sparkles aria-hidden="true" />
          {busy ? "Starting…" : "Find moments"}
        </Button>
      </div>
    </form>
  );
}

function RunProgress({ run }: { run: DetectionRun }) {
  return (
    <WorkingState
      label={detectionStageLabel(run)}
      progress={run.progress_percent}
      progressLabel="Finding moments progress"
      detail="Reading the transcript and ranking moments. You can leave this page; it keeps going."
    />
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
      <summary className="cursor-pointer px-4 py-2.5 text-sm text-muted transition-colors hover:text-foreground">
        Earlier searches ({runs.length})
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
                {run.model}
                <span className="text-muted"> · {formatDate(run.created_at)}</span>
              </span>
              <span className="flex items-center gap-2 text-muted">
                {run.status === "completed" ? `${run.candidate_count} ${run.candidate_count === 1 ? "moment" : "moments"}` : null}
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
  const [loadVersion, setLoadVersion] = useState(0);

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
  }, [projectId, videoId, transcriptReady, handleError, loadVersion]);

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
    body = <LoadingState label="Checking the transcript…" />;
  } else if (!transcriptReady) {
    body = (
      <EmptyState
        compact
        icon={Sparkles}
        title="Waiting for the transcript"
        description="Transcribe the source video before PeakSift can analyze moments."
      />
    );
  } else if (loadError) {
    body = (
      <ErrorState
        title="Finding moments is unavailable"
        message={loadError}
        onRetry={() => {
          setLoadError(null);
          setLoadVersion((v) => v + 1);
        }}
      />
    );
  } else if (providers === null || runs === null) {
    body = <LoadingState label="Loading moments…" />;
  } else if (selected === null || startingNew) {
    body = (
      <div className="space-y-4">
        <StartForm providers={providers} busy={busy} onStart={start} />
        {startingNew ? (
          <div className="flex justify-end">
            <Button variant="ghost" size="sm" onClick={() => setStartingNew(false)} disabled={busy}>
              Back to results
            </Button>
          </div>
        ) : null}
      </div>
    );
  } else if (isDetectionActive(selected.status) && selected.is_stale) {
    body = (
      <InlineAlert
        tone="warning"
        title="Finding moments stalled"
        action={
          <Button variant="secondary" size="sm" onClick={() => run(() => retryRun(projectId, videoId, selected.id))} disabled={busy}>
            {busy ? "Restarting…" : "Try again"}
          </Button>
        }
      >
        The search stopped responding. Start it again to continue.
      </InlineAlert>
    );
  } else if (isDetectionActive(selected.status)) {
    body = <RunProgress run={selected} />;
  } else if (selected.status === "failed") {
    body = (
      <InlineAlert
        title="Finding moments failed"
        action={
          <div className="flex flex-wrap gap-2">
            {selected.transcript_current !== false ? (
              <Button variant="secondary" size="sm" onClick={() => run(() => retryRun(projectId, videoId, selected.id))} disabled={busy}>
                {busy ? "Retrying…" : "Try again"}
              </Button>
            ) : null}
            <Button size="sm" onClick={() => setStartingNew(true)} disabled={busy}>
              Start a new search
            </Button>
          </div>
        }
      >
        {selected.error_message ?? "The analysis could not be completed."}
      </InlineAlert>
    );
  } else {
    body = (
      <div className="space-y-4">
        {selected.transcript_current === false ? (
          <InlineAlert tone="warning" title="The transcript changed">
            These moments come from an earlier transcript. Find moments again for ones that match
            the current one.
          </InlineAlert>
        ) : null}
        {renderResults ? renderResults(selected) : null}
      </div>
    );
  }

  const completed = selected && selected.status === "completed" && !startingNew ? selected : null;
  return (
    <Panel
      id="clips"
     
      title="Moments"
      description={
        completed
          ? `${completed.candidate_count} ${completed.candidate_count === 1 ? "moment" : "moments"} found${
              completed.completed_at ? ` · ${formatDate(completed.completed_at)}` : ""
            }`
          : "PeakSift reads the transcript and ranks the moments worth clipping."
      }
      status={selected && !startingNew ? <StatusBadge status={selected.status} stale={isDetectionActive(selected.status) && selected.is_stale} /> : undefined}
      actions={
        completed ? (
          <Button variant="ghost" size="sm" onClick={() => setStartingNew(true)} disabled={busy}>
            <RotateCcw aria-hidden="true" />
            Find again
          </Button>
        ) : undefined
      }
    >
      {body}

      {runs && runs.length > 1 ? (
        <div className="mt-5">
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

      {actionError ? (
        <div className="mt-3">
          <FormError>{actionError}</FormError>
        </div>
      ) : null}
    </Panel>
  );
}
