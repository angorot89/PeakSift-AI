"use client";

import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Check,
  CheckCircle2,
  Clapperboard,
  Film,
  Smartphone,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";
import { useProject } from "@/components/app/project/project-frame";
import { ErrorState } from "@/components/app/states";
import { StatusBadge } from "@/components/app/status-badge";
import { VideoUpload } from "@/components/app/video-upload";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { Card } from "@/components/ui/card";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Spinner } from "@/components/ui/progress";
import { SectionHeader } from "@/components/ui/section-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { errorMessage } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { projectHref } from "@/lib/navigation";
import { startTranscription } from "@/lib/transcription";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";
import {
  clock,
  editorLink,
  getProjectSummary,
  momentLabel,
  projectStage,
  relativeTime,
  shortLabel,
  STAGES,
  type NextAction,
  type ProjectSummary,
} from "@/lib/workspace";

const TONE: Record<NextAction["tone"], { icon: LucideIcon | null; className: string; eyebrow: string }> = {
  attention: { icon: AlertTriangle, className: "bg-danger/15 text-rose-200", eyebrow: "Needs attention" },
  action: { icon: ArrowRight, className: "bg-accent/15 text-accent-soft", eyebrow: "Next step" },
  waiting: { icon: null, className: "bg-surface-3 text-muted", eyebrow: "In progress" },
  done: { icon: CheckCircle2, className: "bg-success/15 text-emerald-200", eyebrow: "Done" },
};

