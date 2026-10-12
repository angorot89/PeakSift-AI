"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { errorMessage } from "@/lib/api";
import {
  CANDIDATE_PAGE_SIZE,
  decideCandidate,
  listCandidates,
  type CandidateDecision,
  type ClipCandidate,
  type DetectionRun,
} from "@/lib/clip-detection";
import { formatDuration, formatTimestamp } from "@/lib/format";
import { videoContentUrl } from "@/lib/videos";

type Filter = "all" | CandidateDecision;

const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: "all", label: "All" },
  { value: "saved", label: "Saved" },
  { value: "dismissed", label: "Dismissed" },
];

const CATEGORY_LABELS: Record<string, string> = {
  humor: "Humor",
  reaction: "Reaction",
  story: "Story",
  insight: "Insight",
  conflict: "Conflict",
  emotional: "Emotional",
  hot_take: "Hot take",
  explanation: "Explanation",
  other: "Moment",
};

const DIMENSIONS: Array<{ key: keyof ClipCandidate["scores"]; label: string }> = [
  { key: "hook", label: "Hook" },
  { key: "entertainment", label: "Entertainment" },
  { key: "clarity", label: "Clarity" },
  { key: "payoff", label: "Payoff" },
  { key: "completeness", label: "Completeness" },
];

/** Plays only [start, end] of the owner-only source stream; pauses at the end. */
function ClipPreview({
  videoId,
  start,
  end,
  title,
}: {
  videoId: string;
  start: number;
  end: number;
  title: string;
}) {
  const ref = useRef<HTMLVideoElement>(null);

  function clampToRange() {
    const video = ref.current;
    if (!video) return;
    if (video.currentTime >= end) {
      video.pause();
      video.currentTime = end;
    } else if (video.currentTime < start - 0.5) {
      video.currentTime = start;
    }
  }

  return (
    <div className="space-y-2">
      {/* The media fragment makes the browser start at `start`; timeupdate stops at `end`. */}
      <video
        ref={ref}
        controls
        autoPlay
        preload="metadata"
        src={`${videoContentUrl(videoId)}#t=${start.toFixed(2)},${end.toFixed(2)}`}
        onLoadedMetadata={() => {
          if (ref.current && Math.abs(ref.current.currentTime - start) > 0.5) {
            ref.current.currentTime = start;
          }
        }}
        onTimeUpdate={clampToRange}
        className="aspect-video w-full rounded-xl bg-black"
        aria-label={`Preview of “${title}” from ${formatTimestamp(start)} to ${formatTimestamp(end)}`}
      />
      <p className="text-xs text-muted">
        Previewing {formatTimestamp(start)} – {formatTimestamp(end)} of the original video. Nothing
        has been exported.
      </p>
    </div>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <li className="flex items-center gap-2 text-xs">
      <span className="w-24 shrink-0 text-muted">{label}</span>
      <span
        className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
      >
        <span className="block h-full bg-accent/80" style={{ width: `${value}%` }} />
      </span>
      <span className="w-7 text-right font-mono text-muted">{value}</span>
    </li>
  );
}

