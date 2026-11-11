"use client";

import { BarChart3, Lightbulb } from "lucide-react";
import { useCallback } from "react";
import { DailyChart } from "@/components/app/analytics/daily-chart";
import { ButtonLink } from "@/components/ui/button-link";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Panel } from "@/components/ui/panel";
import { Spinner } from "@/components/ui/progress";
import {
  getInsights,
  getVideoPerformance,
  type Insights,
  metric,
  percent,
  positionText,
  type VideoPerformanceDetail,
} from "@/lib/performance";
import { analyticsHref, performanceFreshness, performanceTotals, relatedInsights, type ShortDetail } from "@/lib/shorts";
import { useApi } from "@/lib/use-api";

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="min-w-0 rounded-block border border-border bg-surface-2/60 px-3.5 py-3">
      <dt className="text-caption text-subtle">{label}</dt>
      <dd className="mt-1">
        <span className="tabular block text-xl font-semibold text-foreground">{value}</span>
        {note ? <span className="mt-0.5 block text-caption text-subtle">{note}</span> : null}
      </dd>
    </div>
  );
}

function Figures({ detail, insights }: { detail: VideoPerformanceDetail; insights: Insights | null }) {
  const totals = performanceTotals(detail);
  const firstWeek = detail.daily.filter((day) => totals.firstWeek.has(day.date));
  const related = insights ? relatedInsights(insights, detail.id) : [];
  return (
    <div className="space-y-5">
      {detail.simulated ? (
        <InlineAlert tone="warning" title="Simulated figures">
          These come from PeakSift&apos;s test provider, not from YouTube.
        </InlineAlert>
      ) : null}
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Tile label="Views" value={metric(detail.views)} note="Live counter" />
        <Tile label="Watch time" value={totals.watchTime} note={totals.watchTime === "—" ? "Not reported yet" : "Processed days"} />
        <Tile label="Average % viewed" value={percent(detail.average_view_percentage)} note="Above 100% means replays" />
        <Tile label="Likes" value={metric(detail.likes)} />
        <Tile label="Comments" value={metric(detail.comments)} />
        <Tile label="Subscribers gained" value={totals.subscribers} note={totals.subscribers === "—" ? "Not reported yet" : "Processed days"} />
      </dl>
      {firstWeek.length ? (
        <DailyChart
          title="Engaged views per day, first week"
          points={firstWeek.map((day) => ({ date: day.date, value: day.engaged_views }))}
          format={metric}
        />
      ) : null}
      {detail.positions.length ? (
        <ul className="space-y-1 text-sm text-muted">
          {detail.positions.map((p) => (
            <li key={p.metric}>
              First-week {p.metric === "engaged_views" ? "engaged views" : "average % viewed"}: {positionText(p)}.
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">
          Too early to compare: a Short is compared with your others once its first week is complete and enough of your
          Shorts have a complete first week.
        </p>
      )}
      {related.length ? (
        <div className="space-y-2">
          {related.map((insight) => (
            <p key={insight.id} className="flex gap-2.5 rounded-block border border-border bg-surface-2/60 px-3.5 py-3 text-sm text-pretty text-muted">
              <Lightbulb aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-accent-soft" />
              <span>
                <span className="font-medium text-foreground">Observed in your Shorts: </span>
                {insight.statement}
              </span>
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * How a published Short is doing: only what YouTube reported ("—" otherwise), how fresh it is,
 * and observed patterns that include this Short — never a prediction.
 */
export function PerformancePanel({ short }: { short: ShortDetail }) {
  const contentId = short.performance?.content_id ?? null;
  const loadDetail = useCallback(() => (contentId ? getVideoPerformance(contentId) : Promise.resolve(null)), [contentId]);
  const { data: detail, error, loading } = useApi(loadDetail);
  const { data: insights } = useApi(getInsights);
  const onYouTube = short.status === "published" || short.status === "on_youtube";
  if (short.kind !== "short" || !onYouTube) return null;
  const freshness = performanceFreshness(short.analytics, detail ?? null);
  return (
    <Panel
      id="performance"
      title="Performance"
      description={freshness}
      actions={
        contentId ? (
          <ButtonLink href={analyticsHref(contentId)} variant="secondary" size="sm">
            <BarChart3 aria-hidden="true" />
            Full analytics
          </ButtonLink>
        ) : null
      }
    >
      {!contentId ? (
        <p className="text-sm text-muted">Figures appear here once YouTube reports them for this Short.</p>
      ) : loading && !detail ? (
        <p role="status" className="flex items-center gap-2 text-sm text-muted">
          <Spinner /> Loading performance…
        </p>
      ) : error || !detail ? (
        <InlineAlert title="Performance couldn't be loaded">{error ?? "Try again."}</InlineAlert>
      ) : (
        <Figures detail={detail} insights={insights} />
      )}
    </Panel>
  );
}
