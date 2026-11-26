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
import { ProgressBar, Spinner } from "@/components/ui/progress";
import { errorMessage } from "@/lib/api";
import { getPublishJob, isActive, isFollowing, retryPublishJob, type PublishJob, type PublishPanel } from "@/lib/publishing";
import { fromLocalInput, suggestedTime, timeProblem, toLocalInput } from "@/lib/schedule-rules";
import {
  EMPTY_TIKTOK_FORM,
  TIKTOK_CAPTION_MAX,
  commercialNotice,
  getTikTokCreator,
  getTikTokPanel,
  privacyChoices,
  publishToTikTok,
  tiktokOptions,
  tiktokProblems,
  tiktokStage,
  type TikTokCreator,
  type TikTokForm,
  type TikTokPrivacy,
} from "@/lib/tiktok";
import { usePolling } from "@/lib/use-polling";

const MUSIC_TERMS = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en";
const BRANDED_POLICY = "https://www.tiktok.com/legal/page/global/bc-policy/en";

const check =
  "flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg border border-border px-3 text-sm has-[:checked]:border-accent/60 has-[:checked]:bg-accent/10 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50";

/** The TikTok side of the publish dialog: connect, review the post, then its real state. */
export function TikTokPublish({
  editId,
  durationSeconds = null,
  initialWhen,
}: {
  editId: string;
  durationSeconds?: number | null;
  initialWhen?: string;
}) {
  const [panel, setPanel] = useState<PublishPanel | null>(null);
  const [creator, setCreator] = useState<TikTokCreator | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [job, setJob] = useState<PublishJob | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getTikTokPanel(editId);
        if (cancelled) return;
        setPanel(data);
        const waiting = data.jobs.find((item) => item.status === "scheduled");
        const latest = data.jobs[0];
        if (waiting) setJob(waiting);
        else if (latest && (isActive(latest) || isFollowing(latest))) setJob(latest);
        // Ask TikTok what this creator may choose only when a post can actually be made.
        if (data.enabled && data.connection?.status === "connected" && data.edit_ready) {
          const info = await getTikTokCreator();
          if (!cancelled) setCreator(info);
        }
      } catch (failure) {
        if (!cancelled) setLoadError(errorMessage(failure));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [editId]);

  if (loadError) return <InlineAlert title="TikTok is unavailable right now">{loadError}</InlineAlert>;
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
        title={reconnect ? "Reconnect your TikTok account" : "Connect a TikTok account"}
        action={<ButtonLink href="/settings#tiktok">{reconnect ? "Reconnect" : "Connect"} in Settings</ButtonLink>}
      >
        {reconnect
          ? "TikTok no longer accepts PeakSift's access. Connect again, then come back to this Short."
          : "Connect once in Settings, then come back to this Short to post it."}
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
          It goes to TikTok with the caption and visibility you reviewed.{" "}
          <Link href="/schedule" className="text-accent-soft underline underline-offset-2 hover:text-foreground">
            Open the schedule
          </Link>
        </p>
      </div>
    );
  }
  if (job) return <TikTokJob job={job} onChange={setJob} onNew={() => setJob(null)} />;
  if (!creator) {
    return (
      <div role="status" className="flex items-center gap-2 text-sm text-muted">
        <Spinner /> Asking TikTok what you can choose…
      </div>
    );
  }
  return (
    <TikTokPostForm
      editId={editId}
      panel={panel}
      creator={creator}
      durationSeconds={durationSeconds}
      initialWhen={initialWhen}
      onPublished={setJob}
    />
  );
}

