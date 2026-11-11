"use client";

import { CheckCircle2, CirclePlay, ExternalLink, Link2, RotateCcw, Send } from "lucide-react";
import { useCallback, useState } from "react";
import { PublishBody } from "@/components/app/editor/publish-dialog";
import { Button } from "@/components/ui/button";
import { buttonClasses } from "@/components/ui/button-styles";
import { Dialog } from "@/components/ui/dialog";
import { FormError } from "@/components/ui/form-error";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Panel } from "@/components/ui/panel";
import { ProgressBar, Spinner } from "@/components/ui/progress";
import { StatusPill } from "@/components/ui/status-pill";
import { errorMessage } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import {
  connectYouTube,
  getPublishJob,
  getPublishPanel,
  isActive,
  isFollowing,
  privacyLabel,
  type PublishJob,
  retryPublishJob,
} from "@/lib/publishing";
import { dayLabel, publishingView, type ShortDetail } from "@/lib/shorts";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-block border border-border bg-surface-2/60 px-3.5 py-2.5">
      <dt className="text-caption text-subtle">{label}</dt>
      <dd className="mt-0.5 text-sm break-words text-foreground">{children}</dd>
    </div>
  );
}

/**
 * The Short's publishing, in place: the YouTube connection, the real publishing state, the
 * reviewed title and visibility, and the one action that fits — Connect YouTube, Publish (review
 * → confirm in a dialog), Retry, Open on YouTube. Nothing publishes without the creator's click.
 */
