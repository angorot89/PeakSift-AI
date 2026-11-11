"use client";

import { ExternalLink, RefreshCw } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { useRefresh } from "@/components/app/analytics-view";
import { DailyChart } from "@/components/app/analytics/daily-chart";
import { PageHeader } from "@/components/app/page-header";
import { ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/format";
import {
  getVideoPerformance,
  metric,
  percent,
  positionText,
  WINDOW_LABELS,
  reportingDay,
  seconds,
  seriesOf,
  syncLabel,
  viewDefinition,
  type VideoPerformanceDetail,
} from "@/lib/performance";
import { useApi } from "@/lib/use-api";
import { usePolling } from "@/lib/use-polling";

type Provenance = Record<string, unknown>;
const section = (p: Provenance, key: string) => (p[key] ?? {}) as Record<string, unknown>;

/** How the short was made, from the normalized snapshot recorded when it was published. */
export function provenanceRows(p: Provenance): [string, string][] {
  const rows: [string, string][] = [];
  const auto = section(p, "auto_edit");
  rows.push(["Made with", auto.used ? `Auto Edit (${auto.planner === "local_ai" ? "local AI" : "rules"})` : "Editor, by hand"]);
  if (p.recipe) rows.push(["Recipe", String(p.recipe)]);
  if (p.layout) rows.push(["Framing", String(p.layout).replaceAll("_", " ")]);
  const captions = section(p, "captions");
  rows.push(["Captions", captions.enabled ? [captions.preset, captions.position].filter(Boolean).join(", ") || "on" : "off"]);
  const hook = section(p, "hook");
  rows.push(["Opening hook", hook.enabled ? `${hook.length_chars} characters${hook.duration_seconds ? `, ${hook.duration_seconds} s` : ""}` : "none"]);
  const visuals = section(p, "visuals");
  rows.push(["Visuals", visuals.count ? `${visuals.count} (${visuals.cutaways} cutaways, ${visuals.pips} picture-in-picture, ${visuals.overlays} overlays)` : "none"]);
  const audio = section(p, "audio");
  rows.push(["Audio", [audio.music ? `music${audio.ducking ? `, ${audio.ducking} ducking` : ""}` : "no music", `${audio.sfx_count ?? 0} sound effects`].join(" · ")]);
  const candidate = section(p, "candidate");
  if (candidate.rank) {
    rows.push(["Moment", `#${candidate.rank}${candidate.category ? `, ${candidate.category}` : ""}${candidate.score !== undefined && candidate.score !== null ? ` (editorial score ${candidate.score}/100)` : ""}`]);
  }
  return rows;
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-3">
      <dt className="text-xs text-subtle">{label}</dt>
      <dd className="mt-1">
        <span className="tabular block text-xl font-semibold text-foreground">{value}</span>
        {note ? <span className="mt-0.5 block text-caption text-subtle">{note}</span> : null}
      </dd>
    </div>
  );
}

