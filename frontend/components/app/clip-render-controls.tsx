"use client";

import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Clapperboard, Download, Smartphone } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/components/auth/auth-provider";
import { MediaFrame } from "@/components/ui/media-frame";
import { LoadingState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { WorkingState } from "@/components/ui/progress";
import { buttonClasses } from "@/components/ui/button-styles";
import { ApiError, errorMessage } from "@/lib/api";
import {
  CLIP_STAGES,
  clipContentUrl,
  clipDownloadUrl,
  clipStageLabel,
  friendlyClipError,
  generateClip,
  getClip,
  isClipActive,
  retryClip,
  type GeneratedClip,
} from "@/lib/clips";
import type { ClipCandidate } from "@/lib/clip-detection";
import { editorHref } from "@/lib/edits";
import { formatBytes, formatDuration } from "@/lib/format";
import { newer } from "@/lib/status-sync";
import { usePolling } from "@/lib/use-polling";

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
 * render is active (first check after about a second: fast renders finish that quickly),
 * one timer per clip, cleared on unmount or when it finishes. Responses older than the state
 * on screen (e.g. a poll that started before Retry) are ignored.
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

  // The clip on screen, read by `update` to drop out-of-order responses.
  const clipRef = useRef(clip);
  const update = useCallback(
    (next: GeneratedClip) => {
      if (newer(clipRef.current, next, CLIP_STAGES) !== next) return; // a stale response
      clipRef.current = next;
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
        if (current) update(current);
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
  }, [known, projectId, videoId, runId, candidate.id, handleError, update]);

  const active = clip !== null && isClipActive(clip.status) && !clip.is_stale;
  const clipId = clip?.id ?? null;
  usePolling(
    active && clipId !== null,
    async () => {
      try {
        const current = await getClip(projectId, videoId, runId, candidate.id);
        if (current) update(current);
      } catch (err) {
        setError(handleError(err));
      }
    },
    clipId,
  );

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
    body = <LoadingState label="Checking clip…" />;
  } else if (clip === null) {
    body = (
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted">
          {dismissed
            ? "Restore this candidate to generate a clip."
            : "Render this moment from the original video as an MP4."}
        </p>
        <Button onClick={generate} disabled={busy || dismissed}>
          <Clapperboard aria-hidden="true" />
          {busy ? "Starting…" : "Generate clip"}
        </Button>
      </div>
    );
  } else if (isClipActive(clip.status) && clip.is_stale) {
    body = (
      <InlineAlert
        tone="warning"
        title="Clip render stalled"
        action={
          <Button variant="secondary" size="sm" onClick={retry} disabled={busy}>
            {busy ? "Restarting…" : "Retry render"}
          </Button>
        }
      >
        The worker stopped reporting progress. Start it again to continue.
      </InlineAlert>
    );
  } else if (isClipActive(clip.status)) {
    body = (
      <WorkingState
        label={clipStageLabel(clip).replace("…", "")}
        progress={clip.status === "queued" ? null : clip.progress_percent}
        progressLabel="Clip render progress"
        detail="Rendering clip from the original video."
      />
    );
  } else if (clip.status === "failed") {
    body = (
      <InlineAlert
        title="Render failed"
        action={
          <Button variant="secondary" size="sm" onClick={retry} disabled={busy}>
            {busy ? "Retrying…" : "Retry render"}
          </Button>
        }
      >
        We couldn&apos;t render this clip.
        <span className="block text-xs text-subtle">{friendlyClipError(clip)}</span>
      </InlineAlert>
    );
  } else {
    body = <RenderedClip clip={clip} projectId={projectId} />;
  }

  return (
    <div className="mt-4 border-t border-border pt-4" aria-label="Generated clip" role="group">
      {body}
      {error ? (
        <div className="mt-3">
          <InlineAlert title="That didn't work">{error}</InlineAlert>
        </div>
      ) : null}
    </div>
  );
}

/** The rendered clip: a compact labelled player beside what a creator needs next. */
export function RenderedClip({ clip, projectId }: { clip: GeneratedClip; projectId: string }) {
  const meta = [
    formatDuration(clip.duration_seconds),
    clip.width && clip.height ? `${clip.width} × ${clip.height}` : null,
    clip.file_size != null ? formatBytes(clip.file_size) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="grid items-start gap-4 sm:grid-cols-[minmax(0,420px)_1fr] sm:gap-6">
      <MediaFrame icon={Clapperboard} label="Generated clip">
        {/* The browser sends the HttpOnly session cookie (same-site); the API checks ownership. */}
        <video
          controls
          preload="metadata"
          src={`${clipContentUrl(clip.id)}#t=0.1`}
          className="aspect-video w-full bg-black object-contain"
          aria-label={`Rendered clip: ${clip.title}`}
        />
      </MediaFrame>
      <div className="flex min-w-0 flex-col gap-3 sm:pt-6">
        <div>
          <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
            <CheckCircle2 aria-hidden="true" className="size-4 text-success" />
            Clip ready
          </p>
          <p className="tabular mt-0.5 text-xs text-subtle">{meta} · original aspect ratio</p>
        </div>
        <p className="text-sm text-muted">Make a 9:16 version with captions for Shorts, TikTok and Reels.</p>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Link href={editorHref(projectId, clip.id)} className={buttonClasses("primary", "md")}>
            <Smartphone aria-hidden="true" />
            Create vertical short
          </Link>
          <a
            href={clipDownloadUrl(clip.id)}
            className={buttonClasses("secondary", "md")}
            download
            aria-label={`Download MP4 — ${clip.title}`}
          >
            <Download aria-hidden="true" />
            Download MP4
          </a>
        </div>
      </div>
    </div>
  );
}
