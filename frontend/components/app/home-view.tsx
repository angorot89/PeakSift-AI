"use client";

import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Film,
  FolderOpen,
  Play,
  Plus,
  Smartphone,
  Sparkles,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ErrorState } from "@/components/app/states";
import { ButtonLink } from "@/components/ui/button-link";
import { IconButton } from "@/components/ui/icon-button";
import { Card, cardClasses } from "@/components/ui/card";
import { Spinner } from "@/components/ui/progress";
import { SectionHeader } from "@/components/ui/section-header";
import { Skeleton } from "@/components/ui/skeleton";
import { editContentUrl } from "@/lib/edits";
import { formatDuration } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { useStoredFlag } from "@/lib/use-stored-flag";
import {
  editorLink,
  getHome,
  gettingStarted,
  projectStage,
  relativeTime,
  shortLabel,
  STAGES,
  type ActionTone,
  type ContinueItem,
  type Home,
  type HomeShort,
  type ProjectSummary,
} from "@/lib/workspace";

const TONE_ICON: Record<ActionTone, { icon: LucideIcon | null; className: string; label: string }> = {
  attention: { icon: AlertTriangle, className: "bg-danger/15 text-rose-200", label: "Needs attention" },
  action: { icon: ArrowRight, className: "bg-accent/15 text-accent-soft", label: "Ready for you" },
  waiting: { icon: null, className: "bg-surface-3 text-muted", label: "In progress" },
  done: { icon: CheckCircle2, className: "bg-success/15 text-emerald-200", label: "Done" },
};

/** First visit: what PeakSift does, in three steps, and one way to start. */
function Welcome() {
  const steps: { icon: LucideIcon; title: string; text: string }[] = [
    { icon: Upload, title: "Upload", text: "A stream, podcast, interview or any long recording." },
    { icon: Sparkles, title: "Find moments", text: "PeakSift reads it and ranks the moments worth clipping." },
    { icon: Smartphone, title: "Create Shorts", text: "Framing, captions, visuals and sound — ready to publish." },
  ];
  return (
    <div className="mx-auto max-w-3xl py-6 sm:py-12">
      <div className="text-center">
        <p className="text-small font-medium text-accent-soft">Welcome to PeakSift</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
          Turn long videos into polished Shorts
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-lead text-pretty text-muted">
          PeakSift finds the moments worth clipping and helps you edit them for YouTube Shorts, TikTok and Reels.
        </p>
        <div className="mt-7 flex justify-center">
          <ButtonLink href="/projects/new" size="lg">
            <Plus aria-hidden="true" />
            Create your first project
          </ButtonLink>
        </div>
      </div>
      <ol className="mt-12 grid gap-3 sm:grid-cols-3">
        {steps.map((step, index) => (
          <li key={step.title}>
            <Card className="h-full">
              <span className="flex size-9 items-center justify-center rounded-lg bg-surface-3 text-accent-soft">
                <step.icon aria-hidden="true" className="size-[18px]" />
              </span>
              <p className="mt-3 text-title">
                <span className="tabular text-subtle">{index + 1}. </span>
                {step.title}
              </p>
              <p className="mt-1 text-sm text-muted">{step.text}</p>
            </Card>
          </li>
        ))}
      </ol>
    </div>
  );
}

function ContinueCard({
  item,
  primary,
}: {
  item: ContinueItem;
  primary: boolean;
}) {
  const tone = TONE_ICON[item.tone];
  return (
    <li>
      <Card className="flex h-full flex-col gap-4">
        <div className="flex gap-3">
          <span className={`flex size-9 shrink-0 items-center justify-center rounded-lg ${tone.className}`}>
            {tone.icon ? <tone.icon aria-hidden="true" className="size-[18px]" /> : <Spinner />}
            <span className="sr-only">{tone.label}</span>
          </span>
          <div className="min-w-0">
            <p className="truncate text-caption font-medium text-subtle">{item.project_name}</p>
            <p className="mt-0.5 text-title">{item.title}</p>
            <p className="mt-0.5 text-sm text-pretty text-muted">{item.description}</p>
          </div>
        </div>
        <div className="mt-auto">
          <ButtonLink href={item.href} variant={primary && item.cta ? "primary" : "secondary"} size="sm">
            {item.cta ?? "Open"}
          </ButtonLink>
        </div>
      </Card>
    </li>
  );
}

