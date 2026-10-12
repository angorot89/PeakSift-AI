"use client";

import { useCallback, useEffect, useState } from "react";
import { ErrorState, LoadingState } from "@/components/app/states";
import { StatusBadge } from "@/components/app/status-badge";
import { TranscriptViewer } from "@/components/app/transcript-viewer";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { ApiError, errorMessage } from "@/lib/api";
import {
  getTranscription,
  isActive,
  retryTranscription,
  startTranscription,
  type Transcription,
} from "@/lib/transcription";

const POLL_INTERVAL_MS = 4000;

type Props = { projectId: string; videoId: string };

function statusCopy(transcription: Transcription): string {
  switch (transcription.status) {
    case "queued":
      return "Queued — waiting for a worker";
    case "extracting_audio":
      return "Preparing audio";
    case "transcribing":
      return transcription.progress_percent > 0
        ? `Transcribing — ${transcription.progress_percent}%`
        : "Transcribing";
    case "completed":
      return "Transcript ready";
    case "failed":
      return "Transcription failed";
  }
}

/** Start / status / retry / transcript for a ready video. Polls while a job is active. */
export function TranscriptionPanel({ projectId, videoId }: Props) {
  const { setUser } = useAuth();
  const [transcription, setTranscription] = useState<Transcription | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) setUser(null);
      return errorMessage(err);
    },
    [setUser],
  );

  const refresh = useCallback(() => {
    return getTranscription(projectId, videoId)
      .then((current) => {
        setTranscription(current);
        setLoadError(null);
        setLoaded(true);
      })
      .catch((err: unknown) => {
        setLoadError(handleError(err));
        setLoaded(true);
      });
  }, [projectId, videoId, handleError]);

  // Initial load.
  useEffect(() => {
    let cancelled = false;
    getTranscription(projectId, videoId)
      .then((current) => {
        if (cancelled) return;
        setTranscription(current);
        setLoaded(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(handleError(err));
        setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, videoId, handleError]);

  // Poll only while a job is in flight; the timer is cleared on unmount or completion.
  const active = transcription !== null && isActive(transcription.status);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [active, refresh]);

  async function run(action: () => Promise<Transcription>) {
    setBusy(true);
    setActionError(null);
    try {
      setTranscription(await action());
    } catch (err) {
      setActionError(handleError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="transcription-heading" className="mt-6 border-t border-border pt-5">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h3 id="transcription-heading" className="font-medium">
          Transcription
        </h3>
        {transcription ? <StatusBadge status={transcription.status} /> : null}
      </div>

      {!loaded ? (
        <LoadingState label="Checking transcription…" />
      ) : loadError ? (
        <ErrorState message={loadError} onRetry={() => void refresh()} />
      ) : transcription === null ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted">
            Turn the speech in this video into a timestamped transcript. It runs in the
            background and can take a while for long recordings.
          </p>
          <Button onClick={() => run(() => startTranscription(projectId, videoId))} disabled={busy}>
            {busy ? "Starting…" : "Transcribe video"}
          </Button>
        </div>
      ) : isActive(transcription.status) && transcription.is_stale ? (
        <div className="space-y-4">
          <div
            role="alert"
            className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5 text-sm text-amber-100"
          >
            <p className="font-medium">This transcription appears to have stalled</p>
            <p className="mt-1">The worker stopped reporting progress. You can start it again.</p>
          </div>
          <Button
            variant="secondary"
            onClick={() => run(() => retryTranscription(projectId, videoId))}
            disabled={busy}
          >
            {busy ? "Restarting…" : "Retry transcription"}
          </Button>
        </div>
      ) : isActive(transcription.status) ? (
        <div className="space-y-3">
          <p className="flex items-center gap-3 text-sm text-muted" role="status" aria-live="polite">
            <span
              aria-hidden="true"
              className="size-4 animate-spin rounded-full border-2 border-white/15 border-t-accent"
            />
            {statusCopy(transcription)}
          </p>
          {transcription.status === "transcribing" && transcription.progress_percent > 0 ? (
            <div
              role="progressbar"
              aria-label="Transcription progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={transcription.progress_percent}
              className="h-2 overflow-hidden rounded-full bg-white/10"
            >
              <div
                className="h-full bg-accent transition-[width]"
                style={{ width: `${transcription.progress_percent}%` }}
              />
            </div>
          ) : null}
        </div>
      ) : transcription.status === "failed" ? (
        <div className="space-y-4">
          <div
            role="alert"
            className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3.5 py-2.5 text-sm text-rose-200"
          >
            <p className="font-medium">Transcription failed</p>
            {transcription.error_message ? <p className="mt-1">{transcription.error_message}</p> : null}
          </div>
          <Button
            variant="secondary"
            onClick={() => run(() => retryTranscription(projectId, videoId))}
            disabled={busy}
          >
            {busy ? "Retrying…" : "Retry transcription"}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted">
            {transcription.segment_count} segments
            {transcription.language ? ` · language: ${transcription.language}` : ""} · {transcription.provider}
            {" / "}
            {transcription.model}
          </p>
          <TranscriptViewer projectId={projectId} videoId={videoId} total={transcription.segment_count} />
          <p className="text-sm text-muted">AI clip detection comes in Milestone 4.</p>
        </div>
      )}

      <FormError>{actionError}</FormError>
    </section>
  );
}
