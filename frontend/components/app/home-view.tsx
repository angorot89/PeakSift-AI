"use client";

import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  Clapperboard,
  FolderPlus,
  Palette,
  Scissors,
  Search,
  Smartphone,
  Sparkles,
  Upload,
  Wand2,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { ModeSwitch } from "@/components/app/morocco/morocco-views";
import { QuickStart } from "@/components/app/quick-start";
import { ShellSearch } from "@/components/app/shell-search";
import { ErrorState } from "@/components/app/states";
import { useAuth } from "@/components/auth/auth-provider";
import { ButtonLink } from "@/components/ui/button-link";
import { IconButton } from "@/components/ui/icon-button";
import { Spinner } from "@/components/ui/progress";
import { SectionHeader } from "@/components/ui/section-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { FrameTag, VideoFrame } from "@/components/ui/video-frame";
import { editContentUrl } from "@/lib/edits";
import { formatDuration } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { shortHref, statusLabel } from "@/lib/shorts";
import { useStoredFlag } from "@/lib/use-stored-flag";
import { videoContentUrl } from "@/lib/videos";
import {
  clock,
  continueVisual,
  displayName,
  getHome,
  gettingStarted,
  relativeTime,
  type ActionTone,
  type ContinueItem,
  type Home,
  type HomeShort,
  type ProjectSummary,
  workflowSteps,
} from "@/lib/workspace";

const TONE: Record<ActionTone, { icon: LucideIcon | null; tile: string; ring: string; label: string }> = {
  attention: { icon: AlertTriangle, tile: "bg-danger/15 text-rose-200", ring: "hover:border-danger/40", label: "Needs attention" },
  action: { icon: ArrowRight, tile: "bg-accent/15 text-accent-soft", ring: "hover:border-accent/40", label: "Ready for you" },
  waiting: { icon: null, tile: "bg-violet/15 text-violet-200", ring: "hover:border-violet/40", label: "In progress" },
  done: { icon: CheckCircle2, tile: "bg-success/15 text-emerald-200", ring: "hover:border-success/40", label: "Done" },
};

/**
 * The top of Home: one question, one place to drop a video, and the two other ways to start. On a
 * band of PeakSift blue — the one coloured surface in the workspace.
 */
function CreateBox({ greeting, momentsHref }: { greeting: string; momentsHref: string | null }) {
  return (
    <section aria-labelledby="create-heading" className="create-band relative overflow-hidden rounded-card border border-border px-4 pt-10 pb-6 sm:px-10 sm:pt-14 sm:pb-10">
      <div className="absolute top-4 right-4">
        <ShellSearch />
      </div>
      <div className="mx-auto max-w-2xl text-center">
        <p className="text-sm font-medium text-white/85">{greeting}</p>
        <h1 id="create-heading" className="mt-2 text-page text-balance sm:text-display">
          What will you clip today?
        </h1>
      </div>
      <div className="mx-auto mt-7 max-w-2xl rounded-card border border-border-strong bg-surface p-3 shadow-raised sm:p-4">
        <QuickStart bare />
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <ButtonLink href="/projects/new" variant="secondary">
            <FolderPlus aria-hidden="true" />
            New empty project
          </ButtonLink>
          <ButtonLink href={momentsHref ?? "/projects"} variant="secondary">
            <Search aria-hidden="true" />
            Find clips in a video
          </ButtonLink>
        </div>
      </div>
      <div className="mx-auto mt-6 flex max-w-2xl justify-center">
        <ModeSwitch current="global" />
      </div>
    </section>
  );
}

type Tool = { title: string; text: string; href: string; icon: LucideIcon; tint: string };

