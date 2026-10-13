"use client";

import { type ReactNode, useCallback, useEffect, useState } from "react";
import { Clapperboard, Download, Smartphone } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/components/auth/auth-provider";
import { MediaFrame } from "@/components/ui/media-frame";
import { Button } from "@/components/ui/button";
import { buttonClasses } from "@/components/ui/button-styles";
import { ApiError, errorMessage } from "@/lib/api";
import {
  clipContentUrl,
  clipDownloadUrl,
  clipStageLabel,
  generateClip,
  getClip,
  isClipActive,
  retryClip,
  type GeneratedClip,
} from "@/lib/clips";
import type { ClipCandidate } from "@/lib/clip-detection";
import { editorHref } from "@/lib/edits";
import { formatBytes, formatDuration } from "@/lib/format";

const POLL_INTERVAL_MS = 4000;

type Props = {
  projectId: string;
  videoId: string;
  runId: string;
  candidate: ClipCandidate;
  /** The clip known from the page's listing; `undefined` means "not known, fetch it". */
  initialClip: GeneratedClip | null | undefined;
  onChange?: (clip: GeneratedClip) => void;
};

/**
 * Generate / status / retry for one candidate's rendered clip. Polls only while the
 * render is active, one timer per clip, cleared on unmount or when it finishes.
 */
export function ClipRenderControls({ projectId, videoId, runId, candidate, initialClip, onChange }: Props) {
  const { setUser } = useAuth();
  const [clip, setClip] = useState<GeneratedClip | null>(initialClip ?? null);
  const [known, setKnown] = useState(initialClip !== undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) setUser(null);
      return errorMessage(err);
    },
    [setUser],
  );

  const update = useCallback(
    (next: GeneratedClip) => {
      setClip(next);
      onChange?.(next);
    },
    [onChange],
  );

  // Recover the state from the API when the listing did not provide it.
  useEffect(() => {
    if (known) return;
    let cancelled = false;
    getClip(projectId, videoId, runId, candidate.id)
      .then((current) => {
        if (cancelled) return;
        setClip(current);
        setKnown(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(handleError(err));
        setKnown(true);
      });
    return () => {
      cancelled = true;
    };
  }, [known, projectId, videoId, runId, candidate.id, handleError]);

  const active = clip !== null && isClipActive(clip.status) && !clip.is_stale;
  const clipId = clip?.id ?? null;
  useEffect(() => {
    if (!active || clipId === null) return;
    const timer = window.setInterval(() => {
      getClip(projectId, videoId, runId, candidate.id)
        .then((current) => {
          if (current) update(current);
        })
        .catch((err: unknown) => setError(handleError(err)));
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [active, clipId, projectId, videoId, runId, candidate.id, update, handleError]);

  async function act(action: () => Promise<GeneratedClip>) {
    if (busy) return; // a second click while the first request is in flight does nothing
    setBusy(true);
    setError(null);
    try {
      update(await action());
    } catch (err) {
      setError(handleError(err));
    } finally {
      setBusy(false);
    }
  }

  const generate = () => act(() => generateClip(projectId, videoId, runId, candidate.id));
  const retry = () => act(() => retryClip(projectId, videoId, runId, candidate.id));
  const dismissed = candidate.decision === "dismissed";

  let body: ReactNode;
  if (!known) {
    body = <p className="text-sm text-muted">Checking clip…</p>;
  } else if (clip === null) {
    body = (
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted">
          {dismissed
            ? "Restore this candidate to generate a clip."
            : "Render this moment from the original video as an MP4."}
        </p>
        <Button onClick={generate} disabled={busy || dismissed}>
          {busy ? "Starting…" : "Generate clip"}
        </Button>
      </div>
    );
  } else if (isClipActive(clip.status) && clip.is_stale) {
    body = (
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p role="alert" className="text-sm text-amber-200">
          This render appears to have stalled — the worker stopped reporting.
        </p>
        <Button variant="secondary" onClick={retry} disabled={busy}>
          {busy ? "Restarting…" : "Retry render"}
        </Button>
      </div>
    );
  } else if (isClipActive(clip.status)) {
    body = (
      <div className="space-y-2">
        <p className="flex items-center gap-3 text-sm text-muted" role="status" aria-live="polite">
          <span
            aria-hidden="true"
            className="size-4 animate-spin rounded-full border-2 border-white/15 border-t-accent"
          />
          {clipStageLabel(clip)}
          {clip.progress_percent > 0 ? ` — ${clip.progress_percent}%` : ""}
        </p>
        {clip.progress_percent > 0 ? (
          <div
            role="progressbar"
            aria-label="Clip render progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={clip.progress_percent}
            className="h-1.5 overflow-hidden rounded-full bg-white/10"
          >
            <div className="h-full bg-accent transition-[width]" style={{ width: `${clip.progress_percent}%` }} />
          </div>
        ) : null}
      </div>
    );
  } else if (clip.status === "failed") {
    body = (
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div role="alert" className="min-w-0 text-sm text-rose-200">
          <p className="font-medium">Render failed</p>
          {clip.error_message ? <p className="mt-0.5 break-words">{clip.error_message}</p> : null}
        </div>
        <Button variant="secondary" onClick={retry} disabled={busy}>
          {busy ? "Retrying…" : "Retry render"}
        </Button>
      </div>
    );
  } else {
    body = <RenderedClip clip={clip} projectId={projectId} />;
  }

  return (
    <div className="mt-4 rounded-xl border border-border px-3 py-3 sm:px-4" aria-label="Generated clip">
      {body}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** The rendered clip: labelled player, the facts a creator needs, download and the next step. */
export function RenderedClip({ clip, projectId }: { clip: GeneratedClip; projectId: string }) {
  const meta = [
    formatDuration(clip.duration_seconds),
    clip.width && clip.height ? `${clip.width} × ${clip.height}` : null,
    clip.file_size != null ? formatBytes(clip.file_size) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="space-y-3">
      <MediaFrame icon={Clapperboard} label="Generated clip" meta={meta}>
        {/* The browser sends the HttpOnly session cookie (same-site); the API checks ownership. */}
        <video
          controls
          preload="metadata"
          src={clipContentUrl(clip.id)}
          className="aspect-video w-full bg-black object-contain"
          aria-label={`Rendered clip: ${clip.title}`}
        />
      </MediaFrame>
      <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
        <a
          href={clipDownloadUrl(clip.id)}
          className={buttonClasses("secondary", "md")}
          download
          aria-label={`Download MP4 — ${clip.title}`}
        >
          <Download aria-hidden="true" />
          Download MP4
        </a>
        <Link href={editorHref(projectId, clip.id)} className={buttonClasses("primary", "md")}>
          <Smartphone aria-hidden="true" />
          Create vertical short
        </Link>
      </div>
    </div>
  );
}
