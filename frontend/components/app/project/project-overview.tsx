"use client";

import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Clapperboard,
  FileText,
  Smartphone,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useProject } from "@/components/app/project/project-frame";
import { ProjectMarketControl } from "@/components/app/project/project-market";
import { ErrorState } from "@/components/app/states";
import { VideoUpload } from "@/components/app/video-upload";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Spinner } from "@/components/ui/progress";
import { SectionHeader } from "@/components/ui/section-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { FrameTag, VideoFrame } from "@/components/ui/video-frame";
import { errorMessage } from "@/lib/api";
import { editContentUrl } from "@/lib/edits";
import { shortHref, statusLabel } from "@/lib/shorts";
import { formatDuration } from "@/lib/format";
import { categoryLabel } from "@/lib/moments";
import { projectHref } from "@/lib/navigation";
import { humanStatus } from "@/lib/status";
import { getTranscriptPage, startTranscription, type TranscriptSegment } from "@/lib/transcription";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";
import { videoContentUrl } from "@/lib/videos";
import {
  clock,
  getProjectSummary,
  momentLabel,
  relativeTime,
  shortLabel,
  workflowSteps,
  type FlowState,
  type NextAction,
  type ProjectSummary,
} from "@/lib/workspace";

const TONE: Record<NextAction["tone"], { icon: LucideIcon | null; tile: string; eyebrow: string }> = {
  attention: { icon: AlertTriangle, tile: "bg-danger/15 text-rose-200", eyebrow: "Needs attention" },
  action: { icon: Sparkles, tile: "bg-accent/15 text-accent-soft", eyebrow: "Next best action" },
  waiting: { icon: null, tile: "bg-violet/15 text-violet-200", eyebrow: "In progress" },
  done: { icon: CheckCircle2, tile: "bg-success/15 text-emerald-200", eyebrow: "Done" },
};

const FLOW: Record<FlowState, { circle: string; label: string }> = {
  done: { circle: "border-success/50 bg-success/15 text-emerald-200", label: "done" },
  current: { circle: "border-accent bg-accent text-accent-ink", label: "next" },
  working: { circle: "border-violet/60 bg-violet/15 text-violet-200", label: "in progress" },
  attention: { circle: "border-danger/60 bg-danger/15 text-rose-200", label: "needs attention" },
  upcoming: { circle: "border-border-strong bg-surface-2 text-subtle", label: "not started" },
};

