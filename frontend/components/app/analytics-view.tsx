"use client";

import { Activity, BarChart3, CalendarClock, ExternalLink, Eye, Heart, RefreshCw, Smartphone, Upload, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";
import { AnalyticsAccessGate } from "@/components/app/analytics/analytics-access";
import { InsightsPanel } from "@/components/app/analytics/insights-panel";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { SectionHeader } from "@/components/ui/section-header";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Skeleton } from "@/components/ui/skeleton";
import { VideoFrame } from "@/components/ui/video-frame";
import { editContentUrl } from "@/lib/edits";
import { StatusPill } from "@/components/ui/status-pill";
import { ApiError, errorMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import {
  accessState,
  baselineText,
  coverage,
  freshness,
  getPerformance,
  summaryTotals,
  type Total,
  positionText,
  windowSummary,
  metric,
  percent,
  refreshVideoPerformance,
  reportingDay,
  syncLabel,
  type PerformanceOverview,
  type VideoPerformance,
} from "@/lib/performance";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";

/** The most recent Shorts listed before "Show all". */
const RECENT_SHORTS = 6;

const isRefreshing = (video: VideoPerformance) =>
  video.latest_sync?.status === "queued" || video.latest_sync?.status === "syncing";

export function useRefresh(id: string, onQueued: () => void) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    setBusy(true);
    setMessage(null);
    try {
      await refreshVideoPerformance(id);
      onQueued();
    } catch (failure) {
      setMessage(
        failure instanceof ApiError && failure.status === 429
          ? "Metrics were refreshed moments ago. Try again in a few minutes."
          : errorMessage(failure),
      );
    } finally {
      setBusy(false);
    }
  }, [id, onQueued]);
  return { busy, message, refresh };
}

function VideoStatus({ video, pageSimulated }: { video: VideoPerformance; pageSimulated: boolean }) {
  const syncing = syncLabel(video.latest_sync);
  return (
    <div className="flex flex-wrap gap-1.5 empty:hidden">
      {/* Said once for the whole page when the whole page is simulated. */}
      {video.simulated && !pageSimulated ? <StatusPill tone="warning">Simulated data</StatusPill> : null}
      {video.remote_status === "remote_missing" ? <StatusPill tone="neutral">No longer on YouTube</StatusPill> : null}
      {syncing ? (
        <StatusPill tone={video.latest_sync?.status === "failed" ? "warning" : "processing"}>
          {video.latest_sync?.status === "failed" ? "Refresh failed" : syncing}
        </StatusPill>
      ) : null}
    </div>
  );
}

function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-subtle">{label}</dt>
      <dd className="tabular mt-0.5 text-lg font-semibold text-foreground" title={hint}>
        {value}
      </dd>
    </div>
  );
}

