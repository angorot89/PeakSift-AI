"use client";

import { BarChart3, ExternalLink, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";
import { AnalyticsAccessGate } from "@/components/app/analytics/analytics-access";
import { InsightsPanel } from "@/components/app/analytics/insights-panel";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { ApiError, errorMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import {
  accessState,
  baselineText,
  getPerformance,
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

function VideoStatus({ video }: { video: VideoPerformance }) {
  const syncing = syncLabel(video.latest_sync);
  return (
    <div className="flex flex-wrap gap-1.5">
      {video.simulated ? <StatusPill tone="warning">Simulated data</StatusPill> : null}
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
      <dd className="tabular mt-0.5 text-base font-semibold text-foreground" title={hint}>
        {value}
      </dd>
    </div>
  );
}

function VideoRow({ video, canRefresh, onQueued }: { video: VideoPerformance; canRefresh: boolean; onQueued: () => void }) {
  const { busy, message, refresh } = useRefresh(video.id, onQueued);
  return (
    <li className="rounded-xl border border-border bg-surface px-4 py-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <Link
            href={`/analytics/${video.id}`}
            className="block truncate font-medium text-foreground hover:text-accent-soft focus-visible:outline-2 focus-visible:outline-accent"
          >
            {video.title}
          </Link>
          <p className="mt-0.5 text-xs text-muted">
            Published {formatDate(video.published_at)}
            {video.recipe ? ` · ${video.recipe === "manual" ? "edited by hand" : `${video.recipe} recipe`}` : ""}
            {video.privacy ? ` · ${video.privacy}` : ""}
          </p>
          <div className="mt-2">
            <VideoStatus video={video} />
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
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
        <Figure label="Views (live counter)" value={metric(video.views)} />
        <Figure label="Engaged views (processed)" value={metric(video.engaged_views)} />
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
    <section aria-labelledby="usual-heading" className="rounded-xl border border-border bg-surface-2 px-4 py-4">
      <h2 id="usual-heading" className="text-sm font-medium text-foreground">Your usual short</h2>
      <p className="mt-1 text-sm text-muted">{baselineText(engaged)}</p>
      {engaged?.reliable && retention?.reliable ? (
        <p className="mt-0.5 text-sm text-muted">{baselineText(retention)}</p>
      ) : null}
      <p className="mt-2 text-xs text-subtle">
        Compared only with your own shorts, over the same first week. Other creators&apos; data is never used.
      </p>
    </section>
  );
}

/** The creator's published shorts and what YouTube reported for them. */
export function AnalyticsView() {
  const { data, error, loading, reload } = useApi(getPerformance);
  // Polled updates while a refresh runs; the first load comes from useApi.
  const [live, setLive] = useState<PerformanceOverview | null>(null);
  const overview = live ?? data;
  const poll = useCallback(async () => setLive(await getPerformance()), []);
  usePolling(Boolean(overview?.videos.some(isRefreshing)), poll);

  return (
    <>
      <PageHeader
        title="Analytics"
        description="How your published shorts are doing on YouTube: observed figures, not predictions. YouTube processes analytics with a delay of about 2–3 days."
      />
      {loading && !overview ? (
        <div role="status" aria-label="Loading analytics" className="space-y-3">
          <Skeleton className="h-28 w-full rounded-xl" />
          <Skeleton className="h-28 w-full rounded-xl" />
        </div>
      ) : error || !overview ? (
        <ErrorState title="Analytics unavailable" message={error ?? "Try again."} onRetry={reload} />
      ) : (
        <div className="space-y-6">
          {overview.access.simulated ? (
            <InlineAlert tone="warning" title="Simulated metrics">
              This server uses PeakSift&apos;s deterministic test provider. Every figure below is simulated, not real YouTube data.
            </InlineAlert>
          ) : null}
          {accessState(overview.access) !== "ready" ? <AnalyticsAccessGate access={overview.access} /> : null}
          {overview.videos.some((v) => v.source) ? <UsualShort overview={overview} /> : null}
          {overview.videos.some((v) => v.source) ? <InsightsPanel /> : null}
          {overview.videos.length === 0 ? (
            <EmptyState
              icon={BarChart3}
              title="No published shorts yet"
              description="Shorts you publish to YouTube from PeakSift appear here. Other videos on your channel are never tracked."
            />
          ) : (
            <section aria-labelledby="published-heading">
              <h2 id="published-heading" className="mb-3 text-sm font-medium text-muted">
                Published from PeakSift ({overview.videos.length})
              </h2>
              <ul className="space-y-3">
                {overview.videos.map((video) => (
                  <VideoRow
                    key={video.id}
                    video={video}
                    canRefresh={accessState(overview.access) === "ready"}
                    onQueued={poll}
                  />
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </>
  );
}
