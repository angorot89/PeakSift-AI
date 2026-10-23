"use client";

import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Clapperboard, Download, MoreHorizontal, RotateCcw, Wand2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Menu, type MenuItem } from "@/components/ui/menu";
import { ButtonLink } from "@/components/ui/button-link";
import { WorkingState } from "@/components/ui/progress";
import { ApiError, errorMessage } from "@/lib/api";
import {
  CLIP_STAGES,
  clipDownloadUrl,
  friendlyClipError,
  generateClip,
  getClip,
  isClipActive,
  retryClip,
  type GeneratedClip,
} from "@/lib/clips";
import type { ClipCandidate } from "@/lib/clip-detection";
import { createHref } from "@/lib/edits";
import { formatDuration } from "@/lib/format";
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
  /** The card's other actions (preview, save, dismiss), shown in one row after Create Short. */
  secondary?: ReactNode;
};

/**
 * Generate / status / retry for one candidate's rendered clip. Polls only while the
 * render is active (first check after about a second: fast renders finish that quickly),
 * one timer per clip, cleared on unmount or when it finishes. Responses older than the state
 * on screen (e.g. a poll that started before Retry) are ignored.
 */
export function ClipRenderControls({ projectId, videoId, runId, candidate, initialClip, onChange, secondary }: Props) {
  const { setUser } = useAuth();
  const router = useRouter();
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

  async function act(action: () => Promise<GeneratedClip>, then?: (clip: GeneratedClip) => void) {
    if (busy) return; // a second click while the first request is in flight does nothing
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      update(next);
      then?.(next);
    } catch (err) {
      setError(handleError(err));
    } finally {
      setBusy(false);
    }
  }

  const generate = () => act(() => generateClip(projectId, videoId, runId, candidate.id));
  // Cutting the clip starts at once; the next step shows its progress and opens when it is ready.
  const createShort = () =>
    act(
      () => generateClip(projectId, videoId, runId, candidate.id),
      (next) => router.push(createHref(projectId, next.id)),
    );
  const retry = () => act(() => retryClip(projectId, videoId, runId, candidate.id));
  const dismissed = candidate.decision === "dismissed";

  // One action row in every state: Create Short first, the card's own actions after it, and the
  // rarely needed ones in a menu.
  let primary: ReactNode;
  let cutOnly = false;
  let downloadUrl: string | null = null;
  let status: ReactNode = null;
  if (!known) {
    primary = (
      <Button size="sm" disabled>
        <Wand2 aria-hidden="true" />
        Create Short
      </Button>
    );
  } else if (clip === null) {
    primary = (
      <Button size="sm" onClick={createShort} disabled={busy || dismissed}>
        <Wand2 aria-hidden="true" />
        {busy ? "Starting…" : "Create Short"}
      </Button>
    );
    cutOnly = !dismissed && !busy;
  } else if (clip.status === "failed" || (isClipActive(clip.status) && clip.is_stale)) {
    primary = (
      <Button size="sm" onClick={retry} disabled={busy}>
        <RotateCcw aria-hidden="true" />
        {busy ? "Retrying…" : "Try again"}
      </Button>
    );
    status = (
      <InlineAlert
        tone={clip.status === "failed" ? "danger" : "warning"}
        title={clip.status === "failed" ? "This clip couldn't be prepared" : "Preparing the clip stalled"}
      >
        {clip.status === "failed" ? friendlyClipError(clip) : "The work stopped responding. Try again to continue."}
      </InlineAlert>
    );
  } else {
    // Cutting or ready: the Start step shows the progress and opens as soon as the clip is ready.
    primary = (
      <ButtonLink href={createHref(projectId, clip.id)} size="sm">
        <Wand2 aria-hidden="true" />
        Create Short
      </ButtonLink>
    );
    if (isClipActive(clip.status)) {
      status = (
        <WorkingState
          label={clip.status === "queued" ? "Waiting to start" : "Cutting the clip"}
          progress={clip.status === "queued" ? null : clip.progress_percent}
          progressLabel="Clip progress"
        />
      );
    } else {
      downloadUrl = clipDownloadUrl(clip.id);
      status = (
        <p className="flex items-center gap-1.5 text-xs text-muted">
          <CheckCircle2 aria-hidden="true" className="size-3.5 text-success" />
          Clip ready · {formatDuration(clip.duration_seconds)}
        </p>
      );
    }
  }

  return (
    <div className="mt-4 space-y-3" role="group" aria-label={`Actions for ${candidate.title}`}>
      <div className="flex flex-wrap items-center gap-2">
        {primary}
        {secondary}
        {cutOnly || downloadUrl ? (
          <MoreActions onCutOnly={cutOnly ? generate : undefined} downloadUrl={downloadUrl ?? undefined} />
        ) : null}
      </div>
      {status}
      {error ? <InlineAlert title="That didn't work">{error}</InlineAlert> : null}
    </div>
  );
}

function MoreActions({ onCutOnly, downloadUrl }: { onCutOnly?: () => void; downloadUrl?: string }) {
  const items: MenuItem[] = [];
  if (onCutOnly) items.push({ label: "Only cut the clip", icon: Clapperboard, onSelect: onCutOnly });
  if (downloadUrl) items.push({ label: "Download the clip (MP4)", icon: Download, onSelect: () => download(downloadUrl) });
  return <Menu label="More actions" trigger={<MoreHorizontal aria-hidden="true" />} items={items} />;
}

/** Starts a download of an owner-only file (the session cookie goes with it). */
function download(url: string) {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  link.click();
}
