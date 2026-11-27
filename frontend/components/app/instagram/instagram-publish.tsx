"use client";

import { CalendarClock, RotateCcw, Send } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useId, useState } from "react";
import { ScheduledPost } from "@/components/app/schedule/scheduled-post";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { FormError } from "@/components/ui/form-error";
import { InlineAlert } from "@/components/ui/inline-alert";
import { inputClasses, textareaClasses } from "@/components/ui/input-styles";
import { Spinner } from "@/components/ui/progress";
import { errorMessage } from "@/lib/api";
import {
  INSTAGRAM_CAPTION_MAX,
  captionCounts,
  getInstagramPanel,
  instagramProblems,
  instagramStage,
  publishToInstagram,
} from "@/lib/instagram";
import { getPublishJob, isActive, isFollowing, retryPublishJob, type PublishJob, type PublishPanel } from "@/lib/publishing";
import { fromLocalInput, suggestedTime, timeProblem, toLocalInput } from "@/lib/schedule-rules";
import { usePolling } from "@/lib/use-polling";

const choice =
  "flex min-h-11 cursor-pointer items-center gap-2.5 rounded-control border border-border px-3 text-sm has-[:checked]:border-accent/60 has-[:checked]:bg-accent/10";

/** The Instagram side of the publish dialog: connect, review the Reel, then its real state. */
export function InstagramPublish({
  editId,
  durationSeconds = null,
  initialWhen,
  onPosted,
}: {
  editId: string;
  durationSeconds?: number | null;
  initialWhen?: string;
  /** Called once with the new post when the creator publishes or schedules it. */
  onPosted?: (job: PublishJob) => void;
}) {
  const [panel, setPanel] = useState<PublishPanel | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [job, setJob] = useState<PublishJob | null>(null);

  useEffect(() => {
    let cancelled = false;
    getInstagramPanel(editId)
      .then((data) => {
        if (cancelled) return;
        setPanel(data);
        const waiting = data.jobs.find((item) => item.status === "scheduled");
        const latest = data.jobs[0];
        if (waiting) setJob(waiting);
        else if (latest && (isActive(latest) || isFollowing(latest))) setJob(latest);
      })
      .catch((failure) => !cancelled && setLoadError(errorMessage(failure)));
    return () => {
      cancelled = true;
    };
  }, [editId]);

  if (loadError) return <InlineAlert title="Instagram is unavailable right now">{loadError}</InlineAlert>;
  if (!panel) {
    return (
      <div role="status" className="flex items-center gap-2 text-sm text-muted">
        <Spinner /> Loading…
      </div>
    );
  }
  if (!panel.connection || panel.connection.status !== "connected") {
    const reconnect = panel.connection?.status === "needs_reconnect";
    return (
      <InlineAlert
        tone="info"
        title={reconnect ? "Reconnect your Instagram account" : "Connect an Instagram account"}
        action={<ButtonLink href="/settings#instagram">{reconnect ? "Reconnect" : "Connect"} in Settings</ButtonLink>}
      >
        {reconnect
          ? "Instagram no longer accepts PeakSift's access. Connect again, then come back to this Short."
          : "Connect your Instagram professional account once in Settings, then come back to this Short."}
      </InlineAlert>
    );
  }
  if (!panel.edit_ready) {
    return (
      <InlineAlert tone="info" title="This Short is not rendered yet">
        Render it first; only a finished Short can be posted.
      </InlineAlert>
    );
  }
  if (job?.status === "scheduled") {
    return (
      <div className="space-y-4">
        <ScheduledPost job={job} onChange={setJob} onCancelled={() => setJob(null)} />
        <p className="text-small text-muted">
          It goes to Instagram as a public Reel with the caption you reviewed.{" "}
          <Link href="/schedule" className="text-accent-soft underline underline-offset-2 hover:text-foreground">
            Open the schedule
          </Link>
        </p>
      </div>
    );
  }
  if (job) return <InstagramJob job={job} onChange={setJob} onNew={() => setJob(null)} />;
  return (
    <ReelForm editId={editId} panel={panel} durationSeconds={durationSeconds} initialWhen={initialWhen}
      onPublished={(next) => {
        setJob(next);
        onPosted?.(next);
      }}
    />
  );
}