/** A finished Short; its first frame loads only once the card scrolls into view. */
function ShortCard({ short }: { short: HomeShort }) {
  const ref = useRef<HTMLAnchorElement>(null);
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
    <li className="w-36 shrink-0 sm:w-40">
      <Link
        ref={ref}
        href={editorLink(short.project_id, short.clip_id, short.edit_id)}
        className="group block rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <span className="relative block aspect-[9/16] overflow-hidden rounded-xl border border-border bg-[linear-gradient(160deg,var(--surface-3),var(--background))]">
          {/* Shown until a frame paints (some phones only draw video frames on playback). */}
          <span aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-subtle">
            <Smartphone className="size-6" />
          </span>
          {visible ? (
            <video
              src={`${editContentUrl(short.edit_id)}#t=0.5`}
              preload="metadata"
              muted
              playsInline
              aria-hidden="true"
              tabIndex={-1}
              onLoadedData={() => setPainted(true)}
              className={`relative size-full object-cover transition-opacity group-hover:opacity-80 ${painted ? "opacity-100" : "opacity-0"}`}
            />
          ) : null}
          <span className="absolute right-2 bottom-2 flex size-8 items-center justify-center rounded-full bg-black/70 text-white">
            <Play aria-hidden="true" className="size-3.5" />
          </span>
        </span>
        <span className="mt-2 block truncate text-sm font-medium text-foreground">{short.clip_title}</span>
        <span className="block truncate text-caption text-subtle">{short.project_name}</span>
        <span className="block truncate text-caption text-subtle">
          {shortLabel(short)}
          {short.duration_seconds ? ` · ${formatDuration(short.duration_seconds)}` : ""}
        </span>
      </Link>
    </li>
  );
}

/** Where a project is (Source → Learn), in words and a compact five-step bar. */
export function StageBar({ project }: { project: ProjectSummary }) {
  const stage = projectStage(project);
  return (
    <div>
      <div className="flex gap-1" aria-hidden="true">
        {STAGES.map((name, index) => (
          <span key={name} className={`h-1 flex-1 rounded-full ${index <= stage ? "bg-accent" : "bg-white/10"}`} />
        ))}
      </div>
      <p className="mt-1.5 text-caption text-subtle">
        <span className="sr-only">Stage: </span>
        {STAGES[stage]}
        <span className="sr-only"> (step {stage + 1} of {STAGES.length})</span>
      </p>
    </div>
  );
}

function ProjectCard({ project }: { project: ProjectSummary }) {
  const next = project.next_action;
  return (
    <li>
      <Link href={`/projects/${project.id}`} className={`${cardClasses({ interactive: true })} flex h-full flex-col gap-3`}>
        <div className="flex items-start gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-3 text-muted">
            {project.source ? <Film aria-hidden="true" className="size-[18px]" /> : <FolderOpen aria-hidden="true" className="size-[18px]" />}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-title">{project.name}</span>
            <span className="block truncate text-caption text-subtle">
              {project.source ? project.source.filename : "No video yet"} · {relativeTime(project.last_activity_at)}
            </span>
          </span>
        </div>
        <StageBar project={project} />
        <p className="mt-auto text-sm text-muted">
          <span className="text-subtle">Next: </span>
          {next.title}
        </p>
      </Link>
    </li>
  );
}

