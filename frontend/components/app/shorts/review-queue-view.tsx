"use client";

import { CalendarClock, CheckCircle2, ChevronRight, Clock, SkipForward, Smartphone } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { PublishBody } from "@/components/app/editor/publish-dialog";
import { PageHeader } from "@/components/app/page-header";
import { PostingTimes } from "@/components/app/schedule/posting-times";
import { formatWhen } from "@/components/app/schedule/scheduled-post";
import { previewAt, previewSrc } from "@/components/app/shorts/short-card";
import { EmptyState, ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { Dialog } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/progress";
import { StatusPill } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import { VideoFrame } from "@/components/ui/video-frame";
import { getPostingSlots, type PublishJob } from "@/lib/publishing";
import { toLocalInput } from "@/lib/schedule-rules";
import {
  getShorts,
  mergeQueue,
  nextFreeSlot,
  nextToReview,
  REVIEW_HREF,
  type ReviewOutcome,
  reviewQueue,
  reviewSummary,
  shortHref,
  type ShortItem,
  type ShortsLibrary,
} from "@/lib/shorts";
import { useApi } from "@/lib/use-api";

const OUTCOME: Record<ReviewOutcome, { label: string; tone: "success" | "waiting" | "neutral" }> = {
  published: { label: "Publishing", tone: "success" },
  scheduled: { label: "Scheduled", tone: "waiting" },
  skipped: { label: "Skipped", tone: "neutral" },
};

/** The rest of the queue as a strip of frames; the one under review is marked. */
function Filmstrip({
  queue,
  index,
  outcomes,
  onPick,
}: {
  queue: ShortItem[];
  index: number;
  outcomes: Record<string, ReviewOutcome>;
  onPick: (index: number) => void;
}) {
  return (
    <nav aria-label="Shorts in this review">
      <ol className="flex gap-3 overflow-x-auto pb-2">
        {queue.map((item, position) => {
          const outcome = outcomes[item.id];
          const current = position === index;
          return (
            <li key={item.id} className="shrink-0">
              <button
                type="button"
                onClick={() => onPick(position)}
                aria-current={current ? "true" : undefined}
                aria-label={`${position + 1}. ${item.title}${outcome ? ` (${OUTCOME[outcome].label})` : ""}`}
                className={`group block w-20 rounded-block text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:w-24 ${
                  current ? "ring-2 ring-accent ring-offset-2 ring-offset-background" : ""
                }`}
              >
                <VideoFrame
                  src={previewSrc(item)}
                  at={previewAt(item)}
                  ratio="vertical"
                  icon={Smartphone}
                  className={`rounded-block border border-border ${outcome ? "opacity-50" : ""}`}
                >
                  {outcome ? (
                    <span className="absolute inset-x-1 bottom-1 flex justify-center">
                      <StatusPill tone={OUTCOME[outcome].tone} overlay>
                        {OUTCOME[outcome].label}
                      </StatusPill>
                    </span>
                  ) : null}
                </VideoFrame>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Where the next post lands: the next free posting time, or a nudge to set them. */
function SlotNote({ slot, hasSlots, onEdit }: { slot: string | null; hasSlots: boolean; onEdit: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-block border border-border bg-surface-2/60 px-4 py-3 text-sm">
      <CalendarClock aria-hidden="true" className="size-4 shrink-0 text-accent-soft" />
      <p className="min-w-0 flex-1 text-muted">
        {slot ? (
          <>
            Next free posting time:{" "}
            <time dateTime={slot} className="font-medium text-foreground">
              {formatWhen(new Date(slot))}
            </time>
            . The form below is set to it; change it or publish now if you prefer.
          </>
        ) : hasSlots ? (
          "Your posting times for the next few weeks are taken. Pick a time below, or add more posting times."
        ) : (
          "Set the times you like to post at, and each Short you approve takes the next free one."
        )}
      </p>
      <Button variant="ghost" size="sm" onClick={onEdit}>
        <Clock aria-hidden="true" />
        {hasSlots ? "Posting times" : "Set posting times"}
      </Button>
    </div>
  );
}

type Progress = { index: number; outcomes: Record<string, ReviewOutcome> };

function Review({ queue, progress, onProgress }: { queue: ShortItem[]; progress: Progress; onProgress: (progress: Progress) => void }) {
  const toast = useToast();
  const { data: posting, reload: reloadSlots } = useApi(getPostingSlots);
  const [taken, setTaken] = useState<string[]>([]);
  const [editingTimes, setEditingTimes] = useState(false);
  const { index, outcomes } = progress;

  const current = queue[index];
  const slot = useMemo(() => nextFreeSlot(posting?.upcoming ?? [], taken), [posting, taken]);
  const handled = Object.keys(outcomes).length;

  /** Record what happened to the current Short and go to the next one not yet handled. */
  function settle(outcome: ReviewOutcome) {
    const next = { ...outcomes, [current.id]: outcome };
    onProgress({ index: nextToReview(queue, index, next) ?? index, outcomes: next });
  }

  function posted(job: PublishJob) {
    const outcome: ReviewOutcome = job.status === "scheduled" ? "scheduled" : "published";
    if (job.scheduled_at) setTaken((list) => [...list, job.scheduled_at as string]);
    toast(
      outcome === "scheduled" && job.scheduled_at
        ? `Scheduled for ${formatWhen(new Date(job.scheduled_at))}.`
        : "Publishing started. Its page shows the progress.",
    );
    settle(outcome);
  }

  const skip = () => settle(outcomes[current.id] ?? "skipped");

  const src = previewSrc(current);
  const outcome = outcomes[current.id];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted" aria-live="polite">
          <span className="font-semibold text-foreground">
            Short {index + 1} of {queue.length}
          </span>
          {handled ? ` · ${reviewSummary(outcomes)}` : null}
        </p>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={skip}>
            <SkipForward aria-hidden="true" />
            {outcome ? "Next" : "Skip"}
          </Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] lg:items-start">
        <div className="mx-auto w-full max-w-xs space-y-3 lg:sticky lg:top-24 lg:mx-0">
          {src ? (
            <video
              key={current.id}
              src={src}
              controls
              playsInline
              preload="metadata"
              aria-label={`Rendered Short: ${current.title}`}
              className="aspect-[9/16] w-full rounded-card border border-border bg-black object-contain shadow-card"
            />
          ) : null}
          <div className="min-w-0">
            <p className="text-title break-words" dir="auto">
              {current.title}
            </p>
            <p className="mt-0.5 truncate text-small text-subtle">
              {current.project.name}
              {current.version ? ` · Version ${current.version.number}` : null}
            </p>
            <Link
              href={shortHref(current.id)}
              className="mt-1 inline-flex min-h-11 items-center gap-1 text-small text-accent-soft underline-offset-2 hover:underline"
            >
              Open this Short
              <ChevronRight aria-hidden="true" className="size-3.5" />
            </Link>
          </div>
        </div>

        <section aria-label="Post this Short" className="min-w-0 space-y-4 rounded-card border border-border bg-surface p-5 shadow-card sm:p-6">
          <SlotNote slot={slot} hasSlots={Boolean(posting?.slots.length)} onEdit={() => setEditingTimes(true)} />
          {current.edit_id ? (
            <PublishBody
              // A fresh form per Short and per offered time.
              key={`${current.id}:${slot ?? "now"}`}
              editId={current.edit_id}
              durationSeconds={current.duration_seconds}
              returnTo={REVIEW_HREF}
              initialWhen={slot ? toLocalInput(new Date(slot)) : undefined}
              onPosted={posted}
              onClose={skip}
            />
          ) : null}
        </section>
      </div>

      {queue.length > 1 ? <Filmstrip queue={queue} index={index} outcomes={outcomes} onPick={(position) => onProgress({ index: position, outcomes })} /> : null}

      <Dialog
        open={editingTimes}
        onClose={() => setEditingTimes(false)}
        title="Posting times"
        description="The times you like to post at each week."
      >
        {editingTimes && posting ? (
          <PostingTimes current={posting} onSaved={reloadSlots} onClose={() => setEditingTimes(false)} />
        ) : null}
      </Dialog>
    </div>
  );
}

/**
 * Review & post: every ready Short in turn, beside its post form, which is already set to the
 * next free posting time. Approve (publish or schedule) or skip; nothing goes out without the
 * creator's click, and the platforms' own rules still apply in each form.
 */
export function ReviewQueueView() {
  const { data, error, loading, reload } = useApi(getShorts);
  const [progress, setProgress] = useState<Progress>({ index: 0, outcomes: {} });
  const [queue, setQueue] = useState<ShortItem[] | null>(null);
  const [seen, setSeen] = useState<ShortsLibrary | null>(null);
  // Fresh data (also when the page is shown again): a review under way keeps its order and gains
  // the Shorts that became ready since; a finished or unstarted one starts from the fresh queue.
  if (data && data !== seen) {
    const handled = Object.keys(progress.outcomes).length;
    const finished = queue !== null && queue.every((item) => item.id in progress.outcomes);
    const reviewing = handled > 0 && !finished;
    setSeen(data);
    setQueue(mergeQueue(queue, reviewQueue(data.shorts), reviewing));
    if (!reviewing && handled) setProgress({ index: 0, outcomes: {} });
  }
  const done = queue !== null && queue.length > 0 && queue.every((item) => item.id in progress.outcomes);

  return (
    <div>
      <PageHeader
        size="hero"
        title="Review & post"
        description="Your ready Shorts, one at a time: check it, then publish, schedule or skip."
        back={{ href: "/shorts", label: "Shorts" }}
      />
      {loading && !queue ? (
        <div role="status" className="flex items-center gap-2 text-sm text-muted">
          <Spinner /> Loading your ready Shorts…
        </div>
      ) : error || !queue ? (
        <ErrorState title="Your Shorts couldn't be loaded" message={error ?? "Try again."} onRetry={reload} />
      ) : queue.length === 0 ? (
        <EmptyState
          icon={CheckCircle2}
          title="Nothing waiting to be posted"
          description="Every ready Short already has a post planned, or none is rendered yet. Finish a Short and it appears here."
          action={<ButtonLink href="/shorts">Open your Shorts</ButtonLink>}
        />
      ) : done ? (
        <EmptyState
          icon={CheckCircle2}
          title="All reviewed"
          description={`${reviewSummary(progress.outcomes)}. Scheduled posts go out at their time; you can move or cancel them on the schedule.`}
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <ButtonLink href="/schedule">Open the schedule</ButtonLink>
              <ButtonLink href="/shorts" variant="secondary">
                Back to Shorts
              </ButtonLink>
            </div>
          }
        />
      ) : (
        <Review queue={queue} progress={progress} onProgress={setProgress} />
      )}
    </div>
  );
}