/** The one next step: what it is, why, and the single primary action (or what is happening). */
function NextStep({ summary, onChanged }: { summary: ProjectSummary; onChanged: () => void }) {
  const next = summary.next_action;
  const tone = TONE[next.tone];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function transcribe() {
    if (!summary.source) return;
    setBusy(true);
    setError(null);
    try {
      await startTranscription(summary.id, summary.source.id);
      onChanged();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card padding="md" className="sm:p-6">
      <div className="flex gap-4">
        <span className={`hidden size-11 shrink-0 items-center justify-center rounded-xl sm:flex ${tone.className}`}>
          {tone.icon ? <tone.icon aria-hidden="true" className="size-5" /> : <Spinner />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-caption font-medium tracking-wide text-subtle uppercase">{tone.eyebrow}</p>
          <h2 className="mt-1 text-section" aria-live="polite">
            {next.title}
          </h2>
          <p className="mt-1 text-sm text-pretty text-muted">{next.description}</p>
          {next.key === "upload" ? (
            <div className="mt-5">
              <VideoUpload projectId={summary.id} onUploaded={onChanged} />
            </div>
          ) : next.key === "transcribe" ? (
            <div className="mt-5">
              <Button onClick={() => void transcribe()} disabled={busy}>
                {busy ? "Starting…" : next.cta}
              </Button>
            </div>
          ) : next.cta ? (
            <div className="mt-5">
              <ButtonLink href={next.href}>{next.cta}</ButtonLink>
            </div>
          ) : (
            <p className="mt-4 flex items-center gap-2 text-small text-subtle">
              <Spinner className="size-3.5" />
              This page updates by itself.
            </p>
          )}
          {error ? (
            <div className="mt-4">
              <InlineAlert title="That didn't start">{error}</InlineAlert>
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

/** Source → Clips → Edit → Publish → Learn: where the project is, every step reachable. */
function Workflow({ summary }: { summary: ProjectSummary }) {
  const stage = projectStage(summary);
  const short = summary.shorts.recent.find((s) => s.status === "ready") ?? summary.shorts.recent[0];
  const detail = [
    summary.source ? summary.source.filename : "Add a long video",
    summary.detection?.status === "completed"
      ? `${summary.detection.candidates} moment${summary.detection.candidates === 1 ? "" : "s"} · ${summary.clips.ready} clip${summary.clips.ready === 1 ? "" : "s"}`
      : summary.transcript?.status === "completed"
        ? "Transcript ready"
        : "Find the best moments",
    summary.shorts.total ? `${summary.shorts.ready} Short${summary.shorts.ready === 1 ? "" : "s"} ready` : "Turn a clip into a Short",
    summary.published.uploads || summary.published.with_analytics
      ? "On YouTube"
      : "Publish or download",
    summary.published.with_analytics ? "Analytics ready" : "See what worked",
  ];
  const links = [
    projectHref(summary.id, "source"),
    projectHref(summary.id, "clips"),
    short ? editorLink(summary.id, short.clip_id, short.edit_id) : projectHref(summary.id, "clips"),
    short ? editorLink(summary.id, short.clip_id, short.edit_id) : projectHref(summary.id, "clips"),
    projectHref(summary.id, "analytics"),
  ];
  return (
    <nav aria-label="Project progress">
      <ol className="grid gap-1 sm:grid-cols-5 lg:grid-cols-1">
        {STAGES.map((name, index) => {
          const state = index < stage ? "done" : index === stage ? "current" : "upcoming";
          return (
            <li key={name}>
              <Link
                href={links[index]}
                aria-current={state === "current" ? "step" : undefined}
                className={`flex min-h-11 items-center gap-3 rounded-xl px-2.5 py-2 transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent ${
                  state === "current" ? "bg-surface-2" : ""
                }`}
              >
                <span
                  className={`flex size-7 shrink-0 items-center justify-center rounded-full text-caption font-semibold ${
                    state === "done"
                      ? "bg-success/15 text-emerald-200"
                      : state === "current"
                        ? "bg-accent text-background"
                        : "bg-surface-3 text-subtle"
                  }`}
                >
                  {state === "done" ? <Check aria-hidden="true" className="size-3.5" strokeWidth={3} /> : index + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-foreground">
                    {name}
                    <span className="sr-only">{state === "done" ? " (done)" : state === "current" ? " (current)" : ""}</span>
                  </span>
                  <span className="block truncate text-caption text-subtle">{detail[index]}</span>
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
      <p className="mt-2 px-2.5 text-caption text-subtle">You can open any step at any time.</p>
    </nav>
  );
}

function BestMoments({ summary }: { summary: ProjectSummary }) {
  const top = summary.detection?.top ?? [];
  if (!top.length) return null;
  return (
    <section aria-labelledby="moments-heading">
      <SectionHeader
        id="moments-heading"
        title="Best moments"
        description="Ranked by PeakSift's editorial judgement of the transcript — not a prediction of views."
        actions={
          <Link href={projectHref(summary.id, "clips")} className="inline-flex min-h-11 items-center text-sm text-muted hover:text-foreground">
            All clips
          </Link>
        }
      />
      <ul className="space-y-2">
        {top.map((moment) => (
          <li key={moment.id}>
            <Link
              href={projectHref(summary.id, "clips")}
              className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-foreground">{moment.title}</span>
                <span className="tabular block text-caption text-subtle">
                  {clock(moment.start_time)}–{clock(moment.end_time)} · {formatDuration(moment.duration_seconds)}
                </span>
              </span>
              <StatusPill tone={moment.rank === 1 ? "accent" : "neutral"}>{momentLabel(moment.rank, moment.overall_score)}</StatusPill>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RecentShorts({ summary }: { summary: ProjectSummary }) {
  const shorts = summary.shorts.recent;
  if (!shorts.length) return null;
  return (
    <section aria-labelledby="overview-shorts-heading">
      <SectionHeader id="overview-shorts-heading" title="Recent Shorts" />
      <ul className="space-y-2">
        {shorts.map((short) => (
          <li key={short.edit_id}>
            <Link
              href={editorLink(summary.id, short.clip_id, short.edit_id)}
              className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <Smartphone aria-hidden="true" className="size-4 shrink-0 text-subtle" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-foreground">{short.clip_title}</span>
                <span className="block truncate text-caption text-subtle">
                  {shortLabel(short)} · {short.duration_seconds ? `${formatDuration(short.duration_seconds)} · ` : ""}
                  {relativeTime(short.updated_at)}
                </span>
              </span>
              <StatusBadge status={short.status} />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SideFacts({ summary }: { summary: ProjectSummary }) {
  const published = summary.published.uploads + summary.published.with_analytics > 0;
  return (
    <div className="space-y-3">
      {summary.source ? (
        <Link
          href={projectHref(summary.id, "source")}
          className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <Film aria-hidden="true" className="size-4 shrink-0 text-subtle" />
          <span className="min-w-0 flex-1">
            <span className="block text-caption text-subtle">Source video</span>
            <span className="block truncate text-sm font-medium text-foreground">{summary.source.filename}</span>
            {summary.source.duration_seconds ? (
              <span className="block text-caption text-subtle">{formatDuration(summary.source.duration_seconds)}</span>
            ) : null}
          </span>
          <StatusBadge status={summary.source.status} />
        </Link>
      ) : null}
      {summary.clips.total ? (
        <Link
          href={projectHref(summary.id, "clips")}
          className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <Clapperboard aria-hidden="true" className="size-4 shrink-0 text-subtle" />
          <span className="min-w-0 flex-1">
            <span className="block text-caption text-subtle">Clips</span>
            <span className="block text-sm font-medium text-foreground">
              {summary.clips.ready} ready{summary.clips.working ? ` · ${summary.clips.working} in progress` : ""}
            </span>
          </span>
        </Link>
      ) : null}
      {published ? (
        <Link
          href={projectHref(summary.id, "analytics")}
          className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <BarChart3 aria-hidden="true" className="size-4 shrink-0 text-subtle" />
          <span className="min-w-0 flex-1">
            <span className="block text-caption text-subtle">On YouTube</span>
            <span className="block text-sm font-medium text-foreground">
              {summary.published.with_analytics
                ? `${summary.published.with_analytics} Short${summary.published.with_analytics === 1 ? "" : "s"} with analytics`
                : `${summary.published.uploads} upload${summary.published.uploads === 1 ? "" : "s"}`}
            </span>
            {summary.published.last_synced_at ? (
              <span className="block text-caption text-subtle">Updated {relativeTime(summary.published.last_synced_at)}</span>
            ) : null}
          </span>
        </Link>
      ) : null}
    </div>
  );
}

/** The project's landing page: the next step first, where it is, and what it has. */
export function ProjectOverview() {
  const { project } = useProject();
  const load = useCallback(() => getProjectSummary(project.id), [project.id]);
  const { data, error, loading, reload } = useApi(load);
  const [live, setLive] = useState<ProjectSummary | null>(null);
  const summary = live ?? data;
  const refresh = useCallback(async () => setLive(await getProjectSummary(project.id)), [project.id]);
  // Follow work in progress (a transcription, a render…) until it settles.
  usePolling(summary?.next_action.tone === "waiting", refresh);

  if (loading && !summary) {
    return (
      <div role="status" aria-label="Loading the overview" className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <Skeleton className="h-44 rounded-2xl" />
        <Skeleton className="h-72 rounded-2xl" />
      </div>
    );
  }
  if (error || !summary) return <ErrorState title="The overview could not be loaded" message={error ?? "Try again."} onRetry={reload} />;
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem]">
      <div className="min-w-0 space-y-8">
        <NextStep summary={summary} onChanged={() => void refresh()} />
        <BestMoments summary={summary} />
        <RecentShorts summary={summary} />
      </div>
      <aside aria-label="Project at a glance" className="space-y-6 lg:row-span-2">
        <Workflow summary={summary} />
        <SideFacts summary={summary} />
      </aside>
    </div>
  );
}