/** A first-run checklist from real progress; gone for good once dismissed or once a Short is ready. */
function GettingStarted({ home }: { home: Home }) {
  const [dismissed, setDismissed] = useStoredFlag("peaksift.tips.getting-started");
  const { steps, complete } = gettingStarted(home);
  if (complete || dismissed) return null;
  const done = steps.filter((step) => step.done).length;
  return (
    <section aria-labelledby="start-heading" className="rounded-2xl border border-accent/30 bg-accent/[0.04] px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="start-heading" className="text-title">Getting started</h2>
          <p className="mt-0.5 text-sm text-muted">
            {done} of {steps.length} done. Your first Short is a few steps away.
          </p>
        </div>
        <IconButton aria-label="Dismiss getting started" size="sm" onClick={() => setDismissed(true)}>
          <X aria-hidden="true" />
        </IconButton>
      </div>
      <ol className="mt-3 grid gap-2 sm:grid-cols-3">
        {steps.map((step, index) => (
          <li key={step.key} className="flex items-center gap-2.5 text-sm">
            <span
              aria-hidden="true"
              className={`flex size-6 shrink-0 items-center justify-center rounded-full text-caption font-semibold ${
                step.done ? "bg-success/15 text-emerald-200" : "bg-surface-3 text-subtle"
              }`}
            >
              {step.done ? <CheckCircle2 className="size-3.5" /> : index + 1}
            </span>
            <span className={step.done ? "text-muted line-through decoration-white/20" : "text-foreground"}>
              {step.title}
              <span className="sr-only">{step.done ? " (done)" : ""}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Returning({ home }: { home: Home }) {
  const items = home.continue_items;
  const firstAction = items.findIndex((item) => item.cta);
  return (
    <div className="space-y-10">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-page">Welcome back</h1>
          <p className="mt-1 text-sm text-muted">Pick up where you left off.</p>
        </div>
        <ButtonLink href="/projects/new" variant={firstAction === -1 ? "primary" : "secondary"}>
          <Plus aria-hidden="true" />
          New project
        </ButtonLink>
      </div>

      <GettingStarted home={home} />

      {items.length ? (
        <section aria-labelledby="continue-heading">
          <SectionHeader id="continue-heading" title="Continue working" />
          <ul className="grid gap-3 md:grid-cols-2">
            {items.map((item, index) => (
              <ContinueCard key={item.project_id} item={item} primary={index === firstAction} />
            ))}
          </ul>
        </section>
      ) : null}

      {home.recent_shorts.length ? (
        <section aria-labelledby="shorts-heading">
          <SectionHeader id="shorts-heading" title="Recent Shorts" description="Finished and ready to publish or download." />
          <ul className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0">
            {home.recent_shorts.map((short) => (
              <ShortCard key={short.edit_id} short={short} />
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="projects-heading">
        <SectionHeader
          id="projects-heading"
          title="Recent projects"
          actions={
            home.project_count > home.projects.length ? (
              <Link href="/projects" className="inline-flex min-h-11 items-center text-sm text-muted hover:text-foreground">
                View all {home.project_count}
              </Link>
            ) : undefined
          }
        />
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {home.projects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </ul>
      </section>
    </div>
  );
}

/** Home: continue working, recent Shorts and projects — or a welcome on the first visit. */
export function HomeView() {
  const { data, error, loading, reload } = useApi(getHome);
  if (loading && !data) {
    return (
      <div role="status" aria-label="Loading your workspace" className="space-y-8">
        <Skeleton className="h-9 w-56" />
        <div className="grid gap-3 md:grid-cols-2">
          <Skeleton className="h-36 rounded-2xl" />
          <Skeleton className="h-36 rounded-2xl" />
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Skeleton className="h-32 rounded-2xl" />
          <Skeleton className="h-32 rounded-2xl" />
          <Skeleton className="h-32 rounded-2xl" />
        </div>
      </div>
    );
  }
  if (error || !data) return <ErrorState title="Your workspace could not be loaded" message={error ?? "Try again."} onRetry={reload} />;
  return data.project_count === 0 ? <Welcome /> : <Returning home={data} />;
}