function VideoRow({
  video,
  canRefresh,
  pageSimulated,
  onQueued,
}: {
  video: VideoPerformance;
  canRefresh: boolean;
  pageSimulated: boolean;
  onQueued: () => void;
}) {
  const { busy, message, refresh } = useRefresh(video.id, onQueued);
  return (
    <li className="flex gap-4 rounded-card border border-border bg-surface p-4 shadow-card sm:p-5">
      <VideoFrame
        src={video.edit_id ? editContentUrl(video.edit_id) : null}
        ratio="vertical"
        icon={Smartphone}
        className="w-16 shrink-0 self-start rounded-control border border-border sm:w-20"
      />
      <div className="min-w-0 flex-1">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <Link
            href={`/analytics/${video.id}`}
            className="block truncate font-medium text-foreground hover:text-accent-soft focus-visible:outline-2 focus-visible:outline-accent pointer-coarse:-my-2.5 pointer-coarse:py-2.5"
          >
            {video.title}
          </Link>
          <p className="mt-0.5 text-xs text-muted">
            Published {formatDate(video.published_at)}
            {video.recipe ? ` · ${video.recipe === "manual" ? "edited by hand" : `${video.recipe} recipe`}` : ""}
            {video.privacy ? ` · ${video.privacy}` : ""}
          </p>
          <div className="mt-2 empty:hidden">
            <VideoStatus video={video} pageSimulated={pageSimulated} />
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          {video.edit_id ? (
            <Link
              href={`/shorts/${video.edit_id}`}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent pointer-coarse:min-h-11"
            >
              Open Short
            </Link>
          ) : null}
          {video.video_url ? (
            <a
              href={video.video_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted hover:text-foreground"
            >
              YouTube <ExternalLink aria-hidden="true" className="size-3" />
            </a>
          ) : null}
          {canRefresh ? (
            <Button variant="secondary" size="sm" onClick={refresh} disabled={busy || isRefreshing(video)}>
              <RefreshCw aria-hidden="true" />
              Refresh
            </Button>
          ) : null}
        </div>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-5">
        <Figure label="Views" value={metric(video.views)} hint="YouTube's live counter" />
        <Figure label="Engaged views" value={metric(video.engaged_views)} hint="Processed by YouTube, about 2–3 days behind" />
        <Figure label="Avg. % viewed" value={percent(video.average_view_percentage)} hint="Weighted by daily views; above 100% means replays" />
        <Figure label="Likes" value={metric(video.likes)} />
        <Figure label="Comments" value={metric(video.comments)} />
      </dl>
      <FirstWeek video={video} />
      <p className="mt-3 text-xs text-subtle">
        {video.last_synced_at
          ? `Updated ${formatDate(video.last_synced_at)}. ${video.processed_through ? `Processed analytics through ${reportingDay(video.processed_through)} (Pacific Time).` : "YouTube has not processed analytics for this short yet."}`
          : "Not synced yet."}
      </p>
      {message ? <p className="mt-2 text-xs text-warning">{message}</p> : null}
      </div>
    </li>
  );
}

function FirstWeek({ video }: { video: VideoPerformance }) {
  if (!video.source) return null;
  const week = video.windows.find((w) => w.key === "day_7");
  const placed = video.positions.find((p) => p.metric === "engaged_views");
  return (
    <p className="mt-3 text-sm text-muted">
      <span className="text-foreground">First 7 days:</span> {windowSummary(week)}
      {placed ? <> · {positionText(placed)}</> : null}
    </p>
  );
}

function UsualShort({ overview }: { overview: PerformanceOverview }) {
  const engaged = overview.baselines.find((b) => b.metric === "engaged_views");
  const retention = overview.baselines.find((b) => b.metric === "average_view_percentage");
  return (
    <section aria-labelledby="usual-heading" className="rounded-card border border-border bg-surface p-5 shadow-card">
      <h3 id="usual-heading" className="text-title text-foreground">Your usual Short</h3>
      <p className="mt-1 text-sm text-muted">{baselineText(engaged)}</p>
      {engaged?.reliable && retention?.reliable ? (
        <p className="mt-0.5 text-sm text-muted">{baselineText(retention)}</p>
      ) : null}
      <p className="mt-2 text-xs text-subtle">
        Compared only with your own Shorts, over the same first week. Other creators&apos; data is never used.
      </p>
    </section>
  );
}

const TILE = {
  accent: "bg-accent/15 text-accent-soft",
  info: "bg-info/15 text-sky-200",
  violet: "bg-violet/15 text-violet-200",
  success: "bg-success/15 text-emerald-200",
};

function SummaryCard({
  label,
  icon: Icon,
  tone,
  total,
  count,
}: {
  label: string;
  icon: LucideIcon;
  tone: keyof typeof TILE;
  total?: Total;
  count?: number;
}) {
  const note = total ? coverage(total) : null;
  return (
    <div className="rounded-card border border-border bg-surface p-4 shadow-card sm:p-5">
      <dt className="flex items-center gap-2.5 text-sm text-muted">
        <span aria-hidden="true" className={`flex size-9 items-center justify-center rounded-block ${TILE[tone]}`}>
          <Icon className="size-[18px]" />
        </span>
        {label}
      </dt>
      <dd className="tabular mt-3 text-3xl leading-tight font-bold tracking-tight text-foreground">{total ? metric(total.value) : metric(count)}</dd>
      {note ? <dd className="mt-1 text-caption text-subtle">{note}</dd> : null}
    </div>
  );
}

/** At a glance: only figures YouTube reported ("—" when none did), summed over the Shorts shown. */
function Summary({ videos }: { videos: VideoPerformance[] }) {
  const totals = summaryTotals(videos);
  return (
    <section aria-labelledby="glance-heading">
      <h2 id="glance-heading" className="sr-only">
        At a glance
      </h2>
      <dl className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <SummaryCard label="Shorts published" icon={Upload} tone="accent" count={videos.length} />
        <SummaryCard label="Views" icon={Eye} tone="info" total={totals.views} />
        <SummaryCard label="Engaged views" icon={Activity} tone="violet" total={totals.engaged} />
        <SummaryCard label="Likes" icon={Heart} tone="success" total={totals.likes} />
      </dl>
    </section>
  );
}

/** The creator's published shorts and what YouTube reported for them. */
export function AnalyticsView({ projectId }: { projectId?: string } = {}) {
  const { data, error, loading, reload } = useApi(getPerformance);
  // Polled updates while a refresh runs; the first load comes from useApi.
  const [live, setLive] = useState<PerformanceOverview | null>(null);
  const all = live ?? data;
  // Inside a project: only the shorts published from it (comparisons stay creator-wide).
  const overview = all && projectId ? { ...all, videos: all.videos.filter((v) => v.project_id === projectId) } : all;
  const poll = useCallback(async () => setLive(await getPerformance()), []);
  usePolling(Boolean(overview?.videos.some(isRefreshing)), poll);
  const fresh = overview ? freshness(overview.videos) : null;
  const [showAll, setShowAll] = useState(false);
  const listed = overview ? (showAll ? overview.videos : overview.videos.slice(0, RECENT_SHORTS)) : [];
  const lead = fresh
    ? `${fresh} (Pacific Time). Observed figures, not predictions.`
    : "Observed figures from YouTube, not predictions. YouTube processes analytics with a delay of about 2–3 days.";

  return (
    <>
      {projectId ? (
        <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-section">How this project&apos;s Shorts are doing</h2>
            <p className="mt-1 text-sm text-muted">{lead}</p>
          </div>
          <Link href="/analytics" className="inline-flex min-h-11 items-center text-sm text-accent-soft hover:underline">
            All your analytics and patterns
          </Link>
        </div>
      ) : (
        <PageHeader
          size="hero"
          title="Analytics"
          description={
            <>
              How are my Shorts doing?
              <span className="mt-2 flex items-start gap-2 text-small text-subtle">
                <CalendarClock aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                {lead}
              </span>
            </>
          }
        />
      )}
      {loading && !overview ? (
        <div role="status" aria-label="Loading analytics" className="space-y-3">
          <Skeleton className="h-28 w-full rounded-card" />
          <Skeleton className="h-28 w-full rounded-card" />
        </div>
      ) : error || !overview ? (
        <ErrorState title="Analytics couldn't be loaded" message={error ?? "Try again."} onRetry={reload} />
      ) : (
        <div className="space-y-8">
          {overview.access.simulated ? (
            <InlineAlert tone="warning" title="Simulated metrics">
              This server uses PeakSift&apos;s deterministic test provider. Every figure below is simulated, not real YouTube data.
            </InlineAlert>
          ) : null}
          {accessState(overview.access) !== "ready" ? <AnalyticsAccessGate access={overview.access} /> : null}
          {overview.videos.length ? <Summary videos={overview.videos} /> : null}
          {!projectId && overview.videos.some((v) => v.source) ? (
            <section aria-labelledby="working-heading">
              <SectionHeader
                id="working-heading"
                title="What seems to be working"
                description="Your usual Short, and patterns among your own Shorts."
              />
              <div className="grid gap-3 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
                <UsualShort overview={overview} />
                <InsightsPanel />
              </div>
            </section>
          ) : null}
          {overview.videos.length === 0 ? (
            <EmptyState
              icon={BarChart3}
              title="No published Shorts yet"
              description={
                projectId
                  ? "Shorts you publish to YouTube from this project appear here, with how they are doing."
                  : "Shorts you publish to YouTube from PeakSift appear here. Other videos on your channel are never tracked."
              }
            />
          ) : (
            <section aria-labelledby="published-heading">
              <SectionHeader
                id="published-heading"
                title={`Your Shorts (${overview.videos.length})`}
                description="Published from PeakSift. Other videos on your channel are never tracked."
              />
              <ul className="space-y-3">
                {listed.map((video) => (
                  <VideoRow
                    key={video.id}
                    video={video}
                    canRefresh={accessState(overview.access) === "ready"}
                    pageSimulated={overview.access.simulated}
                    onQueued={poll}
                  />
                ))}
              </ul>
              {listed.length < overview.videos.length ? (
                <div className="mt-3 flex justify-center">
                  <Button variant="secondary" onClick={() => setShowAll(true)}>
                    Show all {overview.videos.length}
                  </Button>
                </div>
              ) : null}
            </section>
          )}
        </div>
      )}
    </>
  );
}