/** Everything PeakSift can do, one tile each, pointed at the most useful place to do it. */
function Tools({ momentsHref }: { momentsHref: string | null }) {
  const tools: Tool[] = [
    { title: "Find Clips", text: "Ask for a moment in your own words", href: momentsHref ?? "/projects", icon: Search, tint: "bg-accent/20 text-accent-soft" },
    { title: "Auto Edit", text: "PeakSift edits a moment for you", href: momentsHref ?? "/projects", icon: Wand2, tint: "bg-violet/20 text-violet-200" },
    { title: "Shorts", text: "Everything you have made", href: "/shorts", icon: Smartphone, tint: "bg-success/20 text-emerald-200" },
    { title: "Schedule", text: "Plan posts across platforms", href: "/schedule", icon: CalendarClock, tint: "bg-warning/20 text-amber-200" },
    { title: "Brand Studio", text: "Your colours, logo and templates", href: "/brand", icon: Palette, tint: "bg-rose-400/20 text-rose-200" },
    { title: "Analytics", text: "How your Shorts are doing", href: "/analytics", icon: BarChart3, tint: "bg-info/20 text-sky-200" },
  ];
  return (
    <section aria-labelledby="tools-heading">
      <h2 id="tools-heading" className="mb-4 text-section">
        Tools
      </h2>
      <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {tools.map((tool) => (
          <li key={tool.title} className="min-w-0">
            <Link
              href={tool.href}
              className="group flex h-full flex-col gap-3 rounded-card border border-border bg-surface p-4 transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <span className={`flex size-11 items-center justify-center rounded-block ${tool.tint}`}>
                <tool.icon aria-hidden="true" className="size-5" />
              </span>
              <span>
                <span className="block text-title">{tool.title}</span>
                <span className="mt-0.5 block text-small text-muted">{tool.text}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** First visit: the creation box, the tools, and what happens after a drop. */
function Welcome() {
  const steps: { icon: LucideIcon; title: string; text: string }[] = [
    { icon: Upload, title: "Upload", text: "A stream, podcast, interview or any long recording." },
    { icon: Sparkles, title: "Find moments", text: "PeakSift reads it and ranks the moments worth clipping." },
    { icon: Smartphone, title: "Create Shorts", text: "Framing, captions, visuals and sound — ready to publish." },
  ];
  return (
    <div className="space-y-10">
      <CreateBox greeting="Welcome to PeakSift" momentsHref={null} />
      <section aria-labelledby="how-heading">
        <h2 id="how-heading" className="mb-4 text-section">
          How it works
        </h2>
        <ol className="grid gap-3 sm:grid-cols-3">
          {steps.map((step, index) => (
            <li key={step.title} className="rounded-card border border-border bg-surface p-5">
              <span className="flex items-center gap-3">
                <span className="tabular flex size-8 items-center justify-center rounded-full bg-accent-fill text-sm font-bold text-accent-ink">
                  {index + 1}
                </span>
                <step.icon aria-hidden="true" className="size-5 text-subtle" />
              </span>
              <p className="mt-4 text-title">{step.title}</p>
              <p className="mt-1 text-sm text-muted">{step.text}</p>
            </li>
          ))}
        </ol>
      </section>
      <Tools momentsHref={null} />
    </div>
  );
}

/** The imagery a continue card shows: the moments waiting, the Short in question, or the source. */
function ContinueImagery({ item, project }: { item: ContinueItem; project: ProjectSummary | undefined }) {
  const visual = continueVisual(item.key, project);
  if (visual.kind === "moments" && project?.source) {
    const source = project.source;
    return (
      <div className="flex items-center gap-2">
        {visual.moments.map((moment) => (
          <VideoFrame
            key={moment.id}
            src={videoContentUrl(source.id)}
            at={moment.start_time + 0.5}
            ratio="square"
            className="w-14 rounded-control border border-border"
          />
        ))}
        <span className="ml-1 text-small text-muted">
          {visual.count} moment{visual.count === 1 ? "" : "s"}
        </span>
      </div>
    );
  }
  if (visual.kind === "short") {
    return (
      <VideoFrame src={editContentUrl(visual.short.edit_id)} ratio="video" icon={Smartphone} className="w-28 rounded-control border border-border" />
    );
  }
  if (visual.kind === "source" && project?.source) {
    return <VideoFrame src={videoContentUrl(project.source.id)} at={1} ratio="video" className="w-28 rounded-control border border-border" />;
  }
  return null;
}

/** One project's next step: the whole card is the link; one clear action. */
function ContinueCard({ item, project }: { item: ContinueItem; project: ProjectSummary | undefined }) {
  const tone = TONE[item.tone];
  return (
    <li className="min-w-0">
      <Link
        href={item.href}
        className={`group flex h-full flex-col gap-4 rounded-card border border-border bg-surface p-4 shadow-card transition-[border-color,background-color] duration-200 hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:p-5 ${tone.ring}`}
      >
        <span className="flex items-start gap-3">
          <span className={`flex size-11 shrink-0 items-center justify-center rounded-block ${tone.tile}`}>
            {tone.icon ? <tone.icon aria-hidden="true" className="size-5" /> : <Spinner />}
            <span className="sr-only">{tone.label}: </span>
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-title text-pretty">{item.title}</span>
            <span className="mt-0.5 block truncate text-small text-subtle">{item.project_name}</span>
          </span>
        </span>
        <span className="block text-sm text-pretty text-muted">{item.description}</span>
        <span className="mt-auto flex flex-wrap items-center justify-between gap-3">
          <ContinueImagery item={item} project={project} />
          <span className="text-small font-medium text-accent-soft">{item.cta ?? "Open"}</span>
        </span>
      </Link>
    </li>
  );
}

/** How far a project is along Upload → Edit & publish, and what is happening now. */
export function StageBar({ project }: { project: ProjectSummary }) {
  const steps = workflowSteps(project);
  const done = steps.filter((step) => step.state === "done").length;
  const now = steps.find((step) => step.state !== "done");
  // Done steps are quiet, the step that is up next carries the signal colour.
  return (
    <span className="block">
      <span className="flex gap-1" aria-hidden="true">
        {steps.map((step) => (
          <span
            key={step.key}
            className={`h-1 flex-1 rounded-full ${
              step.state === "done"
                ? "bg-subtle"
                : step.state === "working"
                  ? "bg-violet/80"
                  : step.state === "attention"
                    ? "bg-danger/80"
                    : step === now
                      ? "bg-accent"
                      : "bg-surface-3"
            }`}
          />
        ))}
      </span>
      <span className="mt-1.5 block truncate text-caption text-subtle">
        <span className="sr-only">
          {done} of {steps.length} steps done.{" "}
        </span>
        {now ? `${now.title} · ${now.detail}` : "All steps done"}
      </span>
    </span>
  );
}

function ProjectCard({ project }: { project: ProjectSummary }) {
  const next = project.next_action;
  const source = project.source;
  return (
    <li className="min-w-0">
      <Link
        href={`/projects/${project.id}`}
        className="group flex h-full flex-col gap-4 rounded-card border border-border bg-surface p-4 shadow-card transition-[border-color,background-color] duration-200 hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <span className="flex items-start gap-4">
          <VideoFrame
            src={source ? videoContentUrl(source.id) : null}
            at={Math.min(5, (source?.duration_seconds ?? 2) / 3)}
            icon={source ? Clapperboard : Upload}
            className="w-28 shrink-0 rounded-block border border-border sm:w-32"
          >
            {source?.duration_seconds ? <FrameTag className="right-1.5 bottom-1.5">{clock(source.duration_seconds)}</FrameTag> : null}
          </VideoFrame>
          <span className="min-w-0 flex-1">
            <span className="block text-title text-pretty break-words">{project.name}</span>
            <span className="mt-1 block truncate text-caption text-subtle">
              {source ? "" : "No video yet · "}
              {relativeTime(project.last_activity_at)}
            </span>
            <span className="mt-3 block">
              <StageBar project={project} />
            </span>
          </span>
        </span>
        <span className="mt-auto flex items-center gap-3 rounded-block bg-surface-2 px-3 py-2.5">
          <span className="min-w-0 flex-1">
            <span className="block text-caption text-subtle">Next step</span>
            <span className="block truncate text-sm font-medium text-foreground">{next.title}</span>
          </span>
          <ArrowRight aria-hidden="true" className="size-4 shrink-0 text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
        </span>
      </Link>
    </li>
  );
}

/** A finished Short as a vertical thumbnail: its state, length, title and project. */
function ShortTile({ short }: { short: HomeShort }) {
  return (
    <li className="min-w-0">
      <Link
        href={shortHref(short.edit_id)}
        className="group block rounded-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <VideoFrame
          src={editContentUrl(short.edit_id)}
          ratio="vertical"
          icon={Smartphone}
          className="rounded-card border border-border transition-[border-color] group-hover:border-border-strong"
        >
          <span className="absolute top-2 left-2">
            <StatusPill tone={statusLabel(short.short_status).tone} overlay>
              {statusLabel(short.short_status).label}
            </StatusPill>
          </span>
          {short.duration_seconds ? <FrameTag className="right-2 bottom-2">{formatDuration(short.duration_seconds)}</FrameTag> : null}
        </VideoFrame>
        <span className="mt-2.5 line-clamp-2 text-sm font-medium text-foreground">{short.clip_title}</span>
        <span className="mt-0.5 block truncate text-caption text-subtle">{short.project_name}</span>
      </Link>
    </li>
  );
}

/** The last tile: where to make the next Short (moments waiting, else a project, else a new one). */
function CreateTile({ home }: { home: Home }) {
  const withMoments = home.projects.find((p) => p.detection?.status === "completed" && p.detection.candidates > 0);
  const href = withMoments ? `/projects/${withMoments.id}/clips` : home.projects[0] ? `/projects/${home.projects[0].id}` : "/projects/new";
  return (
    <li className="min-w-0">
      <Link
        href={href}
        className="flex aspect-[9/16] flex-col items-center justify-center gap-3 rounded-card border border-dashed border-border-strong p-4 text-center text-sm text-muted transition-colors hover:border-subtle hover:bg-surface hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <span className="flex size-11 items-center justify-center rounded-full border border-border-strong bg-surface-2">
          <Scissors aria-hidden="true" className="size-5 text-foreground" />
        </span>
        Create a Short from any moment
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
    <section aria-labelledby="start-heading" className="next-up rounded-card border border-border bg-surface px-5 py-4">
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
            <span className={step.done ? "text-muted line-through decoration-subtle/50" : "text-foreground"}>
              {step.title}
              <span className="sr-only">{step.done ? " (done)" : ""}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ViewAll({ href, children }: { href: string; children: string }) {
  return (
    <Link
      href={href}
      className="inline-flex min-h-11 items-center gap-1.5 rounded-control px-1 text-sm text-muted transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      {children}
      <ArrowRight aria-hidden="true" className="size-4" />
    </Link>
  );
}

function Returning({ home }: { home: Home }) {
  const { user } = useAuth();
  const name = user ? displayName(user.email) : "";
  const projects = new Map(home.projects.map((p) => [p.id, p]));
  // Find Clips and Auto Edit start from a project's moments: the most recent project with a video.
  const withSource = home.projects.find((p) => p.source);
  const momentsHref = withSource ? `/projects/${withSource.id}/clips` : null;
  return (
    <div className="space-y-12">
      <CreateBox greeting={name ? `Hi ${name}` : "Welcome back"} momentsHref={momentsHref} />

      <Tools momentsHref={momentsHref} />

      <GettingStarted home={home} />

      {home.continue_items.length ? (
        <section aria-labelledby="continue-heading">
          <SectionHeader id="continue-heading" title="Continue working" />
          <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {home.continue_items.map((item) => (
              <ContinueCard key={item.project_id} item={item} project={projects.get(item.project_id)} />
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="projects-heading">
        <SectionHeader
          id="projects-heading"
          title="Recent projects"
          actions={<ViewAll href="/projects">{home.project_count > home.projects.length ? `View all ${home.project_count}` : "View all projects"}</ViewAll>}
        />
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {home.projects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </ul>
      </section>

      <section aria-labelledby="shorts-heading">
        <SectionHeader
          id="shorts-heading"
          title="Recent Shorts"
          description={home.recent_shorts.length ? "Finished and ready to publish or download." : "Your finished Shorts will show up here."}
          actions={home.recent_shorts.length ? <ViewAll href="/shorts">View all Shorts</ViewAll> : null}
        />
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-7">
          {home.recent_shorts.map((short) => (
            <ShortTile key={short.edit_id} short={short} />
          ))}
          <CreateTile home={home} />
        </ul>
      </section>
    </div>
  );
}

/** Home: continue working, recent projects and Shorts — or a welcome on the first visit. */
export function HomeView() {
  const { data, error, loading, reload } = useApi(getHome);
  if (loading && !data) {
    return (
      <div role="status" aria-label="Loading your workspace" className="space-y-10">
        <Skeleton className="h-12 w-80" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Skeleton className="h-44 rounded-card" />
          <Skeleton className="h-44 rounded-card" />
          <Skeleton className="h-44 rounded-card" />
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Skeleton className="h-40 rounded-card" />
          <Skeleton className="h-40 rounded-card" />
          <Skeleton className="h-40 rounded-card" />
        </div>
      </div>
    );
  }
  if (error || !data) return <ErrorState title="Your workspace could not be loaded" message={error ?? "Try again."} onRetry={reload} />;
  return data.project_count === 0 ? <Welcome /> : <Returning home={data} />;
}

