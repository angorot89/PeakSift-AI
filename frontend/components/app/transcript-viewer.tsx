"use client";

import { Check, Copy, MicOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { EmptyState, ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { TRANSCRIPT_PAGE_SIZE, getTranscriptPage, type TranscriptSegment } from "@/lib/transcription";

type Props = { projectId: string; videoId: string; total: number; footnote?: string };

/** Paginated, read-only transcript: timestamps + text, loaded page by page. */
export function TranscriptViewer({ projectId, videoId, total, footnote }: Props) {
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

  if (loading && segments.length === 0) {
    return (
      <div role="status" aria-label="Loading transcript" className="space-y-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-5 rounded-md" />
        ))}
      </div>
    );
  }
  if (error && segments.length === 0)
    return <ErrorState title="Transcript could not be loaded" message={error} onRetry={() => loadMore(0)} />;
  if (total === 0 || (segments.length === 0 && !loading)) {
    return (
      <EmptyState
        compact
        icon={MicOff}
        title="No speech detected"
        description="The audio was processed but no spoken words were found."
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="tabular text-xs text-subtle">
          Showing {segments.length} of {total}
        </p>
        <Button variant="ghost" size="sm" onClick={copyTranscript} disabled={copyState === "copying"}>
          {copyState === "copied" ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copyState === "copied"
            ? "Copied"
            : copyState === "failed"
              ? "Copy failed"
              : copyState === "copying"
                ? "Copying…"
                : "Copy transcript"}
        </Button>
      </div>

      {/* A bounded, scrollable reading area so long recordings don't push everything else away. */}
      <div
        tabIndex={0}
        role="region"
        aria-label="Transcript"
        className="max-h-[26rem] overflow-y-auto rounded-xl border border-border bg-surface-2/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <ol className="divide-y divide-border">
          {segments.map((segment) => (
            <li key={segment.sequence_index} className="flex gap-3 px-4 py-2.5 sm:gap-4">
              <time
                dateTime={`PT${Math.floor(segment.start)}S`}
                className="mt-0.5 shrink-0 self-start rounded-md bg-surface-3 px-1.5 py-0.5 font-mono text-caption text-accent-soft"
                title={`${formatTimestamp(segment.start)} – ${formatTimestamp(segment.end)}`}
              >
                {formatTimestamp(segment.start)}
              </time>
              <p className="min-w-0 text-sm leading-relaxed break-words text-foreground/90">{segment.text}</p>
            </li>
          ))}
        </ol>
        {loaded < total ? (
          <div className="flex justify-center border-t border-border p-3">
            <Button variant="secondary" size="sm" onClick={() => loadMore(loaded)} disabled={loading}>
              {loading ? "Loading more…" : `Load ${Math.min(TRANSCRIPT_PAGE_SIZE, total - loaded)} more`}
            </Button>
          </div>
        ) : null}
      </div>

      {error ? <ErrorState title="More segments could not be loaded" message={error} onRetry={() => loadMore(loaded)} /> : null}
      {footnote ? <p className="text-xs text-subtle">{footnote}</p> : null}
    </div>
  );
}
