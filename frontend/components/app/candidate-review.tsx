"use client";

import { Bookmark, BookmarkCheck, ChevronDown, EyeOff, Film, Play, SearchX, Undo2, X } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { MediaFrame } from "@/components/ui/media-frame";
import { ClipRenderControls } from "@/components/app/clip-render-controls";
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
import type { GeneratedClip } from "@/lib/clips";
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
    <MediaFrame
      icon={Film}
      label="Source preview"
      meta={`${formatTimestamp(start)} – ${formatTimestamp(end)} of the original`}
      className="animate-fade-in"
    >
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
        className="aspect-video w-full bg-black"
        aria-label={`Preview of “${title}” from ${formatTimestamp(start)} to ${formatTimestamp(end)}`}
      />
    </MediaFrame>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <li className="flex items-center gap-2 text-xs">
      <span className="w-24 shrink-0 text-muted">{label}</span>
      <span
        className="h-1 flex-1 overflow-hidden rounded-full bg-white/10"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
      >
        <span className="block h-full rounded-full bg-white/45" style={{ width: `${value}%` }} />
      </span>
      <span className="tabular w-7 text-right text-muted">{value}</span>
    </li>
  );
}

/** The overall score is the one number that matters at a glance; the breakdown is secondary. */
function ScoreBadge({ score }: { score: number }) {
  return (
    <div
      className="flex shrink-0 flex-col items-center justify-center rounded-xl border border-border bg-surface-2 px-3 py-2"
      title="Overall editorial score, 0–100. A weighted judgement, not a prediction of views."
    >
      <span className="tabular text-2xl leading-none font-semibold text-foreground" aria-hidden="true">
        {score}
      </span>
      <span className="mt-1 text-[10px] font-medium tracking-wide text-subtle uppercase" aria-hidden="true">
        Score
      </span>
      <span className="sr-only">Overall score {score} out of 100</span>
    </div>
  );
}