export function PublishingPanel({ short, onChange }: { short: ShortDetail; onChange: () => void }) {
  const editId = short.edit_id;
  const loadPanel = useCallback(() => (editId ? getPublishPanel(editId) : Promise.resolve(null)), [editId]);
  const { data: panel, error: loadError, reload } = useApi(loadPanel);
  const [live, setLive] = useState<PublishJob | null>(null);
  const latest = panel?.jobs[0] ?? null;
  const job = live && latest && live.id === latest.id ? live : latest;
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const following = Boolean(job && (isActive(job) || isFollowing(job)));
  const follow = useCallback(async () => {
    if (!job) return;
    const next = await getPublishJob(job.id);
    setLive(next);
    if (!(isActive(next) || isFollowing(next))) onChange(); // the Short's status changed too
  }, [job, onChange]);
  usePolling(following, follow, job?.id ?? null);

  if (short.kind !== "short" || !editId) return null;

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      await connectYouTube(`/shorts/${short.id}`);
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  async function retry() {
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      setLive(await retryPublishJob(job.id));
      onChange();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  const view = panel ? publishingView(short, panel, job) : null;
  const status = view?.pill;
  return (
    <Panel
      id="publishing"
      title="Publishing"
      description={
        view && (view.state === "not_published" || view.action === "connect")
          ? "Publish to your YouTube channel when you're ready. Nothing is uploaded until you confirm."
          : undefined
      }
      status={status ? <StatusPill tone={status.tone}>{status.label}</StatusPill> : null}
    >
      {loadError ? (
        <InlineAlert title="Publishing details couldn't be loaded" action={<Button variant="secondary" size="sm" onClick={reload}>Try again</Button>}>
          {loadError}
        </InlineAlert>
      ) : !panel || !view ? (
        <p role="status" className="flex items-center gap-2 text-sm text-muted">
          <Spinner /> Loading publishing…
        </p>
      ) : (
        <div className="space-y-4">
          <dl className="grid gap-2 sm:grid-cols-2">
            <Fact label="YouTube">{view.connection}</Fact>
            <Fact label="Publishing">
              <span role="status" className="inline-flex items-center gap-1.5">
                {following ? <Spinner /> : view.state === "published" || view.state === "on_youtube" ? <CheckCircle2 aria-hidden="true" className="size-4 text-emerald-300" /> : null}
                {view.stage}
              </span>
            </Fact>
            {job && view.showMetadata ? (
              <>
                <Fact label="Title">{job.title}</Fact>
                <Fact label="Visibility">{privacyLabel(job.privacy)}</Fact>
              </>
            ) : null}
          </dl>

          {job && job.status === "uploading" && job.bytes_total && !job.is_stale ? (
            <ProgressBar value={job.progress_percent} label={`Uploaded ${formatBytes(job.bytes_uploaded)} of ${formatBytes(job.bytes_total)}`} />
          ) : null}
          {following ? <p className="text-small text-muted">You can leave this page; the upload continues.</p> : null}

          {view.state === "on_youtube" && job && !job.simulated ? (
            <p className="text-small text-muted">PeakSift has upload-only access, so it can&apos;t see when YouTube finishes processing. Check it in YouTube Studio.</p>
          ) : null}
          {job?.simulated && (view.state === "published" || view.state === "on_youtube") ? (
            <InlineAlert tone="info" title="Simulated upload">
              This server uses a test provider: nothing was sent to YouTube.
            </InlineAlert>
          ) : null}

          {view.state === "failed" || view.state === "stalled" ? (
            <InlineAlert
              tone={job?.status === "provider_failed" ? "danger" : "warning"}
              title={view.state === "stalled" ? "The upload stopped responding" : job?.status === "provider_failed" ? "YouTube couldn't publish it" : "The upload didn't finish"}
              action={
                job?.retryable ? (
                  <Button variant="secondary" onClick={retry} disabled={busy} data-publish-action>
                    <RotateCcw aria-hidden="true" />
                    {busy ? "Retrying…" : view.state === "stalled" ? "Resume" : "Retry"}
                  </Button>
                ) : null
              }
            >
              {job?.retryable
                ? "Retrying resumes the same upload: it never creates a second video."
                : "Review the details and publish again."}
              {job?.error_message ? (
                <details className="mt-1.5">
                  <summary className="inline-flex cursor-pointer items-center text-small pointer-coarse:min-h-11 pointer-coarse:min-w-11">Details</summary>
                  <p className="mt-1 text-small break-words">{job.error_message}</p>
                </details>
              ) : null}
            </InlineAlert>
          ) : null}

          {view.publishedOn ? (
            <p className="flex items-center gap-1.5 text-small text-muted">
              <CirclePlay aria-hidden="true" className="size-4 text-subtle" />
              YouTube · {view.publishedOn === "published" ? "Published" : "Uploaded"} {view.date ? dayLabel(view.date) : ""}
            </p>
          ) : null}
          <FormError>{error}</FormError>
          <div className="flex flex-wrap gap-2 empty:hidden">
            {view.action === "connect" ? (
              <Button onClick={connect} disabled={busy} data-publish-action>
                <Link2 aria-hidden="true" />
                {busy ? "Opening Google…" : view.reconnect ? "Reconnect YouTube" : "Connect YouTube"}
              </Button>
            ) : null}
            {view.action === "publish" || view.action === "publish_again" ? (
              <Button onClick={() => setOpen(true)} aria-haspopup="dialog" variant={view.action === "publish" ? "primary" : "secondary"} data-publish-action>
                <Send aria-hidden="true" />
                {view.action === "publish" ? "Publish" : "Publish again"}
              </Button>
            ) : null}
            {job?.video_url && (view.state === "published" || view.state === "on_youtube") ? (
              <a href={job.video_url} target="_blank" rel="noopener noreferrer" className={buttonClasses("secondary", "md")}>
                <ExternalLink aria-hidden="true" />
                Open on YouTube
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            ) : null}
          </div>

        </div>
      )}
      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
          reload();
          onChange();
        }}
        title="Publish to YouTube"
        description={short.title}
      >
        <PublishBody
          editId={editId}
          onClose={() => {
            setOpen(false);
            reload();
            onChange();
          }}
          returnTo={`/shorts/${short.id}`}
        />
      </Dialog>
    </Panel>
  );
}