export function VideoAnalyticsView() {
  const { contentId } = useParams<{ contentId: string }>();
  const load = useCallback(() => getVideoPerformance(contentId), [contentId]);
  const { data, error, loading, reload } = useApi(load);
  const [live, setLive] = useState<VideoPerformanceDetail | null>(null);
  const video = live ?? data;
  const poll = useCallback(async () => setLive(await getVideoPerformance(contentId)), [contentId]);
  const refreshing = video?.latest_sync?.status === "queued" || video?.latest_sync?.status === "syncing";
  usePolling(Boolean(refreshing), poll);
  const { busy, message, refresh } = useRefresh(contentId, poll);
  const versions = useMemo(() => [...new Set(video?.daily.map((d) => d.metric_version) ?? [])], [video]);

  if (loading && !video) {
    return (
      <div role="status" aria-label="Loading analytics" className="space-y-3">
        <Skeleton className="h-10 w-2/3 rounded-lg" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    );
  }
  if (error || !video) return <ErrorState title="Analytics couldn't be loaded" message={error ?? "Try again."} onRetry={reload} />;

  const sync = syncLabel(video.latest_sync);
  return (
    <>
      <PageHeader
        title={video.title}
        back={{ href: "/analytics", label: "Analytics" }}
        description={`Published ${formatDate(video.published_at)}${video.privacy ? ` · ${video.privacy}` : ""}`}
        action={
          <>
            {video.video_url ? (
              <a href={video.video_url} target="_blank" rel="noopener noreferrer"
                 className="inline-flex items-center gap-1 rounded-md px-3 py-2 text-sm text-muted hover:text-foreground">
                Open on YouTube <ExternalLink aria-hidden="true" className="size-3.5" />
              </a>
            ) : null}
            <Button variant="secondary" onClick={refresh} disabled={busy || refreshing}>
              <RefreshCw aria-hidden="true" />
              {refreshing ? "Refreshing…" : "Refresh"}
            </Button>
          </>
        }
      />
      <div className="space-y-6">
        {video.simulated ? (
          <InlineAlert tone="warning" title="Simulated metrics">
            These figures come from PeakSift&apos;s deterministic test provider, not from YouTube.
          </InlineAlert>
        ) : null}
        {video.remote_status === "remote_missing" ? (
          <InlineAlert tone="info" title="No longer on YouTube">
            YouTube no longer returns this video (deleted or unavailable). Figures collected before are kept.
          </InlineAlert>
        ) : null}
        {sync && !refreshing ? <InlineAlert tone="warning" title="Last refresh did not complete">{sync}</InlineAlert> : null}
        {message ? <InlineAlert tone="warning" title="Not refreshed">{message}</InlineAlert> : null}

        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <Tile label="Views" value={metric(video.views)} note="Live public counter" />
          <Tile label="Engaged views" value={metric(video.engaged_views)} note="Processed days" />
          <Tile label="Avg. % viewed" value={percent(video.average_view_percentage)} note="Above 100% means replays" />
          <Tile label="Likes" value={metric(video.likes)} />
          <Tile label="Comments" value={metric(video.comments)} />
        </dl>

        <Panel
          title="Early windows"
          description="The same early windows for every short, in YouTube's reporting days from the day of publication (so “day of publication” is roughly the first 24 hours). Only complete windows are compared with your other shorts."
        >
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Early windows (scrolls sideways)">
            <table className="w-full min-w-[520px] text-left text-sm">
              <caption className="sr-only">Early windows</caption>
              <thead className="text-xs text-subtle">
                <tr>
                  {["Window", "Engaged views", "Avg. % viewed", "Likes", "Comments", "Status"].map((h) => (
                    <th key={h} scope="col" className="px-2 py-1.5 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="tabular">
                {video.windows.map((w) => (
                  <tr key={w.key} className="border-t border-border">
                    <th scope="row" className="px-2 py-1.5 font-normal text-muted">{WINDOW_LABELS[w.key]}</th>
                    <td className="px-2 py-1.5">{metric(w.engaged_views)}</td>
                    <td className="px-2 py-1.5">{percent(w.average_view_percentage)}</td>
                    <td className="px-2 py-1.5">{metric(w.likes)}</td>
                    <td className="px-2 py-1.5">{metric(w.comments)}</td>
                    <td className="px-2 py-1.5 text-muted">
                      {w.status === "complete" ? "Complete" : w.status === "open" ? `Processing (${w.days_reported}/${w.days_expected} days)` : "Days missing"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {video.positions.length ? (
            <ul className="mt-4 space-y-1 text-sm text-muted">
              {video.positions.map((p) => (
                <li key={p.metric}>
                  First-week {p.metric === "engaged_views" ? "engaged views" : "average % viewed"}: {positionText(p)}.
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-4 text-sm text-muted">
              No comparison yet: a short is compared with your usual once its first week is complete and at least five of your shorts have a complete first week.
            </p>
          )}
        </Panel>

        <Panel
          title="Daily"
          description={
            video.processed_through
              ? `Processed by YouTube through ${reportingDay(video.processed_through)} (Pacific Time). Recent days may still change.`
              : "YouTube has not processed analytics for this short yet (usually 2–3 days)."
          }
        >
          {video.daily.length ? (
            <div className="space-y-8">
              <div className="grid gap-8 lg:grid-cols-2">
                <DailyChart title="Engaged views per day" points={seriesOf(video.daily, "engaged_views")} format={metric} />
                <DailyChart title="Average % viewed per day" points={seriesOf(video.daily, "average_view_percentage")}
                            format={(v) => (v === null ? "—" : `${Math.round(v)}%`)} />
              </div>
              {versions.length > 1 ? (
                <p className="text-xs text-subtle">
                  YouTube changed how views are counted during this period; each day below shows the definition in force. Engaged views kept one definition throughout.
                </p>
              ) : null}
              <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Daily figures (scrolls sideways)">
                <table className="w-full min-w-[560px] text-left text-sm">
                  <caption className="sr-only">Daily figures</caption>
                  <thead className="text-xs text-subtle">
                    <tr>
                      {["Day", "Views", "Engaged", "Avg. % viewed", "Avg. duration", "Likes", "Comments", "Subscribers"].map((h) => (
                        <th key={h} scope="col" className="px-2 py-1.5 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="tabular">
                    {video.daily.map((day) => (
                      <tr key={`${day.date}-${day.metric_version}`} className="border-t border-border">
                        <th scope="row" className="px-2 py-1.5 font-normal text-muted" title={viewDefinition(day.metric_version)}>
                          {reportingDay(day.date)}
                        </th>
                        <td className="px-2 py-1.5">{metric(day.views)}</td>
                        <td className="px-2 py-1.5">{metric(day.engaged_views)}</td>
                        <td className="px-2 py-1.5">{percent(day.average_view_percentage)}</td>
                        <td className="px-2 py-1.5">{seconds(day.average_view_duration_seconds)}</td>
                        <td className="px-2 py-1.5">{metric(day.likes)}</td>
                        <td className="px-2 py-1.5">{metric(day.comments)}</td>
                        <td className="px-2 py-1.5">{metric(day.subscribers_gained)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted">No processed days yet. “—” means YouTube has not reported a figure; it is never shown as zero.</p>
          )}
        </Panel>

        <Panel title="How this Short was made" description="Recorded when it was published. Used later to compare your own Shorts with each other.">
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            {provenanceRows(video.provenance).map(([label, value]) => (
              <div key={label} className="flex justify-between gap-3 border-b border-border py-1.5">
                <dt className="text-muted">{label}</dt>
                <dd className="text-right text-foreground">{value}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      </div>
    </>
  );
}
