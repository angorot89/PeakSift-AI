"use client";

import { CalendarClock, CheckCircle2, CirclePlay, ExternalLink, RotateCcw, Send } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useId, useState } from "react";
import { ScheduledPost } from "@/components/app/schedule/scheduled-post";
import { InstagramPublish } from "@/components/app/instagram/instagram-publish";
import { TikTokPublish } from "@/components/app/tiktok/tiktok-publish";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { inputClasses, textareaClasses } from "@/components/ui/input-styles";
import { ButtonLink } from "@/components/ui/button-link";
import { buttonClasses } from "@/components/ui/button-styles";
import { FormError } from "@/components/ui/form-error";
import { InlineAlert } from "@/components/ui/inline-alert";
import { ProgressBar, Spinner } from "@/components/ui/progress";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { errorMessage } from "@/lib/api";
import {
  bytes,
  characters,
  connectYouTube,
  DESCRIPTION_MAX_BYTES,
  getPublishJob,
  getPlatforms,
  getPublishPanel,
  isActive,
  isFollowing,
  metadataProblems,
  parseTags,
  type Privacy,
  privacyLabel,
  publishEdit,
  type PublishJob,
  type PublishPanel,
  retryPublishJob,
  stageLabel,
  TAGS_MAX,
  tagsLength,
  TITLE_MAX,
} from "@/lib/publishing";
import { fromLocalInput, suggestedTime, timeProblem, toLocalInput } from "@/lib/schedule-rules";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";

const STEPS: { key: string; label: string }[] = [
  { key: "preparing", label: "Prepare" },
  { key: "uploading", label: "Upload" },
  { key: "uploaded", label: "Uploaded" },
  { key: "published", label: "Published" },
];
const STEP_INDEX: Record<string, number> = {
  queued: 0, preparing: 0, uploading: 1, uploaded: 2, processing: 2, published: 3,
};

/** "Publish to YouTube" beside Download: the reviewed metadata, then the real job state. */
export function PublishToYouTube({
  editId,
  editName,
  returnTo,
}: {
  editId: string;
  editName: string;
  /** Where to come back to after connecting YouTube (the page this dialog is on). */
  returnTo?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)} aria-haspopup="dialog">
        <CirclePlay aria-hidden="true" />
        Publish to YouTube
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Publish" description={editName}>
        <PublishBody editId={editId} onClose={() => setOpen(false)} returnTo={returnTo} />
      </Dialog>
    </>
  );
}

type PlatformKey = "youtube" | "tiktok" | "instagram";

/**
 * The publish dialog's content. Where this server also offers TikTok, the creator first
 * chooses the platform; each platform then has its own reviewed post and its own real state.
 */
export function PublishBody(props: {
  editId: string;
  onClose: () => void;
  returnTo?: string;
  /** Open on "Schedule for later" with this time (a datetime-local value), e.g. the next posting slot. */
  initialWhen?: string;
  /** The Short's length, checked against the creator's TikTok limit. */
  durationSeconds?: number | null;
  /** Called once with the new post when the creator publishes or schedules it (the review queue). */
  onPosted?: (job: PublishJob) => void;
  /** Start on this platform instead of YouTube. */
  initialPlatform?: PlatformKey;
}) {
  const { data } = useApi(getPlatforms);
  const [chosen, setChosen] = useState<PlatformKey | null>(props.initialPlatform ?? null);
  const offered = (data ?? []).filter((platform) => platform.enabled);
  // One platform on this server: no choice to make. YouTube stays the default when offered.
  const platform: PlatformKey =
    chosen ?? (offered.some((item) => item.key === "youtube") ? "youtube" : (offered[0]?.key ?? "youtube"));
  return (
    <div className="space-y-5">
      {offered.length > 1 ? (
        <SegmentedControl
          label="Where to publish"
          value={platform}
          onChange={setChosen}
          options={offered.map((item) => ({ value: item.key, label: item.label }))}
        />
      ) : null}
      {platform === "tiktok" ? (
        <TikTokPublish editId={props.editId} durationSeconds={props.durationSeconds} initialWhen={props.initialWhen} onPosted={props.onPosted} />
      ) : platform === "instagram" ? (
        <InstagramPublish editId={props.editId} durationSeconds={props.durationSeconds} initialWhen={props.initialWhen} onPosted={props.onPosted} />
      ) : (
        <YouTubePublishBody
          editId={props.editId}
          onClose={props.onClose}
          returnTo={props.returnTo}
          initialWhen={props.initialWhen}
          onPosted={props.onPosted}
        />
      )}
    </div>
  );
}