function ReelForm({
  editId,
  panel,
  durationSeconds,
  initialWhen,
  onPublished,
}: {
  editId: string;
  panel: PublishPanel;
  durationSeconds: number | null;
  initialWhen?: string;
  onPublished: (job: PublishJob) => void;
}) {
  const id = useId();
  const [caption, setCaption] = useState(panel.defaults.description);
  const [later, setLater] = useState(Boolean(initialWhen));
  const [when, setWhen] = useState(() => initialWhen ?? toLocalInput(suggestedTime(new Date())));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const problems = instagramProblems(caption, durationSeconds);
  const whenProblem = later ? timeProblem(when, new Date()) : null;
  const valid = Object.keys(problems).length === 0 && !whenProblem;
  const counts = captionCounts(caption);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      const scheduledAt = later ? fromLocalInput(when)?.toISOString() : undefined;
      onPublished(await publishToInstagram(editId, panel.defaults.title, caption.trim(), scheduledAt));
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {panel.connection?.account_title ? (
        <p className="text-sm text-muted">
          Posting as <span dir="auto" className="font-medium text-foreground">{panel.connection.account_title}</span>
        </p>
      ) : null}

      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <label htmlFor={`${id}-caption`} className="text-sm font-medium">
            Caption
          </label>
          <span className={`tabular text-xs ${problems.caption ? "text-rose-300" : "text-subtle"}`}>
            {caption.trim().length} / {INSTAGRAM_CAPTION_MAX}
          </span>
        </div>
        <textarea
          id={`${id}-caption`}
          dir="auto"
          rows={4}
          value={caption}
          onChange={(event) => setCaption(event.target.value)}
          aria-invalid={problems.caption ? true : undefined}
          aria-describedby={`${id}-caption-hint`}
          className={textareaClasses}
        />
        <p id={`${id}-caption-hint`} className={`text-xs ${problems.caption ? "text-rose-300" : "text-muted"}`}>
          {problems.caption ?? (counts || "Up to 30 hashtags and 20 mentions. You can leave it empty.")}
        </p>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">When</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {[false, true].map((value) => (
            <label key={String(value)} className={choice}>
              <input
                type="radio"
                name={`${id}-when`}
                checked={later === value}
                onChange={() => setLater(value)}
                className="accent-[var(--color-accent)]"
              />
              {value ? "Schedule for later" : "Post now"}
            </label>
          ))}
        </div>
        {later ? (
          <div className="space-y-1.5">
            <label htmlFor={`${id}-when-time`} className="block text-xs text-muted">
              Date and time, in your local time
            </label>
            <input
              id={`${id}-when-time`}
              type="datetime-local"
              value={when}
              onChange={(event) => setWhen(event.target.value)}
              aria-invalid={whenProblem ? true : undefined}
              className={`${inputClasses} max-w-64`}
            />
            {whenProblem ? <p className="text-sm text-rose-300">{whenProblem}</p> : null}
          </div>
        ) : null}
      </fieldset>

      {problems.duration ? <InlineAlert title="Not a length Instagram accepts">{problems.duration}</InlineAlert> : null}

      <InlineAlert tone="info" title="Before you post">
        The Reel is <strong className="font-medium text-foreground">public</strong> on your professional account and may
        appear in your feed — Instagram has no private option for posts made this way. Instagram processes the video
        first; PeakSift posts it as soon as it is ready, usually within a few minutes. PeakSift cannot edit or delete the
        Reel afterwards — use Instagram for that.
      </InlineAlert>

      <FormError>{error}</FormError>
      <Button type="submit" disabled={!valid || busy} className="w-full sm:w-auto">
        {later ? <CalendarClock aria-hidden="true" /> : <Send aria-hidden="true" />}
        {busy ? (later ? "Scheduling…" : "Starting…") : later ? "Schedule public Reel" : "Post public Reel"}
      </Button>
    </form>
  );
}

function InstagramJob({ job, onChange, onNew }: { job: PublishJob; onChange: (job: PublishJob) => void; onNew: () => void }) {
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      onChange(await getPublishJob(job.id));
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }, [job.id, onChange]);
  usePolling(isActive(job) || isFollowing(job), refresh, job.id);
  const stage = instagramStage(job);

  async function retry() {
    setRetrying(true);
    setError(null);
    try {
      onChange(await retryPublishJob(job.id));
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="flex items-center gap-2.5 text-sm text-foreground" role="status" aria-live="polite">
        {stage.tone === "working" ? <Spinner /> : null}
        <span className={stage.tone === "attention" ? "text-amber-200" : stage.tone === "done" ? "text-emerald-200" : ""}>
          {stage.label}
        </span>
      </p>
      {job.error_message && stage.tone === "attention" ? <InlineAlert title="What happened">{job.error_message}</InlineAlert> : null}
      {job.status === "published" && job.simulated ? (
        <p className="text-small text-muted">This server uses a simulated Instagram: nothing was posted.</p>
      ) : null}
      <FormError>{error}</FormError>
      <div className="flex flex-wrap gap-2">
        {job.retryable ? (
          <Button variant="secondary" onClick={retry} disabled={retrying}>
            <RotateCcw aria-hidden="true" />
            {retrying ? "Retrying…" : "Try again"}
          </Button>
        ) : null}
        {stage.tone !== "working" ? (
          <Button variant="ghost" onClick={onNew}>
            Post again with another caption
          </Button>
        ) : null}
      </div>
    </div>
  );
}