function TikTokPostForm({
  editId,
  panel,
  creator,
  durationSeconds,
  initialWhen,
  onPublished,
}: {
  editId: string;
  panel: PublishPanel;
  creator: TikTokCreator;
  durationSeconds: number | null;
  initialWhen?: string;
  onPublished: (job: PublishJob) => void;
}) {
  const id = useId();
  const [form, setForm] = useState<TikTokForm>({ ...EMPTY_TIKTOK_FORM, caption: panel.defaults.description });
  const [later, setLater] = useState(Boolean(initialWhen));
  const [when, setWhen] = useState(() => initialWhen ?? toLocalInput(suggestedTime(new Date())));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tried, setTried] = useState(false);
  const set = <K extends keyof TikTokForm>(key: K, value: TikTokForm[K]) => setForm((previous) => ({ ...previous, [key]: value }));

  const problems = tiktokProblems(form, creator, durationSeconds);
  const whenProblem = later ? timeProblem(when, new Date()) : null;
  const valid = Object.keys(problems).length === 0 && !whenProblem;
  const notice = commercialNotice(form);
  const levels = privacyChoices(creator, form);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setTried(true);
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      const scheduledAt = later ? fromLocalInput(when)?.toISOString() : undefined;
      onPublished(
        await publishToTikTok(editId, panel.defaults.title, form.caption.trim(), tiktokOptions(form, creator), scheduledAt),
      );
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  const switches: { key: "allowComment" | "allowDuet" | "allowStitch"; label: string; off: boolean }[] = [
    { key: "allowComment", label: "Comments", off: creator.comment_disabled },
    { key: "allowDuet", label: "Duets", off: creator.duet_disabled },
    { key: "allowStitch", label: "Stitches", off: creator.stitch_disabled },
  ];

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <p className="text-sm text-muted">
        Posting as{" "}
        <span dir="auto" className="font-medium text-foreground">
          {creator.nickname || creator.username || "your TikTok account"}
        </span>
        {creator.username ? <span className="text-subtle"> · @{creator.username}</span> : null}
      </p>

      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <label htmlFor={`${id}-caption`} className="text-sm font-medium">
            Caption
          </label>
          <span className={`tabular text-xs ${problems.caption ? "text-rose-300" : "text-subtle"}`}>
            {form.caption.length} / {TIKTOK_CAPTION_MAX}
          </span>
        </div>
        <textarea
          id={`${id}-caption`}
          dir="auto"
          rows={4}
          value={form.caption}
          onChange={(event) => set("caption", event.target.value)}
          aria-invalid={problems.caption ? true : undefined}
          aria-describedby={`${id}-caption-hint`}
          className={textareaClasses}
        />
        <p id={`${id}-caption-hint`} className="text-xs text-muted">
          {problems.caption ?? "Hashtags and mentions go here. You can leave it empty."}
        </p>
      </div>

      <div className="space-y-1.5">
        <label htmlFor={`${id}-privacy`} className="block text-sm font-medium">
          Who can see this post
        </label>
        <select
          id={`${id}-privacy`}
          value={form.privacy}
          onChange={(event) => set("privacy", event.target.value as TikTokPrivacy | "")}
          aria-invalid={tried && problems.privacy ? true : undefined}
          aria-describedby={tried && problems.privacy ? `${id}-privacy-error` : undefined}
          className={`${inputClasses} max-w-sm`}
        >
          {/* TikTok requires the creator to choose: nothing is preselected. */}
          <option value="" disabled>
            Choose…
          </option>
          {levels.map((level) => (
            <option key={level.value} value={level.value} disabled={level.disabled}>
              {level.label}
              {level.disabled ? " (not for branded content)" : ""}
            </option>
          ))}
        </select>
        {tried && problems.privacy ? (
          <p id={`${id}-privacy-error`} className="text-sm text-rose-300">{problems.privacy}</p>
        ) : null}
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Allow others to</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {switches.map((item) => (
            <label key={item.key} className={check}>
              <input
                type="checkbox"
                checked={form[item.key] && !item.off}
                disabled={item.off}
                onChange={(event) => set(item.key, event.target.checked)}
                className="accent-[var(--color-accent)]"
              />
              {item.label === "Comments" ? "Comment" : item.label === "Duets" ? "Duet" : "Stitch"}
            </label>
          ))}
        </div>
        {switches.some((item) => item.off) ? (
          <p className="text-xs text-muted">
            {switches.filter((item) => item.off).map((item) => item.label).join(" and ")} are turned off in your TikTok
            settings.
          </p>
        ) : null}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Commercial content</legend>
        <label className={check}>
          <input
            type="checkbox"
            checked={form.commercial}
            onChange={(event) => set("commercial", event.target.checked)}
            className="accent-[var(--color-accent)]"
          />
          This post promotes a brand, product or service
        </label>
        {form.commercial ? (
          <div className="grid gap-2 sm:grid-cols-2">
            <label className={check}>
              <input
                type="checkbox"
                checked={form.yourBrand}
                onChange={(event) => set("yourBrand", event.target.checked)}
                className="accent-[var(--color-accent)]"
              />
              Your own brand
            </label>
            <label className={check}>
              <input
                type="checkbox"
                checked={form.brandedContent}
                onChange={(event) => set("brandedContent", event.target.checked)}
                className="accent-[var(--color-accent)]"
              />
              Branded content (a paid partnership)
            </label>
          </div>
        ) : null}
        {problems.commercial ? <p className="text-sm text-rose-300">{problems.commercial}</p> : null}
        {notice ? <p className="text-xs text-muted">{notice}</p> : null}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">When</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {[false, true].map((value) => (
            <label key={String(value)} className={check}>
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

      {problems.duration ? <InlineAlert title="Too long for your TikTok account">{problems.duration}</InlineAlert> : null}

      <label className="flex cursor-pointer items-start gap-2.5 text-sm">
        <input
          type="checkbox"
          checked={form.musicConfirmed}
          onChange={(event) => set("musicConfirmed", event.target.checked)}
          aria-invalid={tried && problems.music ? true : undefined}
          className="mt-0.5 size-4 accent-[var(--color-accent)]"
        />
        <span className="text-pretty text-muted">
          By posting, you agree to TikTok&apos;s{" "}
          <a href={MUSIC_TERMS} target="_blank" rel="noreferrer" className="text-accent-soft underline underline-offset-2">
            Music Usage Confirmation
          </a>
          {form.commercial && form.brandedContent ? (
            <>
              {" "}
              and{" "}
              <a href={BRANDED_POLICY} target="_blank" rel="noreferrer" className="text-accent-soft underline underline-offset-2">
                Branded Content Policy
              </a>
            </>
          ) : null}
          .
        </span>
      </label>
      {tried && problems.music ? <p className="text-sm text-rose-300">{problems.music}</p> : null}

      <InlineAlert tone="info" title="Before you post">
        The Short goes to your TikTok account with this caption and visibility. TikTok may take a few minutes to process
        it. Until TikTok has reviewed PeakSift, it only accepts posts that are visible to you alone, on private accounts.
        PeakSift cannot edit or delete the post afterwards — use TikTok for that.
      </InlineAlert>

      <FormError>{error}</FormError>
      <Button type="submit" disabled={busy || Boolean(problems.duration)} className="w-full sm:w-auto">
        {later ? <CalendarClock aria-hidden="true" /> : <Send aria-hidden="true" />}
        {busy ? (later ? "Scheduling…" : "Starting…") : later ? "Schedule TikTok post" : "Post to TikTok"}
      </Button>
    </form>
  );
}

function TikTokJob({ job, onChange, onNew }: { job: PublishJob; onChange: (job: PublishJob) => void; onNew: () => void }) {
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
  const stage = tiktokStage(job);

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
      {job.status === "uploading" && !job.is_stale ? (
        <ProgressBar value={job.progress_percent} label="Upload progress" />
      ) : null}
      {job.error_message && stage.tone === "attention" ? <InlineAlert title="What happened">{job.error_message}</InlineAlert> : null}
      {job.status === "published" && job.simulated ? (
        <p className="text-small text-muted">This server uses a simulated TikTok: nothing was posted.</p>
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
            Post again with other choices
          </Button>
        ) : null}
      </div>
    </div>
  );
}