function CandidateCard({
  candidate,
  videoId,
  previewing,
  onPreview,
  busy,
  onDecide,
}: {
  candidate: ClipCandidate;
  videoId: string;
  previewing: boolean;
  onPreview: () => void;
  busy: boolean;
  onDecide: (action: "save" | "dismiss" | "reset") => void;
}) {
  const [showExcerpt, setShowExcerpt] = useState(false);
  const dismissed = candidate.decision === "dismissed";
  const saved = candidate.decision === "saved";

  return (
    <li
      className={`rounded-2xl border bg-surface p-4 sm:p-5 ${
        saved ? "border-emerald-500/40" : dismissed ? "border-border opacity-60" : "border-border"
      }`}
      aria-label={`Candidate ${candidate.rank}: ${candidate.title}`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium tracking-wide text-muted uppercase">
            #{candidate.rank} · {CATEGORY_LABELS[candidate.category] ?? candidate.category}
            {saved ? " · Saved" : dismissed ? " · Dismissed" : ""}
          </p>
          <h4 className="font-medium break-words text-foreground">{candidate.title}</h4>
          <p className="font-mono text-xs text-accent-soft">
            <time dateTime={`PT${Math.floor(candidate.start)}S`}>{formatTimestamp(candidate.start)}</time>
            {" – "}
            <time dateTime={`PT${Math.floor(candidate.end)}S`}>{formatTimestamp(candidate.end)}</time>
            <span className="text-muted"> · {formatDuration(candidate.duration)}</span>
          </p>
        </div>
        <div
          className="flex shrink-0 items-baseline gap-1 rounded-xl border border-border px-3 py-1.5"
          title="Overall editorial score, 0–100. A weighted judgement, not a prediction."
        >
          <span className="text-2xl font-semibold text-foreground">{candidate.overall_score}</span>
          <span className="text-xs text-muted">/ 100</span>
        </div>
      </div>

      <p className="mt-3 text-sm text-foreground">
        <span className="text-muted">Hook: </span>
        {candidate.hook}
      </p>
      <p className="mt-1 text-sm leading-relaxed text-muted">{candidate.rationale}</p>

      <ul className="mt-3 grid gap-1 sm:grid-cols-2 sm:gap-x-6" aria-label="Score breakdown">
        {DIMENSIONS.map(({ key, label }) => (
          <ScoreBar key={key} label={label} value={candidate.scores[key]} />
        ))}
      </ul>

      {candidate.transcript_excerpt ? (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowExcerpt((v) => !v)}
            aria-expanded={showExcerpt}
            className="text-xs text-accent-soft underline-offset-2 hover:underline"
          >
            {showExcerpt ? "Hide transcript excerpt" : "Show transcript excerpt"}
          </button>
          {showExcerpt ? (
            <blockquote className="mt-2 border-l-2 border-border pl-3 text-sm leading-relaxed break-words text-muted">
              {candidate.transcript_excerpt}
            </blockquote>
          ) : null}
        </div>
      ) : null}

      {previewing ? (
        <div className="mt-4">
          <ClipPreview
            videoId={videoId}
            start={candidate.start}
            end={candidate.end}
            title={candidate.title}
          />
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="secondary" onClick={onPreview} aria-pressed={previewing}>
          {previewing ? "Close preview" : "Preview"}
        </Button>
        {saved ? (
          <Button variant="secondary" onClick={() => onDecide("reset")} disabled={busy}>
            Unsave
          </Button>
        ) : (
          <Button onClick={() => onDecide("save")} disabled={busy}>
            Save
          </Button>
        )}
        {dismissed ? (
          <Button variant="secondary" onClick={() => onDecide("reset")} disabled={busy}>
            Restore
          </Button>
        ) : (
          <Button variant="secondary" onClick={() => onDecide("dismiss")} disabled={busy}>
            Dismiss
          </Button>
        )}
      </div>
    </li>
  );
}

type Props = { projectId: string; videoId: string; run: DetectionRun };

/** Ranked candidates of a completed run: filter, page, preview, save/dismiss. */
export function CandidateReview({ projectId, videoId, run }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const [candidates, setCandidates] = useState<ClipCandidate[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);

  const decision = filter === "all" ? undefined : filter;

  const load = useCallback(
    (offset: number) => {
      setLoading(true);
      setError(null);
      return listCandidates(projectId, videoId, run.id, offset, CANDIDATE_PAGE_SIZE, decision)
        .then((page) => {
          setCandidates((previous) =>
            offset === 0 ? page.candidates : [...previous, ...page.candidates],
          );
          setTotal(page.total);
          setLoading(false);
        })
        .catch((err: unknown) => {
          setError(errorMessage(err));
          setLoading(false);
        });
    },
    [projectId, videoId, run.id, decision],
  );

  // First page whenever the run or the filter changes.
  useEffect(() => {
    let cancelled = false;
    listCandidates(projectId, videoId, run.id, 0, CANDIDATE_PAGE_SIZE, decision)
      .then((page) => {
        if (cancelled) return;
        setCandidates(page.candidates);
        setTotal(page.total);
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
  }, [projectId, videoId, run.id, decision]);

  async function decide(candidate: ClipCandidate, action: "save" | "dismiss" | "reset") {
    setBusyId(candidate.id);
    setActionError(null);
    try {
      const updated = await decideCandidate(projectId, videoId, run.id, candidate.id, action);
      setCandidates((previous) =>
        previous
          .map((item) => (item.id === updated.id ? updated : item))
          // Under a decision filter the card leaves the list once it no longer matches.
          .filter((item) => decision === undefined || item.decision === decision),
      );
      if (decision !== undefined && updated.decision !== decision) setTotal((t) => Math.max(0, t - 1));
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Filter candidates" className="flex gap-1 rounded-full border border-border p-1">
          {FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={filter === option.value}
              onClick={() => {
                setFilter(option.value);
                setPreviewId(null);
              }}
              className={`rounded-full px-3 py-1 text-sm transition-colors ${
                filter === option.value
                  ? "bg-foreground text-background"
                  : "text-muted hover:text-foreground"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <p className="text-sm text-muted">
          {loading && candidates.length === 0 ? "" : `${candidates.length} of ${total}`}
        </p>
      </div>

      {loading && candidates.length === 0 ? (
        <LoadingState label="Loading candidates…" />
      ) : error && candidates.length === 0 ? (
        <ErrorState message={error} onRetry={() => void load(0)} />
      ) : candidates.length === 0 ? (
        <EmptyState
          title={filter === "all" ? "No clip-worthy moments found" : `No ${filter} candidates`}
          description={
            filter === "all"
              ? "The analysis finished but nothing met the clip criteria. Try another model, or run again after the transcript changes."
              : "Candidates you mark will appear here."
          }
        />
      ) : (
        <ol className="space-y-3">
          {candidates.map((candidate) => (
            <CandidateCard
              key={candidate.id}
              candidate={candidate}
              videoId={videoId}
              previewing={previewId === candidate.id}
              onPreview={() => setPreviewId((id) => (id === candidate.id ? null : candidate.id))}
              busy={busyId === candidate.id}
              onDecide={(action) => void decide(candidate, action)}
            />
          ))}
        </ol>
      )}

      {error && candidates.length > 0 ? (
        <ErrorState message={error} onRetry={() => void load(candidates.length)} />
      ) : null}

      {candidates.length < total ? (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={() => void load(candidates.length)} disabled={loading}>
            {loading ? "Loading…" : `Load more (${Math.min(CANDIDATE_PAGE_SIZE, total - candidates.length)})`}
          </Button>
        </div>
      ) : null}

      <FormError>{actionError}</FormError>
      <p className="text-xs text-muted">
        Scores are the model&apos;s editorial judgement on a 0–100 scale, normalised across
        providers. They are not predictions of views or engagement.
      </p>
    </div>
  );
}