function YouTubePublishBody({
  editId,
  onClose,
  returnTo,
  initialWhen,
  onPosted,
}: {
  editId: string;
  onClose: () => void;
  returnTo?: string;
  /** Open on "Schedule for later" with this time (a datetime-local value), e.g. the next posting slot. */
  initialWhen?: string;
  onPosted?: (job: PublishJob) => void;
}) {
  const [panel, setPanel] = useState<PublishPanel | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [job, setJob] = useState<PublishJob | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPublishPanel(editId)
      .then((data) => {
        if (cancelled) return;
        setPanel(data);
        // Show the latest job still in flight (or just finished) instead of a blank form.
        const latest = data.jobs[0];
        const waiting = data.jobs.find((item) => item.status === "scheduled");
        if (waiting) setJob(waiting); // one Short has at most one post waiting for its time
        else if (latest && (isActive(latest) || isFollowing(latest))) setJob(latest);
      })
      .catch((failure) => !cancelled && setLoadError(errorMessage(failure)));
    return () => {
      cancelled = true;
    };
  }, [editId]);

  if (loadError) return <InlineAlert title="Publishing is unavailable">{loadError}</InlineAlert>;
  if (!panel) {
    return (
      <div role="status" className="flex items-center gap-2 text-sm text-muted">
        <Spinner /> Loading…
      </div>
    );
  }
  if (!panel.enabled) {
    return (
      <InlineAlert tone="info" title="Publishing is not enabled on this server">
        Download the short and upload it yourself in the meantime.
      </InlineAlert>
    );
  }
  if (!panel.connection || panel.connection.status !== "connected") {
    const reconnect = panel.connection?.status === "needs_reconnect";
    return (
      <InlineAlert
        tone="info"
        title={reconnect ? "Reconnect your YouTube account" : "Connect a YouTube account"}
        action={
          returnTo ? (
            <ConnectButton returnTo={returnTo} reconnect={reconnect} />
          ) : (
            <ButtonLink href="/settings#youtube">{reconnect ? "Reconnect" : "Connect"} in Settings</ButtonLink>
          )
        }
      >
        {reconnect
          ? "Google no longer accepts PeakSift's access (it was removed or expired)."
          : "PeakSift needs permission to upload to your channel. It asks for upload access only."}
      </InlineAlert>
    );
  }
  if (!panel.edit_ready) {
    return (
      <InlineAlert tone="info" title="This short is not ready">
        Render it first; only a finished short can be published.
      </InlineAlert>
    );
  }
  if (job?.status === "scheduled") {
    return (
      <div className="space-y-4">
        <ScheduledPost job={job} onChange={setJob} onCancelled={() => setJob(null)} />
        <p className="text-small text-muted">
          It goes out with the title, description and visibility you reviewed.{" "}
          <Link href="/schedule" className="text-accent-soft underline underline-offset-2 hover:text-foreground">
            Open the schedule
          </Link>
        </p>
      </div>
    );
  }
  if (job) return <JobProgress job={job} onChange={setJob} onClose={onClose} onNew={() => setJob(null)} />;
  return (
    <PublishForm
      editId={editId}
      panel={panel}
      initialWhen={initialWhen}
      onPublished={(next) => {
        setJob(next);
        onPosted?.(next);
      }}
    />
  );
}

/** Opens Google's consent; afterwards the browser comes back to `returnTo`. */
function ConnectButton({ returnTo, reconnect }: { returnTo: string; reconnect: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-2">
      <Button
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await connectYouTube(returnTo);
          } catch (failure) {
            setError(errorMessage(failure));
            setBusy(false);
          }
        }}
        disabled={busy}
      >
        {busy ? "Opening Google…" : reconnect ? "Reconnect YouTube" : "Connect YouTube"}
      </Button>
      <FormError>{error}</FormError>
    </div>
  );
}

