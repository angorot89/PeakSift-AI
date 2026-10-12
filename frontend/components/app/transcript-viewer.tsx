"use client";

import { useCallback, useEffect, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { TRANSCRIPT_PAGE_SIZE, getTranscriptPage, type TranscriptSegment } from "@/lib/transcription";

type Props = { projectId: string; videoId: string; total: number };

/** Paginated, read-only transcript: timestamps + text, loaded page by page. */
export function TranscriptViewer({ projectId, videoId, total }: Props) {
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [loaded, setLoaded] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copying" | "copied" | "failed">("idle");

  const loadMore = useCallback(
    (offset: number) => {
      setLoading(true);
      setError(null);
      getTranscriptPage(projectId, videoId, offset)
        .then((page) => {
          setSegments((previous) => (offset === 0 ? page.segments : [...previous, ...page.segments]));
          setLoaded(offset + page.segments.length);
          setLoading(false);
        })
        .catch((err: unknown) => {
          setError(errorMessage(err));
          setLoading(false);
        });
    },
    [projectId, videoId],
  );

  useEffect(() => {
    let cancelled = false;
    getTranscriptPage(projectId, videoId, 0)
      .then((page) => {
        if (cancelled) return;
        setSegments(page.segments);
        setLoaded(page.segments.length);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(errorMessage(err));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, videoId]);

  async function copyTranscript() {
    setCopyState("copying");
    try {
      const page = await getTranscriptPage(projectId, videoId, 0, 1, true);
      await navigator.clipboard.writeText(page.full_text ?? "");
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
    window.setTimeout(() => setCopyState("idle"), 2500);
  }

  if (loading && segments.length === 0) return <LoadingState label="Loading transcript…" />;
  if (error && segments.length === 0) return <ErrorState message={error} onRetry={() => loadMore(0)} />;
  if (total === 0 || (segments.length === 0 && !loading)) {
    return (
      <EmptyState
        title="No speech detected"
        description="The audio was processed but no spoken words were found."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted">
          Showing {segments.length} of {total} segments
        </p>
        <Button variant="secondary" onClick={copyTranscript} disabled={copyState === "copying"}>
          {copyState === "copied"
            ? "Copied"
            : copyState === "failed"
              ? "Copy failed"
              : copyState === "copying"
                ? "Copying…"
                : "Copy transcript"}
        </Button>
      </div>

      <ol className="divide-y divide-border rounded-2xl border border-border bg-surface">
        {segments.map((segment) => (
          <li key={segment.sequence_index} className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:gap-4">
            <time
              dateTime={`PT${Math.floor(segment.start)}S`}
              className="shrink-0 font-mono text-xs text-accent-soft sm:w-20 sm:pt-0.5"
              title={`${formatTimestamp(segment.start)} – ${formatTimestamp(segment.end)}`}
            >
              {formatTimestamp(segment.start)}
            </time>
            <p className="min-w-0 text-sm leading-relaxed break-words text-foreground">{segment.text}</p>
          </li>
        ))}
      </ol>

      {error ? <ErrorState message={error} onRetry={() => loadMore(loaded)} /> : null}

      {loaded < total ? (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={() => loadMore(loaded)} disabled={loading}>
            {loading ? "Loading…" : `Load more (${Math.min(TRANSCRIPT_PAGE_SIZE, total - loaded)})`}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