function CandidateCard({
  candidate,
  videoId,
  previewing,
  onPreview,
  busy,
  onDecide,
  clipControls,
}: {
  candidate: ClipCandidate;
  videoId: string;
  previewing: boolean;
  onPreview: () => void;
  busy: boolean;
  onDecide: (action: "save" | "dismiss" | "reset") => void;
  clipControls: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const dismissed = candidate.decision === "dismissed";
  const saved = candidate.decision === "saved";
  const top = candidate.rank === 1;

  return (
    <li
      className={`rounded-2xl border bg-surface-2/40 p-4 transition-[border-color,opacity] duration-200 sm:p-5 ${
        saved ? "border-success/40" : "border-border"
      } ${dismissed ? "opacity-60 hover:opacity-90" : ""}`}
      aria-label={`Candidate ${candidate.rank}: ${candidate.title}`}
    >
      <div className="flex gap-3 sm:gap-4">
        <span
          aria-hidden="true"
          className={`tabular flex size-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold sm:size-10 ${
            top ? "bg-accent/15 text-accent-soft" : "bg-surface-3 text-muted"
          }`}
        >
          #{candidate.rank}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="rounded-md bg-surface-3 px-1.5 py-0.5 text-caption font-medium text-muted">
              {CATEGORY_LABELS[candidate.category] ?? candidate.category}
            </span>
            {saved ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-success/10 px-1.5 py-0.5 text-caption font-medium text-emerald-200">
                <BookmarkCheck aria-hidden="true" className="size-3" />
                Saved
              </span>
            ) : null}
            {dismissed ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-surface-3 px-1.5 py-0.5 text-caption font-medium text-subtle">
                <EyeOff aria-hidden="true" className="size-3" />
                Dismissed
              </span>
            ) : null}
          </div>
          <h4 className="mt-1.5 text-base leading-snug font-semibold text-balance break-words text-foreground sm:text-section">
            {candidate.title}
          </h4>
          <p className="tabular mt-1 text-xs text-muted">
            <time dateTime={`PT${Math.floor(candidate.start)}S`}>{formatTimestamp(candidate.start)}</time>
            {" – "}
            <time dateTime={`PT${Math.floor(candidate.end)}S`}>{formatTimestamp(candidate.end)}</time>
            <span className="text-subtle"> · {formatDuration(candidate.duration)}</span>
          </p>
        </div>
        <ScoreBadge score={candidate.overall_score} />
      </div>

      <blockquote className="mt-4 border-l-2 border-accent/60 pl-3 text-lead leading-relaxed text-pretty text-foreground">
        {candidate.hook}
      </blockquote>

      <div className="mt-3">
        <p className="text-xs font-medium text-subtle">Why it was selected</p>
        <p className={`mt-1 text-sm leading-relaxed text-pretty text-muted ${expanded ? "" : "line-clamp-2"}`}>
          {candidate.rationale}
        </p>
      </div>

      <details className="group mt-3" onToggle={(e) => setExpanded((e.target as HTMLDetailsElement).open)}>
        <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded text-xs text-accent-soft select-none hover:underline [&::-webkit-details-marker]:hidden">
          <ChevronDown aria-hidden="true" className="size-3.5 transition-transform group-open:rotate-180" />
          <span className="group-open:hidden">More: score breakdown{candidate.transcript_excerpt ? " and transcript" : ""}</span>
          <span className="hidden group-open:inline">Less</span>
        </summary>
        <div className="mt-3 space-y-3 animate-fade-in">
          <ul className="grid gap-1.5 sm:grid-cols-2 sm:gap-x-6" aria-label="Score breakdown">
            {DIMENSIONS.map(({ key, label }) => (
              <ScoreBar key={key} label={label} value={candidate.scores[key]} />
            ))}
          </ul>
          {candidate.transcript_excerpt ? (
            <blockquote className="rounded-lg bg-surface-3/60 px-3 py-2 text-sm leading-relaxed break-words text-muted">
              {candidate.transcript_excerpt}
            </blockquote>
          ) : null}
        </div>
      </details>

      {previewing ? (
        <div className="mt-4">
          <ClipPreview videoId={videoId} start={candidate.start} end={candidate.end} title={candidate.title} />
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" onClick={onPreview} aria-pressed={previewing}>
          {previewing ? <X aria-hidden="true" /> : <Play aria-hidden="true" />}
          {previewing ? "Close source preview" : "Preview source"}
        </Button>
        {saved ? (
          <Button variant="ghost" size="sm" onClick={() => onDecide("reset")} disabled={busy} aria-pressed="true">
            <BookmarkCheck aria-hidden="true" className="text-success" />
            Unsave
          </Button>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => onDecide("save")} disabled={busy} aria-pressed="false">
            <Bookmark aria-hidden="true" />
            Save
          </Button>
        )}
        {dismissed ? (
          <Button variant="ghost" size="sm" onClick={() => onDecide("reset")} disabled={busy}>
            <Undo2 aria-hidden="true" />
            Restore
          </Button>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => onDecide("dismiss")} disabled={busy}>
            <EyeOff aria-hidden="true" />
            Dismiss
          </Button>
        )}
      </div>

      {clipControls}
    </li>
  );
}

type Props = {
  projectId: string;
  videoId: string;
  run: DetectionRun;
  /** candidate_id → generated clip, owned by the workspace (null while loading). */
  clips: Map<string, GeneratedClip> | null;
  /** False when the listing failed: each card then fetches its own clip state. */
  clipsKnown: boolean;
  onClipChange: (clip: GeneratedClip) => void;
};

/** Ranked candidates of a completed run: filter, page, preview, save/dismiss. */
export function CandidateReview({ projectId, videoId, run, clips, clipsKnown, onClipChange }: Props) {
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
        <div role="tablist" aria-label="Filter candidates" className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
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
              className={`inline-flex h-8 items-center rounded-md px-3 text-small font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                filter === option.value
                  ? "bg-surface-3 text-foreground shadow-sm"
                  : "text-muted hover:text-foreground"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <p className="tabular text-xs text-subtle">
          {loading && candidates.length === 0 ? "" : `${candidates.length} of ${total}`}
        </p>
      </div>

      {(loading && candidates.length === 0) || clips === null ? (
        <LoadingState label="Loading candidates…" />
      ) : error && candidates.length === 0 ? (
        <ErrorState title="Candidates could not be loaded" message={error} onRetry={() => void load(0)} />
      ) : candidates.length === 0 ? (
        <EmptyState
          compact
          icon={SearchX}
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
              clipControls={
                <ClipRenderControls
                  projectId={projectId}
                  videoId={videoId}
                  runId={run.id}
                  candidate={candidate}
                  initialClip={clipsKnown ? (clips.get(candidate.id) ?? null) : undefined}
                  onChange={onClipChange}
                />
              }
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

      <p className="text-xs text-subtle">
        Scores are the model&apos;s editorial judgement on a 0–100 scale, normalised across
        providers. They are not predictions of views or engagement.
      </p>
    </div>
  );
}
