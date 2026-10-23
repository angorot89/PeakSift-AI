"use client";

import { Bookmark, BookmarkCheck, ChevronDown, EyeOff, Film, Play, SearchX, Star, Undo2, X } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { MediaFrame } from "@/components/ui/media-frame";
import { ClipRenderControls } from "@/components/app/clip-render-controls";
import { EmptyState, ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api";
import {
  CANDIDATE_PAGE_SIZE,
  decideCandidate,
  listCandidates,
  type CandidateCounts,
  type ClipCandidate,
  type DetectionRun,
} from "@/lib/clip-detection";
import type { GeneratedClip } from "@/lib/clips";
import { formatDuration, formatTimestamp } from "@/lib/format";
import { MOMENT_FILTERS, emptyMoments, momentCount, momentQuery, type MomentFilter } from "@/lib/moments";
import { videoContentUrl } from "@/lib/videos";
import { momentLabel } from "@/lib/workspace";

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

const LABEL_STYLES = {
  "Top pick": "bg-accent/15 text-accent-soft",
  "Strong moment": "bg-sky-400/10 text-sky-200",
  "Worth reviewing": "bg-surface-3 text-muted",
} as const;

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

/** A still from the moment, loaded only once the card scrolls into view; pressing it previews. */
function MomentThumbnail({
  videoId,
  start,
  title,
  previewing,
  onPreview,
}: {
  videoId: string;
  start: number;
  title: string;
  previewing: boolean;
  onPreview: () => void;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const [visible, setVisible] = useState(false);
  const [painted, setPainted] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return (
    <button
      ref={ref}
      type="button"
      onClick={onPreview}
      aria-pressed={previewing}
      aria-label={`${previewing ? "Close the preview of" : "Preview"} “${title}”`}
      className="group relative block aspect-video w-28 shrink-0 self-start overflow-hidden rounded-xl border border-border bg-[linear-gradient(160deg,var(--surface-3),var(--background))] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:w-44"
    >
      <span aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-subtle">
        <Film className="size-5" />
      </span>
      {visible ? (
        <video
          src={`${videoContentUrl(videoId)}#t=${(start + 0.5).toFixed(2)}`}
          preload="metadata"
          muted
          playsInline
          aria-hidden="true"
          tabIndex={-1}
          onLoadedData={() => setPainted(true)}
          className={`relative size-full object-cover transition-opacity ${painted ? "opacity-100" : "opacity-0"}`}
        />
      ) : null}
      <span className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/30">
        <span className="flex size-9 items-center justify-center rounded-full bg-black/70 text-white">
          {previewing ? <X aria-hidden="true" className="size-4" /> : <Play aria-hidden="true" className="size-4" />}
        </span>
      </span>
    </button>
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

function MomentCard({
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
  clipControls: (secondary: ReactNode) => ReactNode;
}) {
  const dismissed = candidate.decision === "dismissed";
  const saved = candidate.decision === "saved";
  const label = momentLabel(candidate.rank, candidate.overall_score);
  const times = (
    <p className="tabular text-xs text-muted">
      <time dateTime={`PT${Math.floor(candidate.start)}S`}>{formatTimestamp(candidate.start)}</time>
      {" – "}
      <time dateTime={`PT${Math.floor(candidate.end)}S`}>{formatTimestamp(candidate.end)}</time>
      <span className="text-subtle"> · {formatDuration(candidate.duration)}</span>
    </p>
  );

  // A dismissed moment stays out of the way: one line and Restore.
  if (dismissed) {
    return (
      <li className="flex items-center justify-between gap-3 rounded-xl border border-border px-4 py-3" aria-label={`Dismissed moment: ${candidate.title}`}>
        <div className="min-w-0">
          <p className="truncate text-sm text-muted">{candidate.title}</p>
          {times}
        </div>
        <Button variant="ghost" size="sm" onClick={() => onDecide("reset")} disabled={busy}>
          <Undo2 aria-hidden="true" />
          Restore
        </Button>
      </li>
    );
  }

  const secondary = (
    <>
      <Button variant="secondary" size="sm" onClick={onPreview} aria-pressed={previewing}>
        {previewing ? <X aria-hidden="true" /> : <Play aria-hidden="true" />}
        {previewing ? "Close preview" : "Preview"}
      </Button>
      <span className="ml-auto flex items-center gap-1">
        {saved ? (
          <Button variant="ghost" size="sm" onClick={() => onDecide("reset")} disabled={busy} aria-pressed="true">
            <BookmarkCheck aria-hidden="true" className="text-success" />
            Saved
          </Button>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => onDecide("save")} disabled={busy} aria-pressed="false">
            <Bookmark aria-hidden="true" />
            Save
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={() => onDecide("dismiss")} disabled={busy}>
          <EyeOff aria-hidden="true" />
          Dismiss
        </Button>
      </span>
    </>
  );

  return (
    <li
      className={`rounded-2xl border bg-surface p-4 transition-colors sm:p-5 ${saved ? "border-success/40" : "border-border"}`}
      aria-label={`${label}: ${candidate.title}`}
    >
      <div className="flex gap-3 sm:gap-4">
        <MomentThumbnail
          videoId={videoId}
          start={candidate.start}
          title={candidate.title}
          previewing={previewing}
          onPreview={onPreview}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-caption font-medium ${LABEL_STYLES[label]}`}>
              {label === "Top pick" ? <Star aria-hidden="true" className="size-3" /> : null}
              {label}
            </span>
            <span className="rounded-md bg-surface-3 px-1.5 py-0.5 text-caption font-medium text-muted">
              {CATEGORY_LABELS[candidate.category] ?? candidate.category}
            </span>
          </div>
          <h3 className="mt-1.5 text-section text-balance break-words text-foreground">{candidate.title}</h3>
          <div className="mt-0.5">{times}</div>
          <blockquote className="mt-3 border-l-2 border-accent/60 pl-3 text-sm leading-relaxed text-pretty text-foreground">
            {candidate.hook}
          </blockquote>
          <p className="mt-2 line-clamp-2 text-small text-pretty text-muted">
            <span className="text-subtle">Why: </span>
            {candidate.rationale}
          </p>
          <details className="group mt-2">
            <summary className="inline-flex min-h-8 cursor-pointer pointer-coarse:min-h-11 list-none items-center gap-1 rounded text-xs text-accent-soft select-none hover:underline [&::-webkit-details-marker]:hidden">
              <ChevronDown aria-hidden="true" className="size-3.5 transition-transform group-open:rotate-180" />
              <span className="group-open:hidden">Details</span>
              <span className="hidden group-open:inline">Less</span>
            </summary>
            <div className="mt-2 animate-fade-in space-y-3">
              <p className="text-small text-pretty text-muted">{candidate.rationale}</p>
              <p className="text-xs text-subtle">
                Editorial score <span className="tabular text-muted">{candidate.overall_score}</span> of 100 — the model&apos;s
                judgement, not a prediction of views.
              </p>
              <ul className="grid gap-1.5 sm:grid-cols-2 sm:gap-x-6" aria-label="Score breakdown">
                {DIMENSIONS.map(({ key, label: name }) => (
                  <ScoreBar key={key} label={name} value={candidate.scores[key]} />
                ))}
              </ul>
              {candidate.transcript_excerpt ? (
                <blockquote className="rounded-lg bg-surface-3/60 px-3 py-2 text-sm leading-relaxed break-words text-muted">
                  {candidate.transcript_excerpt}
                </blockquote>
              ) : null}
            </div>
          </details>
        </div>
      </div>

      {previewing ? (
        <div className="mt-4">
          <ClipPreview videoId={videoId} start={candidate.start} end={candidate.end} title={candidate.title} />
        </div>
      ) : null}

      {clipControls(secondary)}
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

/** The moments of a completed search, best first: filter, page, preview, save/dismiss, create. */
export function CandidateReview({ projectId, videoId, run, clips, clipsKnown, onClipChange }: Props) {
  const [filter, setFilter] = useState<MomentFilter>("all");
  const [candidates, setCandidates] = useState<ClipCandidate[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<CandidateCounts | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const toast = useToast();

  const query = momentQuery(filter);
  const { view, decision } = query;

  const load = useCallback(
    (offset: number) => {
      setLoading(true);
      setError(null);
      return listCandidates(projectId, videoId, run.id, offset, CANDIDATE_PAGE_SIZE, decision, view)
        .then((page) => {
          setCandidates((previous) => (offset === 0 ? page.candidates : [...previous, ...page.candidates]));
          setTotal(page.total);
          setCounts(page.counts);
          setLoading(false);
        })
        .catch((err: unknown) => {
          setError(errorMessage(err));
          setLoading(false);
        });
    },
    [projectId, videoId, run.id, decision, view],
  );

  // First page whenever the run or the filter changes.
  useEffect(() => {
    let cancelled = false;
    listCandidates(projectId, videoId, run.id, 0, CANDIDATE_PAGE_SIZE, decision, view)
      .then((page) => {
        if (cancelled) return;
        setCandidates(page.candidates);
        setTotal(page.total);
        setCounts(page.counts);
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
  }, [projectId, videoId, run.id, decision, view]);

  async function decide(candidate: ClipCandidate, action: "save" | "dismiss" | "reset") {
    setBusyId(candidate.id);
    setActionError(null);
    try {
      const updated = await decideCandidate(projectId, videoId, run.id, candidate.id, action);
      const before = candidate.decision;
      // A card leaves the list once it no longer belongs to the filter (e.g. dismissed from All).
      const belongs = (item: ClipCandidate) =>
        filter === "all" || filter === "top" ? item.decision !== "dismissed" : item.decision === filter;
      setCandidates((previous) => previous.map((item) => (item.id === updated.id ? updated : item)).filter(belongs));
      if (!belongs(updated)) setTotal((t) => Math.max(0, t - 1));
      setCounts((current) => (current ? recount(current, before, updated) : current));
      if (action === "dismiss") toast("Moment dismissed. It's kept under Dismissed.");
      else if (action === "save") toast("Moment saved");
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  function changeFilter(next: MomentFilter) {
    setFilter(next);
    setPreviewId(null);
    setCandidates([]);
    setLoading(true);
  }

  const firstLoad = (loading && candidates.length === 0) || clips === null;
  const empty = counts ? emptyMoments(filter, counts) : null;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl
          label="Show moments"
          value={filter}
          onChange={changeFilter}
          options={MOMENT_FILTERS.map((option) => ({
            ...option,
            count: counts ? momentCount(counts, option.value) : undefined,
          }))}
        />
        {!firstLoad && total > 0 ? (
          <p className="tabular text-xs text-subtle">
            {candidates.length < total ? `${candidates.length} of ${total}` : `${total} ${total === 1 ? "moment" : "moments"}`}
          </p>
        ) : null}
      </div>

      {firstLoad ? (
        <div role="status" aria-label="Loading moments" className="space-y-3">
          <Skeleton className="h-40 rounded-2xl" />
          <Skeleton className="h-40 rounded-2xl" />
        </div>
      ) : error && candidates.length === 0 ? (
        <ErrorState title="Moments couldn't be loaded" message={error} onRetry={() => void load(0)} />
      ) : candidates.length === 0 && empty ? (
        <EmptyState
          compact
          icon={SearchX}
          title={empty.title}
          description={empty.description}
          action={
            empty.offer ? (
              <Button variant="secondary" size="sm" onClick={() => changeFilter(empty.offer!)}>
                Show {MOMENT_FILTERS.find((f) => f.value === empty.offer)?.label.toLowerCase()}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ol className="space-y-3">
          {candidates.map((candidate) => (
            <MomentCard
              key={candidate.id}
              candidate={candidate}
              videoId={videoId}
              previewing={previewId === candidate.id}
              onPreview={() => setPreviewId((id) => (id === candidate.id ? null : candidate.id))}
              busy={busyId === candidate.id}
              onDecide={(action) => void decide(candidate, action)}
              clipControls={(secondary) => (
                <ClipRenderControls
                  projectId={projectId}
                  videoId={videoId}
                  runId={run.id}
                  candidate={candidate}
                  initialClip={clipsKnown ? (clips.get(candidate.id) ?? null) : undefined}
                  onChange={onClipChange}
                  secondary={secondary}
                />
              )}
            />
          ))}
        </ol>
      )}

      {error && candidates.length > 0 ? <ErrorState message={error} onRetry={() => void load(candidates.length)} /> : null}

      {candidates.length < total ? (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={() => void load(candidates.length)} disabled={loading}>
            {loading ? "Loading…" : `Show ${Math.min(CANDIDATE_PAGE_SIZE, total - candidates.length)} more`}
          </Button>
        </div>
      ) : null}

      <FormError>{actionError}</FormError>

      <p className="text-xs text-subtle">
        Moments are ranked by editorial judgement (Top pick, Strong moment, Worth reviewing). They are not predictions of
        views or engagement.
      </p>
    </div>
  );
}

/** The filter counts after one decision changed (the next page load brings the server's). */
function recount(counts: CandidateCounts, before: ClipCandidate["decision"], after: ClipCandidate): CandidateCounts {
  const next = { ...counts };
  const strong = after.rank === 1 || momentLabel(after.rank, after.overall_score) !== "Worth reviewing";
  const move = (decision: ClipCandidate["decision"], by: number) => {
    if (decision === "dismissed") next.dismissed += by;
    else {
      next.active += by;
      if (strong) next.top += by;
    }
    if (decision === "saved") next.saved += by;
  };
  move(before, -1);
  move(after.decision, 1);
  return next;
}
