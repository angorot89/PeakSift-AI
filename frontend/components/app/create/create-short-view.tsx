"use client";

import { Clapperboard, Palette, Pencil, RotateCcw, Wand2, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CreateSteps } from "@/components/app/create/create-steps";
import { EmptyState, ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { WorkingState } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { selectClasses } from "@/components/ui/select-styles";
import { errorMessage } from "@/lib/api";
import { listTemplates, type Template } from "@/lib/brand";
import { summary } from "@/lib/template-rules";
import { autoEditHref } from "@/lib/auto-edit";
import { clipContentUrl, friendlyClipError, isClipActive, retryClip, type GeneratedClip } from "@/lib/clips";
import { editorHref } from "@/lib/edits";
import { formatDuration } from "@/lib/format";
import { projectHref } from "@/lib/navigation";
import { loadProjectClip } from "@/lib/project-clip";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";

function Choice({
  href,
  icon: Icon,
  title,
  description,
  recommended,
  disabled,
}: {
  href: string;
  icon: LucideIcon;
  title: string;
  description: string;
  recommended?: boolean;
  disabled: boolean;
}) {
  const body = (
    <>
      <span className={`flex size-11 shrink-0 items-center justify-center rounded-block ${recommended ? "bg-accent/15 text-accent-soft" : "bg-surface-3 text-muted"}`}>
        <Icon aria-hidden="true" className="size-5" />
      </span>
      <span className="min-w-0">
        <span className="flex flex-wrap items-center gap-2 text-title">
          {title}
          {recommended ? (
            <span className="rounded-full bg-accent/15 px-2 py-0.5 text-caption font-medium text-accent-soft">Recommended</span>
          ) : null}
        </span>
        <span className="mt-1 block text-sm text-pretty text-muted">{description}</span>
      </span>
    </>
  );
  const shape = `flex h-full gap-4 rounded-card border p-5 text-left ${
    recommended ? "border-accent/50 bg-accent/[0.05]" : "border-border bg-surface"
  }`;
  if (disabled) {
    return (
      <div aria-disabled="true" className={`${shape} opacity-60`}>
        {body}
      </div>
    );
  }
  return (
    <Link
      href={href}
      className={`${shape} transition-colors hover:border-accent/70 hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`}
    >
      {body}
    </Link>
  );
}

/**
 * /projects/[id]/clips/[clipId]/create — the start of making a Short: the clip (prepared if it is
 * still rendering), then Auto Edit (recommended) or starting by hand.
 */
export function CreateShortView() {
  const { id, clipId } = useParams<{ id: string; clipId: string }>();
  const load = useCallback(() => loadProjectClip(id, clipId), [id, clipId]);
  const { data, error, loading, reload } = useApi(load);
  // The latest polled or retried state of the clip, once there is one.
  const [clip, setClip] = useState<GeneratedClip | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  // V1.7: the template a new Short starts from — the creator's default, changeable here.
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [changing, setChanging] = useState(false);
  useEffect(() => {
    let cancelled = false;
    listTemplates()
      .then((list) => {
        if (cancelled) return;
        setTemplates(list);
        setTemplateId(list.find((t) => t.is_default)?.id ?? null);
      })
      .catch(() => !cancelled && setTemplates([])); // Auto Edit works without templates
    return () => {
      cancelled = true;
    };
  }, []);
  const chosen = templates?.find((t) => t.id === templateId) ?? null;
  const current = clip ?? data?.clip ?? null;
  const preparing = !!current && isClipActive(current.status) && !current.is_stale;
  usePolling(preparing, async () => setClip((await loadProjectClip(id, clipId)).clip), clipId);

  async function retry() {
    if (!current) return;
    setBusy(true);
    setActionError(null);
    try {
      setClip(await retryClip(id, current.video_id, current.run_id, current.candidate_id));
    } catch (failure) {
      setActionError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  if (loading && !current) {
    return (
      <div role="status" aria-label="Loading the clip" className="space-y-4">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-64 rounded-card" />
      </div>
    );
  }
  if (error || !current) {
    const notFound = error === "Clip not found" || error === "Project not found";
    return notFound ? (
      <EmptyState
        icon={Clapperboard}
        title="Clip not found"
        description="This clip does not exist or you do not have access to it."
        action={<Link href={projectHref(id, "clips")} className="text-sm text-accent-soft hover:underline">Back to clips</Link>}
      />
    ) : (
      <ErrorState title="This clip could not be loaded" message={error ?? "Try again."} onRetry={reload} />
    );
  }

  const ready = current.status === "ready";
  const failed = current.status === "failed" || current.is_stale;
  return (
    <div className="space-y-8">
      <div className="space-y-4">
        <CreateSteps current={0} />
        <div>
          <h1 className="text-page text-balance">Create a Short</h1>
          <p className="mt-1 text-sm text-muted">
            <span className="text-foreground">{current.title}</span>
            <span className="tabular"> · {formatDuration(current.duration_seconds)}</span>
          </p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_16rem]">
        <section aria-labelledby="start-heading" className="min-w-0 space-y-4">
          <h2 id="start-heading" className="text-section">How do you want to start?</h2>
          <div className="grid gap-3 md:grid-cols-2">
            <Choice
              href={`${autoEditHref(id, current.id)}?new=1&template=${chosen?.id ?? "none"}`}
              icon={Wand2}
              title="Auto Edit"
              recommended
              disabled={!ready}
              description={
                chosen
                  ? `Starts from your “${chosen.name}” template. You can change everything before rendering.`
                  : "PeakSift will prepare framing, captions, visuals and sound. You can change everything before rendering."
              }
            />
            <Choice
              href={editorHref(id, current.id)}
              icon={Pencil}
              title="Start manually"
              disabled={!ready}
              description="Open the editor with sensible defaults and choose every setting yourself."
            />
          </div>
          {templates && templates.length > 0 ? (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-block border border-border bg-surface px-4 py-3 text-sm">
              <Palette aria-hidden="true" className="size-4 shrink-0 text-accent-soft" />
              {changing ? (
                <>
                  <label htmlFor="start-template" className="text-muted">
                    Start from
                  </label>
                  <select
                    id="start-template"
                    value={templateId ?? "none"}
                    onChange={(e) => {
                      setTemplateId(e.target.value === "none" ? null : e.target.value);
                      setChanging(false);
                    }}
                    className={`${selectClasses} w-full sm:w-72`}
                  >
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                        {t.is_default ? " (default)" : ""}
                      </option>
                    ))}
                    <option value="none">No template</option>
                  </select>
                </>
              ) : (
                <>
                  <span className="min-w-0 flex-1 text-muted">
                    Using: <span className="font-medium text-foreground">{chosen ? chosen.name : "No template"}</span>
                    {chosen ? <span className="block text-caption text-subtle">{summary(chosen.config, Boolean(chosen.brand?.has_logo))}</span> : null}
                  </span>
                  <Button size="sm" variant="ghost" onClick={() => setChanging(true)}>
                    Change<span className="sr-only"> template</span>
                  </Button>
                </>
              )}
            </div>
          ) : null}
          {preparing ? (
            <div className="rounded-card border border-border bg-surface p-4">
              <WorkingState
                label={current.status === "queued" ? "Waiting to start" : "Cutting your clip"}
                progress={current.status === "queued" ? null : current.progress_percent}
                progressLabel="Clip progress"
                detail="Cutting this moment from your video. Both options open as soon as it is ready."
              />
            </div>
          ) : null}
          {failed ? (
            <InlineAlert
              title="This clip couldn't be prepared"
              action={
                <Button size="sm" variant="secondary" onClick={() => void retry()} disabled={busy}>
                  <RotateCcw aria-hidden="true" />
                  {busy ? "Retrying…" : "Try again"}
                </Button>
              }
            >
              {current.status === "failed" ? friendlyClipError(current) : "The work stopped responding."} Nothing else was changed.
            </InlineAlert>
          ) : null}
          {actionError ? <InlineAlert title="That didn't work">{actionError}</InlineAlert> : null}
        </section>
        <aside aria-label="The clip" className="min-w-0">
          <div className="mx-auto aspect-video w-full overflow-hidden rounded-block border border-border bg-black lg:max-w-none">
            {ready ? (
              <video
                controls
                playsInline
                preload="metadata"
                src={`${clipContentUrl(current.id)}#t=0.1`}
                className="size-full object-contain"
                aria-label={`Preview of the clip ${current.title}`}
              />
            ) : (
              <div className="flex size-full items-center justify-center text-subtle">
                <Clapperboard aria-hidden="true" className="size-6" />
              </div>
            )}
          </div>
          <p className="mt-2 text-caption text-subtle">The original clip, before vertical framing.</p>
        </aside>
      </div>
    </div>
  );
}
