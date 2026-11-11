"use client";

import { Download, FolderOpen, Pencil, Send, Smartphone, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/app/page-header";
import { PerformancePanel } from "@/components/app/shorts/performance-panel";
import { PublishingPanel } from "@/components/app/shorts/publishing-panel";
import { previewAt, previewSrc, useShortAction } from "@/components/app/shorts/short-card";
import { ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button-link";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { VideoFrame } from "@/components/ui/video-frame";
import { editDownloadUrl } from "@/lib/edits";
import { formatBytes } from "@/lib/format";
import {
  clock,
  dayLabel,
  editorHref,
  getShort,
  primaryAction,
  type ShortAction,
  type ShortDetail,
  shortHref,
  statusDetail,
  statusLabel,
} from "@/lib/shorts";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";

const ACTION_ICONS: Partial<Record<ShortAction, typeof Pencil>> = {
  continue: Pencil,
  publish: Send,
  performance: TrendingUp,
  fix_render: Pencil,
  fix_publish: Send,
  retry_cut: FolderOpen,
};

const CATEGORY: Record<string, string> = {
  insight: "Insight",
  humor: "Humor",
  story: "Story",
  emotional: "Emotional",
  controversial: "Hot take",
  educational: "Lesson",
  reaction: "Reaction",
};

/** A Short is still changing while it renders or uploads: keep its page current. */
const changing = (short: ShortDetail) => short.status === "rendering" || short.status === "publishing";

/** The rendered Short with controls; the moment's cut (clearly named) until it exists. */
function Preview({ short }: { short: ShortDetail }) {
  const src = previewSrc(short);
  if (short.preview === "short" && src) {
    return (
      <video
        src={src}
        controls
        playsInline
        preload="metadata"
        aria-label={`Rendered Short: ${short.title}`}
        className="aspect-[9/16] w-full rounded-card border border-border bg-black object-contain shadow-card"
      />
    );
  }
  return (
    <figure className="space-y-2">
      <VideoFrame src={src} at={previewAt(short)} ratio="vertical" icon={Smartphone} className="rounded-card border border-border shadow-card" />
      <figcaption className="text-caption text-subtle">
        {short.preview === "clip" ? "The moment's cut. The Short appears here once it's rendered." : "Nothing to preview yet."}
      </figcaption>
    </figure>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_minmax(0,1fr)] gap-3 border-b border-border py-2.5 last:border-b-0">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="min-w-0 text-sm break-words text-foreground">{children}</dd>
    </div>
  );
}

/** What this Short was made from and with — as recorded with it, never today's template. */
function Provenance({ short }: { short: ShortDetail }) {
  const moment = short.moment;
  return (
    <Card>
      <h2 className="text-title">Details</h2>
      <dl className="mt-2">
        <Row label="Created from">
          <Link href={`/projects/${short.project.id}`} className="font-medium text-accent-soft underline-offset-4 hover:underline">
            {short.project.name}
          </Link>
          <span className="block truncate text-caption text-subtle">{short.source.filename}</span>
        </Row>
        <Row label="Moment">
          <span className="tabular">
            {clock(moment.start_time)}–{clock(moment.end_time)}
          </span>
          <span className="text-muted">
            {" "}
            · #{moment.rank}
            {CATEGORY[moment.category] ? ` · ${CATEGORY[moment.category]}` : ""}
          </span>
        </Row>
        <Row label="Template">
          {short.template ? (
            <>
              {short.template.name}
              {short.template.version ? <span className="text-muted"> · version {short.template.version}</span> : null}
            </>
          ) : (
            <span className="text-muted">None</span>
          )}
        </Row>
        <Row label="Brand">{short.brand ? short.brand.name : <span className="text-muted">None</span>}</Row>
        {short.kind === "short" ? <Row label="Made with">{short.auto_edit ? "Auto Edit, then the editor" : "The editor"}</Row> : null}
        <Row label="Duration">{short.duration_seconds ? <span className="tabular">{clock(short.duration_seconds)}</span> : "—"}</Row>
        <Row label="Created">{dayLabel(short.created_at)}</Row>
        {short.kind === "short" ? <Row label="Last rendered">{short.rendered_at ? dayLabel(short.rendered_at) : "—"}</Row> : null}
        {short.render.file_size ? <Row label="File">MP4 · {formatBytes(short.render.file_size)}</Row> : null}
      </dl>
      {short.template || short.brand ? (
        <p className="mt-3 text-caption text-subtle">Template and brand are what this Short was made with; later changes don&apos;t alter it.</p>
      ) : null}
    </Card>
  );
}

/** Every version of this moment; the current one is marked. */
function Versions({ short }: { short: ShortDetail }) {
  if (short.versions.length < 2) return null;
  return (
    <Card>
      <h2 className="text-title">Versions of this moment</h2>
      <ol className="mt-3 space-y-1">
        {short.versions.map((version) => {
          const status = statusLabel(version.status);
          const current = version.id === short.id;
          return (
            <li key={version.id}>
              <Link
                href={shortHref(version.id)}
                aria-current={current ? "page" : undefined}
                className={`flex min-h-11 items-center justify-between gap-3 rounded-control px-3 text-sm transition-colors hover:bg-white/[0.04] focus-visible:outline-2 focus-visible:outline-accent ${
                  current ? "bg-accent/[0.08] text-foreground" : "text-muted"
                }`}
              >
                <span>
                  Version {version.number}
                  <span className="text-subtle"> · {dayLabel(version.created_at)}</span>
                  {current ? <span className="sr-only"> (this version)</span> : null}
                </span>
                <StatusPill tone={status.tone}>{status.label}</StatusPill>
              </Link>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

/** Status, its one-line explanation and the state's one primary action. */
function StatusCard({ short, onAction }: { short: ShortDetail; onAction: (action: ShortAction) => void }) {
  const status = statusLabel(short.status);
  const primary = primaryAction(short);
  const Icon = primary ? ACTION_ICONS[primary.action] : undefined;
  return (
    <Card>
      <p className="text-caption text-subtle">Status</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <StatusPill tone={status.tone}>{status.label}</StatusPill>
        {short.version && short.version.count > 1 ? (
          <span className="text-small text-muted">
            Version {short.version.number} of {short.version.count}
          </span>
        ) : null}
      </div>
      <p role="status" className="mt-2 text-sm text-pretty text-muted">
        {statusDetail(short)}
      </p>
      {short.render.error_message && short.status === "failed" ? (
        <details className="mt-2 text-small text-subtle">
          <summary className="inline-flex cursor-pointer items-center text-muted pointer-coarse:min-h-11 pointer-coarse:min-w-11">Details</summary>
          <p className="mt-1 break-words">{short.render.error_message}</p>
        </details>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-2">
        {primary ? (
          <Button onClick={() => onAction(primary.action)}>
            {Icon ? <Icon aria-hidden="true" /> : null}
            {primary.label}
          </Button>
        ) : null}
        {short.kind === "short" && primary?.action !== "fix_render" ? (
          <ButtonLink href={editorHref(short)} variant="secondary">
            <Pencil aria-hidden="true" />
            Edit
          </ButtonLink>
        ) : null}
        {short.preview === "short" && short.edit_id ? (
          <a
            href={editDownloadUrl(short.edit_id)}
            className="inline-flex h-10 items-center gap-2 rounded-control border border-border-strong bg-surface-2 px-4 text-sm font-medium text-foreground transition-colors hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent pointer-coarse:h-11 [&_svg]:size-4"
          >
            <Download aria-hidden="true" />
            Download
          </a>
        ) : null}
        <ButtonLink href={`/projects/${short.project.id}`} variant="ghost">
          <FolderOpen aria-hidden="true" />
          Open project
        </ButtonLink>
      </div>
    </Card>
  );
}

export function ShortDetailSkeleton() {
  return (
    <div role="status" aria-label="Loading this Short" className="grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <Skeleton className="aspect-[9/16] w-full rounded-card" />
      <div className="space-y-4">
        <Skeleton className="h-32 rounded-card" />
        <Skeleton className="h-64 rounded-card" />
      </div>
    </div>
  );
}

/** /shorts/[id]: one Short — preview, status, its one next action, and what it was made from. */
export function ShortDetailView() {
  const { shortId } = useParams<{ shortId: string }>();
  const router = useRouter();
  const load = useCallback(() => getShort(shortId), [shortId]);
  const { data, error, loading, reload } = useApi(load);
  const [live, setLive] = useState<ShortDetail | null>(null);
  const short = live && live.id === data?.id ? live : data;
  const poll = useCallback(async () => setLive(await getShort(shortId)), [shortId]);
  usePolling(Boolean(short && changing(short)), poll, short?.id ?? null);
  const run = useShortAction();

  // A draft's link follows it once it has a version: show the version's own address.
  useEffect(() => {
    if (data && data.id !== shortId) router.replace(shortHref(data.id));
  }, [data, shortId, router]);

  if (loading && !short) {
    return (
      <>
        <PageHeader title="Short" back={{ href: "/shorts", label: "Shorts" }} />
        <ShortDetailSkeleton />
      </>
    );
  }
  if (error || !short) {
    return (
      <>
        <PageHeader title="Short" back={{ href: "/shorts", label: "Shorts" }} />
        <ErrorState title="This Short couldn't be loaded" message={error ?? "Try again."} onRetry={reload} />
      </>
    );
  }
  const onAction = (action: ShortAction) => {
    if ((action === "publish" || action === "fix_publish") && short.kind === "short") {
      // Publishing happens in place, in the panel below: bring it into view and focus its action.
      const panel = document.getElementById("publishing");
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      panel?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      panel?.querySelector<HTMLElement>("[data-publish-action]")?.focus({ preventScroll: true });
      return;
    }
    if (action === "performance" && document.getElementById("performance")) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      document.getElementById("performance")?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      return;
    }
    run(short, action);
  };
  return (
    <>
      <PageHeader title={short.title} back={{ href: "/shorts", label: "Shorts" }} description={`${short.kind === "draft" ? "Draft" : "Short"} from ${short.project.name}`} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:items-start">
        <div
          className={`mx-auto w-full sm:max-w-xs lg:sticky lg:top-6 lg:max-w-none ${
            // A still (not yet rendered) stays small on phones so the next step stays in view.
            short.preview === "short" ? "max-w-60" : "max-w-44"
          }`}
        >
          <Preview short={short} />
        </div>
        <div className="space-y-6">
          <StatusCard short={short} onAction={onAction} />
          {/* A new publishing state (an upload finished, a retry started) reloads the panel. */}
          <PublishingPanel key={short.publish.state} short={short} onChange={() => void poll()} />
          <Provenance short={short} />
          <PerformancePanel short={short} />
          <Versions short={short} />
        </div>
      </div>
    </>
  );
}
