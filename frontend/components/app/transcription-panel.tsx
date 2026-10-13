"use client";

import { FileText } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { useWorkflowReport, type StepState } from "@/components/app/project-workflow";
import { EmptyState, ErrorState, LoadingState } from "@/components/app/states";
import { StatusBadge } from "@/components/app/status-badge";
import { TranscriptViewer } from "@/components/app/transcript-viewer";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Panel } from "@/components/ui/panel";
import { WorkingState } from "@/components/ui/progress";
import { ApiError, errorMessage } from "@/lib/api";
import {
  getTranscription,
  isActive,
  retryTranscription,
  startTranscription,
  type Transcription,
} from "@/lib/transcription";

const POLL_INTERVAL_MS = 4000;

type Props = {
  projectId: string;
  videoId: string;
  /** Lets the page share the transcription state with sibling sections (clip detection). */
  onTranscriptionChange?: (transcription: Transcription | null, loaded: boolean) => void;
};

function statusCopy(transcription: Transcription): string {
  switch (transcription.status) {
    case "queued":
      return "Queued — waiting for a worker";
    case "extracting_audio":
      return "Preparing audio";
    case "transcribing":
      return "Transcribing";
    case "completed":
      return "Transcript ready";
    case "failed":
      return "Transcription failed";
  }
}

/** Start / status / retry / transcript for a ready video. Polls while a job is active. */
export function TranscriptionPanel({ projectId, videoId, onTranscriptionChange }: Props) {
  const { setUser } = useAuth();
  const [transcription, setTranscription] = useState<Transcription | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    onTranscriptionChange?.(transcription, loaded);
  }, [transcription, loaded, onTranscriptionChange]);
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

  const stepState: StepState = !loaded
    ? "unknown"
    : transcription === null
      ? "todo"
      : transcription.status === "completed"
        ? "done"
        : transcription.status === "failed" || transcription.is_stale
          ? "failed"
          : "active";
  useWorkflowReport("transcribe", stepState);

  let body: ReactNode;
  if (!loaded) {
    body = <LoadingState label="Checking the transcript…" />;
  } else if (loadError) {
    body = <ErrorState title="Transcript status unavailable" message={loadError} onRetry={() => void refresh()} />;
  } else if (transcription === null) {
    body = (
      <EmptyState
        compact
        icon={FileText}
        title="No transcript yet"
        description="Transcribe the source video before PeakSift can analyze moments. It runs in the background."
        action={
          <Button onClick={() => run(() => startTranscription(projectId, videoId))} disabled={busy}>
            <FileText aria-hidden="true" />
            {busy ? "Starting…" : "Transcribe video"}
          </Button>
        }
      />
    );
  } else if (isActive(transcription.status) && transcription.is_stale) {
    body = (
      <InlineAlert
        tone="warning"
        title="Transcription stalled"
        action={
          <Button variant="secondary" size="sm" onClick={() => run(() => retryTranscription(projectId, videoId))} disabled={busy}>
            {busy ? "Restarting…" : "Retry transcription"}
          </Button>
        }
      >
        The worker stopped reporting progress. Start it again to continue.
      </InlineAlert>
    );
  } else if (isActive(transcription.status)) {
    body = (
      <WorkingState
        label={statusCopy(transcription)}
        progress={transcription.status === "transcribing" ? transcription.progress_percent : null}
        progressLabel="Transcription progress"
        detail="Long recordings can take a while. You can leave this page; it keeps running."
      />
    );
  } else if (transcription.status === "failed") {
    body = (
      <InlineAlert
        title="Transcription failed"
        action={
          <Button variant="secondary" size="sm" onClick={() => run(() => retryTranscription(projectId, videoId))} disabled={busy}>
            {busy ? "Retrying…" : "Retry transcription"}
          </Button>
        }
      >
        {transcription.error_message ?? "The speech could not be transcribed."}
      </InlineAlert>
    );
  } else {
    body = (
      <TranscriptViewer
        projectId={projectId}
        videoId={videoId}
        total={transcription.segment_count}
        footnote={`Transcribed with ${transcription.provider} · ${transcription.model}`}
      />
    );
  }

  const description =
    transcription?.status === "completed"
      ? `${transcription.segment_count} segment${transcription.segment_count === 1 ? "" : "s"}${
          transcription.language ? ` · ${languageName(transcription.language)}` : ""
        }`
      : "A timestamped transcript of everything said in the video.";

  return (
    <Panel
      id="transcript"
      step="2"
      title="Transcript"
      description={description}
      status={transcription ? <StatusBadge status={transcription.status} stale={isActive(transcription.status) && transcription.is_stale} /> : undefined}
    >
      {body}
      {actionError ? (
        <div className="mt-3">
          <FormError>{actionError}</FormError>
        </div>
      ) : null}
    </Panel>
  );
}

const languageNames = typeof Intl !== "undefined" && "DisplayNames" in Intl ? new Intl.DisplayNames(["en"], { type: "language" }) : null;

function languageName(code: string): string {
  try {
    return languageNames?.of(code) ?? code;
  } catch {
    return code;
  }
}