/** Upload → Transcribe → Find moments → Create Short → Edit & publish, from real progress. */
function Workflow({ summary }: { summary: ProjectSummary }) {
  const steps = workflowSteps(summary);
  return (
    <nav aria-label="Project progress" className="rounded-card border border-border bg-surface px-3 py-3 shadow-card sm:px-5 sm:py-4">
      <ol className="grid grid-cols-5 gap-1">
        {steps.map((step, index) => {
          const look = FLOW[step.state];
          return (
            <li key={step.key} className="relative flex min-w-0 flex-col items-center gap-1.5 px-0.5 py-1 text-center lg:flex-row lg:items-center lg:gap-3 lg:px-1 lg:text-left">
              {index > 0 ? (
                <span
                  aria-hidden="true"
                  className={`absolute top-1/2 -left-3 hidden h-px w-5 lg:block ${steps[index - 1].state === "done" ? "bg-success/50" : "bg-white/10"}`}
                />
              ) : null}
              <span
                aria-current={step.state === "current" ? "step" : undefined}
                className={`flex size-9 shrink-0 items-center justify-center rounded-full border text-caption font-semibold ${look.circle}`}
              >
                {step.state === "done" ? (
                  <Check aria-hidden="true" className="size-4" strokeWidth={3} />
                ) : step.state === "working" ? (
                  <Spinner className="size-4" />
                ) : step.state === "attention" ? (
                  <AlertTriangle aria-hidden="true" className="size-4" />
                ) : (
                  <span aria-hidden="true">{index + 1}</span>
                )}
              </span>
              <span className="min-w-0">
                <span className={`block text-caption leading-tight font-semibold sm:text-small lg:text-sm ${step.state === "current" ? "text-accent-soft" : "text-foreground"}`}>
                  {step.title}
                  <span className="sr-only"> ({look.label})</span>
                </span>
                <span className="hidden truncate text-caption text-subtle lg:block">{step.detail}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

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
    <section
      aria-labelledby="next-heading"
      className={`relative overflow-hidden rounded-card border p-5 shadow-card sm:p-6 ${
        next.tone === "action" ? "next-up border-border bg-surface" : "border-border bg-surface"
      }`}
    >
      <div className="flex gap-4">
        <span className={`hidden size-12 shrink-0 items-center justify-center rounded-block sm:flex ${tone.tile}`}>
          {tone.icon ? <tone.icon aria-hidden="true" className="size-6" /> : <Spinner />}
        </span>
        <div className="min-w-0 flex-1">
          <p className={`text-small font-medium ${next.tone === "attention" ? "text-rose-200" : next.tone === "action" ? "text-accent-soft" : "text-muted"}`}>{tone.eyebrow}</p>
          <h2 id="next-heading" className="mt-1 text-section text-pretty" aria-live="polite">
            {next.title}
          </h2>
          <p className="mt-1.5 text-sm text-pretty text-muted">{next.description}</p>
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
              <ButtonLink href={next.href}>
                {next.cta}
                <ArrowRight aria-hidden="true" />
              </ButtonLink>
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
    </section>
  );
}

/** The source video: a real frame, its length and state; details live on the Source page. */
function SourceCard({ summary }: { summary: ProjectSummary }) {
  const source = summary.source;
  if (!source) return null;
  const status = humanStatus(source.status);
  return (
    <section aria-labelledby="source-heading" className="rounded-card border border-border bg-surface p-4 shadow-card sm:p-5">
      <SectionHeader as="h3" id="source-heading" title="Source video" />
      <Link
        href={projectHref(summary.id, "source")}
        className="group block rounded-block focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <VideoFrame
          src={source.status === "failed" ? null : videoContentUrl(source.id)}
          at={Math.min(5, (source.duration_seconds ?? 2) / 3)}
          className="rounded-block border border-border transition-[border-color] group-hover:border-border-strong"
        >
          {source.duration_seconds ? <FrameTag className="right-2 bottom-2">{clock(source.duration_seconds)}</FrameTag> : null}
        </VideoFrame>
        <span className="mt-3 flex items-center justify-between gap-3">
          <span className="min-w-0 truncate text-sm font-medium text-foreground">{source.filename}</span>
          <StatusPill tone={status.tone}>{status.label}</StatusPill>
        </span>
        <span className="mt-0.5 block text-caption text-subtle">Open the source, transcript and technical details</span>
      </Link>
    </section>
  );
}

/** The first lines of the transcript, read-only; the full, searchable transcript is on Source. */
function TranscriptPeek({ summary }: { summary: ProjectSummary }) {
  const source = summary.source;
  const ready = summary.transcript?.status === "completed" && !!source;
  const [lines, setLines] = useState<TranscriptSegment[] | null>(null);
  useEffect(() => {
    if (!ready || !source) return;
    let cancelled = false;
    getTranscriptPage(summary.id, source.id, 0, 6)
      .then((page) => !cancelled && setLines(page.segments))
      .catch(() => !cancelled && setLines([]));
    return () => {
      cancelled = true;
    };
  }, [ready, source, summary.id]);
  if (!ready) return null;
  const top = summary.detection?.top[0];
  return (
    <section aria-labelledby="transcript-heading" className="flex flex-col rounded-card border border-border bg-surface p-4 shadow-card sm:p-5">
      <SectionHeader
        as="h3"
        id="transcript-heading"
        title="Transcript"
        actions={
          <Link
            href={projectHref(summary.id, "source")}
            className="inline-flex min-h-11 items-center gap-1.5 text-sm text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <FileText aria-hidden="true" className="size-4" />
            Full transcript
          </Link>
        }
      />
      {lines === null ? (
        <div className="space-y-2" role="status" aria-label="Loading the transcript">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : lines.length ? (
        <ol className="space-y-1">
          {lines.map((line) => {
            // The top moment's opening line is highlighted, so the creator sees where it starts.
            const inTop = !!top && line.start < top.end_time && line.end > top.start_time;
            return (
              <li
                key={line.sequence_index}
                className={`flex gap-3 rounded-control px-2 py-1.5 text-sm ${inTop ? "bg-accent/[0.08] ring-1 ring-accent/25 ring-inset" : ""}`}
              >
                <span className={`tabular mt-0.5 shrink-0 self-start rounded-md px-1.5 text-caption ${inTop ? "bg-accent/20 text-accent-soft" : "bg-surface-2 text-subtle"}`}>
                  {clock(line.start)}
                </span>
                <span className="min-w-0 text-pretty text-muted">{line.text}</span>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="text-sm text-muted">The transcript has no lines to show.</p>
      )}
    </section>
  );
}

/** The best moments as visual cards: a real frame at the moment, its type, time and rank label. */
function Moments({ summary }: { summary: ProjectSummary }) {
  const top = summary.detection?.top ?? [];
  const source = summary.source;
  if (!top.length || !source) return null;
  return (
    <section aria-labelledby="moments-heading">
      <SectionHeader
        id="moments-heading"
        title="Clip moments"
        description="Ranked by PeakSift's editorial judgement of the transcript — not a prediction of views."
        actions={
          <Link
            href={projectHref(summary.id, "clips")}
            className="inline-flex min-h-11 items-center gap-1.5 text-sm text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            View all moments
            <ArrowRight aria-hidden="true" className="size-4" />
          </Link>
        }
      />
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {top.slice(0, 3).map((moment) => (
          <li key={moment.id} className="min-w-0">
            <Link
              href={projectHref(summary.id, "clips")}
              className="group flex h-full flex-col overflow-hidden rounded-card border border-border bg-surface shadow-card transition-[border-color,background-color] hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <VideoFrame src={videoContentUrl(source.id)} at={moment.start_time + 0.5}>
                <span className="absolute top-2 left-2">
                  <StatusPill tone="info" overlay>
                    {categoryLabel(moment.category)}
                  </StatusPill>
                </span>
                {moment.rank === 1 ? (
                  <span className="absolute top-2 right-2">
                    <StatusPill tone="accent" overlay>
                      {momentLabel(moment.rank, moment.overall_score)}
                    </StatusPill>
                  </span>
                ) : null}
                <FrameTag className="bottom-2 left-2">
                  {clock(moment.start_time)} – {clock(moment.end_time)}
                </FrameTag>
              </VideoFrame>
              <span className="flex flex-1 flex-col gap-1 p-4">
                <span className="text-title text-pretty">{moment.title}</span>
                <span className="text-caption text-subtle">
                  {formatDuration(moment.duration_seconds)}
                  {moment.rank === 1 ? "" : ` · ${momentLabel(moment.rank, moment.overall_score)}`}
                </span>
                <span className="mt-auto pt-3 text-small font-medium text-accent-soft">Review and create a Short</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The project's Shorts as vertical thumbnails with their state. */
function Shorts({ summary }: { summary: ProjectSummary }) {
  const shorts = summary.shorts.recent;
  if (!shorts.length) return null;
  return (
    <section aria-labelledby="overview-shorts-heading">
      <SectionHeader
        id="overview-shorts-heading"
        title="Generated Shorts"
        actions={
          <Link
            href={`/shorts?q=${encodeURIComponent(summary.name)}`}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-control px-1 text-sm text-muted transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            View in Shorts
          </Link>
        }
      />
      <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        {shorts.map((short) => {
          const status = statusLabel(short.short_status);
          return (
            <li key={short.edit_id} className="min-w-0">
              <Link
                href={shortHref(short.edit_id)}
                className="group block rounded-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <VideoFrame
                  src={short.status === "ready" ? editContentUrl(short.edit_id) : null}
                  ratio="vertical"
                  icon={short.status === "ready" ? Smartphone : Clapperboard}
                  className="rounded-card border border-border group-hover:border-border-strong"
                >
                  <span className="absolute top-2 left-2">
                    <StatusPill tone={status.tone} overlay>
                      {status.label}
                    </StatusPill>
                  </span>
                  {short.duration_seconds ? <FrameTag className="right-2 bottom-2">{formatDuration(short.duration_seconds)}</FrameTag> : null}
                </VideoFrame>
                <span className="mt-2.5 line-clamp-2 text-sm font-medium text-foreground">{short.clip_title}</span>
                <span className="mt-0.5 block truncate text-caption text-subtle">
                  {shortLabel(short)} · {relativeTime(short.updated_at)}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The project's landing page: where it is, the next step, its source, moments and Shorts. */
export function ProjectOverview() {
  const { project, reload: reloadProject } = useProject();
  const load = useCallback(() => getProjectSummary(project.id), [project.id]);
  const { data, error, loading, reload } = useApi(load);
  const [live, setLive] = useState<ProjectSummary | null>(null);
  const summary = live ?? data;
  const refresh = useCallback(async () => setLive(await getProjectSummary(project.id)), [project.id]);
  // Follow work in progress (a transcription, a render…) until it settles.
  usePolling(summary?.next_action.tone === "waiting", refresh);

  if (loading && !summary) {
    return (
      <div role="status" aria-label="Loading the overview" className="space-y-6">
        <Skeleton className="h-20 rounded-card" />
        <div className="grid gap-6 lg:grid-cols-12">
          <Skeleton className="h-56 rounded-card lg:col-span-7" />
          <Skeleton className="h-56 rounded-card lg:col-span-5" />
        </div>
      </div>
    );
  }
  if (error || !summary) return <ErrorState title="The overview could not be loaded" message={error ?? "Try again."} onRetry={reload} />;
  const hasTranscript = summary.transcript?.status === "completed";
  return (
    <div className="space-y-8">
      <Workflow summary={summary} />
      <div className="grid gap-6 lg:grid-cols-12 lg:items-start">
        <div className={summary.source ? "lg:col-span-7" : "lg:col-span-12"}>
          <NextStep summary={summary} onChanged={() => void refresh()} />
        </div>
        {summary.source ? (
          <div className="lg:col-span-5">
            <SourceCard summary={summary} />
          </div>
        ) : null}
      </div>
      <Moments summary={summary} />
      {summary.shorts.recent.length || hasTranscript ? (
        <div className="grid gap-6 lg:grid-cols-12">
          {summary.shorts.recent.length ? (
            <div className={hasTranscript ? "lg:col-span-7" : "lg:col-span-12"}>
              <Shorts summary={summary} />
            </div>
          ) : null}
          {hasTranscript ? (
            <div className={summary.shorts.recent.length ? "lg:col-span-5" : "lg:col-span-12"}>
              <TranscriptPeek summary={summary} />
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="max-w-2xl">
        <ProjectMarketControl project={project} onChange={() => reloadProject()} />
      </div>
    </div>
  );
}