function PublishForm({
  editId,
  panel,
  onPublished,
  initialWhen,
}: {
  editId: string;
  panel: PublishPanel;
  onPublished: (job: PublishJob) => void;
  initialWhen?: string;
}) {
  const id = useId();
  const [title, setTitle] = useState(panel.defaults.title);
  const [description, setDescription] = useState(panel.defaults.description);
  const [tagText, setTagText] = useState(panel.defaults.tags.join(", "));
  const [privacy, setPrivacy] = useState<Privacy>(panel.defaults.privacy);
  const [madeForKids, setMadeForKids] = useState(panel.defaults.made_for_kids);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // When: now, or at a time the creator picks (their local time).
  const [later, setLater] = useState(Boolean(initialWhen));
  const [when, setWhen] = useState(() => initialWhen ?? toLocalInput(suggestedTime(new Date())));

  const metadata = { title, description, tags: parseTags(tagText), privacy, made_for_kids: madeForKids };
  const problems = metadataProblems(metadata);
  const whenProblem = later ? timeProblem(when, new Date()) : null;
  const valid = Object.keys(problems).length === 0 && !whenProblem;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      const scheduledAt = later ? fromLocalInput(when)?.toISOString() : undefined;
      onPublished(
        await publishEdit(editId, { ...metadata, title: title.trim(), description: description.trim() }, scheduledAt),
      );
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  const counter = (text: string, ok: boolean) => (
    <span className={`tabular text-xs ${ok ? "text-subtle" : "text-rose-300"}`}>{text}</span>
  );

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <label htmlFor={`${id}-title`} className="text-sm font-medium">Title</label>
          {counter(`${characters(title.trim())} / ${TITLE_MAX}`, !problems.title)}
        </div>
        <input
          id={`${id}-title`}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          aria-invalid={problems.title ? true : undefined}
          aria-describedby={problems.title ? `${id}-title-error` : undefined}
          className={inputClasses}
        />
        {problems.title ? <p id={`${id}-title-error`} className="text-sm text-rose-300">{problems.title}</p> : null}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <label htmlFor={`${id}-description`} className="text-sm font-medium">Description</label>
          {counter(`${bytes(description.trim())} / ${DESCRIPTION_MAX_BYTES} bytes`, !problems.description)}
        </div>
        <textarea
          id={`${id}-description`}
          value={description}
          rows={4}
          onChange={(event) => setDescription(event.target.value)}
          aria-invalid={problems.description ? true : undefined}
          aria-describedby={problems.description ? `${id}-description-error` : undefined}
          className={textareaClasses}
        />
        {problems.description ? (
          <p id={`${id}-description-error`} className="text-sm text-rose-300">{problems.description}</p>
        ) : null}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <label htmlFor={`${id}-tags`} className="text-sm font-medium">
            Tags <span className="font-normal text-muted">(comma-separated, optional)</span>
          </label>
          {counter(`${tagsLength(metadata.tags)} / ${TAGS_MAX}`, !problems.tags)}
        </div>
        <input
          id={`${id}-tags`}
          value={tagText}
          onChange={(event) => setTagText(event.target.value)}
          aria-invalid={problems.tags ? true : undefined}
          aria-describedby={problems.tags ? `${id}-tags-error` : undefined}
          className={inputClasses}
        />
        {problems.tags ? <p id={`${id}-tags-error`} className="text-sm text-rose-300">{problems.tags}</p> : null}
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Visibility</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {(["private", "unlisted", "public"] as const).map((option) => (
            <label
              key={option}
              className="flex min-h-11 cursor-pointer items-center gap-2 rounded-control border border-border px-3 text-sm has-[:checked]:border-accent/60 has-[:checked]:bg-accent/10"
            >
              <input
                type="radio"
                name={`${id}-privacy`}
                value={option}
                checked={privacy === option}
                onChange={() => setPrivacy(option)}
                className="accent-[var(--color-accent)]"
              />
              {privacyLabel(option)}
              {option === "private" ? <span className="text-xs text-muted">(default)</span> : null}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Audience</legend>
        <p className="text-xs text-muted">YouTube requires you to say whether the video is made for kids.</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {[false, true].map((value) => (
            <label
              key={String(value)}
              className="flex min-h-11 cursor-pointer items-center gap-2 rounded-control border border-border px-3 text-sm has-[:checked]:border-accent/60 has-[:checked]:bg-accent/10"
            >
              <input
                type="radio"
                name={`${id}-kids`}
                checked={madeForKids === value}
                onChange={() => setMadeForKids(value)}
                className="accent-[var(--color-accent)]"
              />
              {value ? "Yes, it's made for kids" : "No, it's not made for kids"}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">When</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {[false, true].map((value) => (
            <label
              key={String(value)}
              className="flex min-h-11 cursor-pointer items-center gap-2 rounded-control border border-border px-3 text-sm has-[:checked]:border-accent/60 has-[:checked]:bg-accent/10"
            >
              <input
                type="radio"
                name={`${id}-when`}
                checked={later === value}
                onChange={() => setLater(value)}
                className="accent-[var(--color-accent)]"
              />
              {value ? "Schedule for later" : "Publish now"}
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
              aria-describedby={whenProblem ? `${id}-when-error` : undefined}
              className={`${inputClasses} max-w-64`}
            />
            {whenProblem ? <p id={`${id}-when-error`} className="text-sm text-rose-300">{whenProblem}</p> : null}
          </div>
        ) : null}
      </fieldset>

      <InlineAlert tone="info" title="Before you publish">
        The short goes to your connected channel with this title, description and visibility. Google keeps videos
        uploaded through apps it has not yet verified <strong className="font-medium text-foreground">private</strong>,
        whatever visibility you choose, until the app is verified. PeakSift cannot edit or delete the video afterwards —
        use YouTube Studio for that.
      </InlineAlert>

      <FormError>{error}</FormError>
      <Button type="submit" disabled={!valid || busy} className="w-full sm:w-auto">
        {later ? <CalendarClock aria-hidden="true" /> : <Send aria-hidden="true" />}
        {busy
          ? later
            ? "Scheduling…"
            : "Starting…"
          : later
            ? `Schedule ${privacyLabel(privacy).toLowerCase()} post`
            : privacy === "private"
              ? "Publish privately"
              : `Publish as ${privacyLabel(privacy).toLowerCase()}`}
      </Button>
    </form>
  );
}

function JobProgress({
  job,
  onChange,
  onClose,
  onNew,
}: {
  job: PublishJob;
  onChange: (job: PublishJob) => void;
  onClose: () => void;
  onNew: () => void;
}) {
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

  const failed = job.status === "failed" || job.status === "provider_failed";
  const reached = failed ? -1 : STEP_INDEX[job.status];
  const done = job.status === "uploaded" || job.status === "published";

  return (
    <div className="space-y-5">
      <ol className="grid grid-cols-4 gap-2" aria-label="Publishing steps">
        {STEPS.map((step, index) => {
          const state = index < reached || (done && index === reached) ? "done" : index === reached ? "current" : "todo";
          return (
            <li key={step.key} className="space-y-1.5 text-center" aria-current={state === "current" ? "step" : undefined}>
              <span
                className={`block h-1.5 rounded-full ${
                  state === "done" ? "bg-emerald-400" : state === "current" ? "bg-accent" : "bg-white/10"
                }`}
              />
              <span className={`block text-xs ${state === "todo" ? "text-subtle" : "text-foreground"}`}>{step.label}</span>
            </li>
          );
        })}
      </ol>

      <div role="status" aria-live="polite" className="space-y-3">
        <p className="flex items-center gap-2 text-sm font-medium">
          {done ? <CheckCircle2 aria-hidden="true" className="size-4 text-emerald-300" /> : isActive(job) ? <Spinner /> : null}
          {stageLabel(job)}
        </p>
        {job.status === "uploading" && job.bytes_total ? (
          <ProgressBar value={job.progress_percent} label={`Uploaded ${formatBytes(job.bytes_uploaded)} of ${formatBytes(job.bytes_total)}`} />
        ) : null}
        {isActive(job) ? (
          <p className="text-xs text-muted">You can close this window; the upload continues on the server.</p>
        ) : null}
      </div>

      {job.status === "uploaded" && !job.simulated && !job.awaiting_processing ? (
        <p className="text-sm text-muted">
          YouTube now processes the video. PeakSift has upload-only access, so it cannot see when processing finishes —
          check it in YouTube Studio.
        </p>
      ) : null}
      {job.simulated && done ? (
        <InlineAlert tone="info" title="Simulated upload">
          This server uses a test provider: nothing was sent to YouTube.
        </InlineAlert>
      ) : null}
      {failed ? (
        <InlineAlert
          tone={job.status === "provider_failed" ? "danger" : "warning"}
          title={stageLabel(job)}
          action={
            job.retryable ? (
              <Button variant="secondary" onClick={retry} disabled={retrying}>
                <RotateCcw aria-hidden="true" />
                {retrying ? "Retrying…" : "Retry"}
              </Button>
            ) : null
          }
        >
          {job.error_message}
        </InlineAlert>
      ) : null}
      {job.is_stale && job.retryable && !failed ? (
        <InlineAlert
          tone="warning"
          title="The upload stalled"
          action={
            <Button variant="secondary" onClick={retry} disabled={retrying}>
              <RotateCcw aria-hidden="true" />
              {retrying ? "Resuming…" : "Resume"}
            </Button>
          }
        >
          It resumes where YouTube stopped receiving it.
        </InlineAlert>
      ) : null}
      <FormError>{error}</FormError>

      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {job.video_url ? (
          <a href={job.video_url} target="_blank" rel="noopener noreferrer" className={buttonClasses("primary", "md")}>
            <ExternalLink aria-hidden="true" />
            Open on YouTube
          </a>
        ) : null}
        {job.studio_url ? (
          <a href={job.studio_url} target="_blank" rel="noopener noreferrer" className={buttonClasses("secondary", "md")}>
            <ExternalLink aria-hidden="true" />
            YouTube Studio
          </a>
        ) : null}
        {failed && !job.retryable ? (
          <Button variant="secondary" onClick={onNew}>
            Edit details and publish again
          </Button>
        ) : null}
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  );
}

function formatBytes(value: number): string {
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
