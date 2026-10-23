// Pure helpers for performance analytics (no React, no fetch): types, honest formatting
// (null is "not reported", never 0) and the copy for access states and OAuth outcomes.

export type AnalyticsAccess = {
  enabled: boolean;
  connected: boolean;
  connection_status: string | null;
  analytics_access: boolean;
  simulated: boolean;
};

export type SyncInfo = {
  kind: string;
  status: "queued" | "syncing" | "completed" | "failed";
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
};

export type PerformanceWindow = {
  key: "day_1" | "day_3" | "day_7";
  days_expected: number;
  days_reported: number;
  status: "complete" | "open" | "incomplete";
  engaged_views: number | null;
  views: number | null;
  average_view_percentage: number | null;
  watch_time_seconds: number | null;
  likes: number | null;
  comments: number | null;
  subscribers_gained: number | null;
};

export type Position = {
  metric: "engaged_views" | "average_view_percentage";
  window: string;
  value: number;
  median: number;
  ratio: number | null;
  label: "above" | "near" | "below";
};

export type Baseline = {
  metric: "engaged_views" | "average_view_percentage";
  window: string;
  sample_size: number;
  minimum_sample: number;
  median: number | null;
  reliable: boolean;
};

export type VideoPerformance = {
  id: string;
  project_id: string;
  edit_id: string | null;
  title: string;
  published_at: string;
  duration_seconds: number | null;
  privacy: string | null;
  remote_status: "active" | "remote_missing" | "unknown";
  source: "youtube" | "fake" | null;
  simulated: boolean;
  video_url: string | null;
  views: number | null;
  likes: number | null;
  comments: number | null;
  counters_observed_at: string | null;
  engaged_views: number | null;
  average_view_percentage: number | null;
  processed_through: string | null;
  processed_days: number;
  last_synced_at: string | null;
  next_sync_at: string | null;
  latest_sync: SyncInfo | null;
  recipe: string | null;
  windows: PerformanceWindow[];
  positions: Position[];
};

export type PerformanceOverview = { access: AnalyticsAccess; videos: VideoPerformance[]; baselines: Baseline[] };

export type DailyMetric = {
  date: string;
  metric_version: string;
  views: number | null;
  engaged_views: number | null;
  likes: number | null;
  comments: number | null;
  watch_time_seconds: number | null;
  average_view_duration_seconds: number | null;
  average_view_percentage: number | null;
  subscribers_gained: number | null;
};

export type VideoPerformanceDetail = VideoPerformance & {
  provenance: Record<string, unknown>;
  daily: DailyMetric[];
  snapshots: { observed_at: string; views: number | null; likes: number | null; comments: number | null }[];
  syncs: SyncInfo[];
};

/** Where the creator stands, in the order the page must handle it. */
export type AccessState = "disabled" | "not_connected" | "reconnect" | "upgrade" | "ready";

export function accessState(access: AnalyticsAccess): AccessState {
  if (!access.enabled) return "disabled";
  if (!access.connected) return "not_connected";
  if (access.connection_status !== "connected") return "reconnect";
  if (!access.analytics_access) return "upgrade";
  return "ready";
}

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const whole = new Intl.NumberFormat("en");

/** "—" for not reported (never "0"); compact from 10,000 up. */
export function metric(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return Math.abs(value) >= 10_000 ? compact.format(value) : whole.format(value);
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)}%`;
}

export function seconds(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)} s`;
}

/** "2026-10-20" → "Oct 20" (a reporting day; no timezone shift). */
export function reportingDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en", {
    month: "short", day: "numeric", timeZone: "UTC",
  });
}

export function viewDefinition(version: string): string {
  if (version === "youtube_views_2026_08") return "Views counted from playback start (since Aug 27, 2026)";
  if (version === "youtube_views_2025_03") return "Shorts views count starts and replays (Mar 31, 2025 – Aug 26, 2026)";
  return "Earlier YouTube view definition";
}

export function syncLabel(sync: SyncInfo | null): string | null {
  if (!sync) return null;
  if (sync.status === "queued" || sync.status === "syncing") return "Refreshing…";
  if (sync.status === "failed") return sync.error_message ?? "The last refresh failed";
  return null;
}

/** What the analytics OAuth callback reported (``?analytics=…``), or null. */
export function analyticsOutcome(
  params: URLSearchParams,
): { ok: boolean; title: string; message: string } | null {
  const outcome = params.get("analytics");
  if (outcome === "connected") {
    return { ok: true, title: "Analytics connected", message: "Analytics access is connected. Metrics for your PeakSift uploads will appear as YouTube processes them (usually 2–3 days)." };
  }
  if (outcome !== "error") return null;
  const reasons: Record<string, string> = {
    analytics_not_granted: "Both read-only permissions are needed to show metrics. Nothing changed: publishing keeps working as before.",
    insufficient_scope: "Upload permission was unticked, so nothing changed. Connect analytics again and keep upload allowed.",
    denied: "You declined on Google's consent screen. Nothing changed: publishing keeps working as before.",
    invalid_state: "That link was not valid for this account. Start again from here.",
    expired: "That took too long. Start again from here.",
    signin_required: "Sign in to PeakSift, then try again.",
    missing_refresh_token: "Google did not grant lasting access. Try again.",
    exchange_failed: "Google could not complete the request. Try again.",
    disabled: "Analytics is not enabled on this server.",
  };
  return {
    ok: false,
    title: "Analytics not connected",
    message: reasons[params.get("reason") ?? ""] ?? "Analytics access was not connected. Try again.",
  };
}

/** Bars for one daily series: missing values stay gaps (never drawn as 0). */
export function seriesOf(days: DailyMetric[], key: "engaged_views" | "average_view_percentage") {
  return days.map((day) => ({ date: day.date, value: day[key] }));
}

/** A clean axis top (1, 2, 2.5 or 5 × 10^n) at or above the largest value. */
export function niceMax(values: (number | null)[]): number {
  const max = Math.max(0, ...values.filter((v): v is number => v !== null));
  if (max <= 0) return 1;
  const exponent = 10 ** Math.floor(Math.log10(max));
  for (const step of [1, 2, 2.5, 5, 10]) if (step * exponent >= max) return step * exponent;
  return 10 * exponent;
}

export const WINDOW_LABELS: Record<PerformanceWindow["key"], string> = {
  day_1: "Day of publication",
  day_3: "First 3 days",
  day_7: "First 7 days",
};

/** A window in words: its figure when complete, otherwise why there is none (never 0). */
export function windowSummary(w: PerformanceWindow | undefined): string {
  if (!w) return "Not synced yet";
  if (w.status === "open") return `Still being processed (${w.days_reported} of ${w.days_expected} days so far)`;
  if (w.status === "incomplete") return "Not every day was reported, so it is not compared";
  return `${metric(w.engaged_views)} engaged views`;
}

/** "1.4× your usual" style wording; observational, never a verdict or a prediction. */
export function positionText(p: Position): string {
  const where = { above: "above your usual", near: "near your usual", below: "below your usual" }[p.label];
  // Two decimals below 2× so a "near" 0.85× never reads as 0.8×.
  const ratio = p.ratio === null ? "" : ` (${p.ratio.toFixed(p.ratio < 2 ? 2 : 1)}× your median)`;
  return `${where}${ratio}`;
}

/** The creator's own usual short, or why there is no reliable pattern yet. */
export function baselineText(b: Baseline | undefined): string {
  if (!b) return "No reliable pattern yet.";
  if (!b.reliable) {
    return `No reliable pattern yet: ${b.sample_size} of ${b.minimum_sample} shorts have a complete first week.`;
  }
  const value = b.metric === "average_view_percentage" ? percent(b.median) : metric(b.median);
  const what = b.metric === "average_view_percentage" ? "viewed on average" : "engaged views";
  return `${value} ${what} in the first week (median of your ${b.sample_size} comparable shorts)`;
}

export type Insight = {
  id: string;
  rank: number;
  feature: string;
  value: string;
  metric: "engaged_views" | "average_view_percentage";
  window: string;
  direction: "higher" | "lower";
  group_size: number;
  comparison_size: number;
  group_median: number;
  comparison_median: number;
  ratio: number | null;
  consistency: number;
  confidence: "limited" | "moderate";
  statement: string;
  dismissed: boolean;
  group: { id: string; title: string }[];
  comparison: { id: string; title: string }[];
};

export type Insights = {
  status: "ready" | "insufficient";
  source: string;
  simulated: boolean;
  engine_version: string;
  computed_at: string;
  sample_size: number;
  minimum_sample: number;
  minimum_group: number;
  insights: Insight[];
};

/** What to say when there are no visible patterns (never a fake insight). */
export function insightsEmptyText(data: Insights): string {
  if (data.status === "insufficient") {
    return `No reliable pattern yet: ${data.sample_size} of ${data.minimum_sample} shorts have a complete first week to compare.`;
  }
  return `No clear pattern in your recent uploads: nothing passed the checks across ${data.sample_size} comparable shorts.`;
}

export function confidenceText(insight: Insight): string {
  const basis = `${insight.group_size} vs ${insight.comparison_size} shorts`;
  return insight.confidence === "moderate" ? `Moderate confidence · ${basis}` : `Limited evidence · ${basis}`;
}

export type Total = { value: number | null; reported: number; of: number };

/** A sum over the Shorts that reported the figure; null (shown "—") when none did — never 0. */
function total(videos: VideoPerformance[], pick: (video: VideoPerformance) => number | null): Total {
  const values = videos.map(pick).filter((v): v is number => v !== null && v !== undefined);
  return { value: values.length ? values.reduce((sum, v) => sum + v, 0) : null, reported: values.length, of: videos.length };
}

/** The summary cards: only figures YouTube reported, with how many Shorts they cover. */
export function summaryTotals(videos: VideoPerformance[]) {
  return {
    views: total(videos, (v) => v.views),
    engaged: total(videos, (v) => v.engaged_views),
    likes: total(videos, (v) => v.likes),
  };
}

/** "from 3 of 5 Shorts" when a total does not cover every Short; null when it does (or none). */
export function coverage(t: Total): string | null {
  return t.reported > 0 && t.reported < t.of ? `from ${t.reported} of ${t.of} Shorts` : null;
}

/** "Analytics updated through Oct 20": the newest day YouTube has processed for any Short. */
export function freshness(videos: VideoPerformance[]): string | null {
  const days = videos.map((v) => v.processed_through).filter((d): d is string => !!d).sort();
  return days.length ? `Analytics updated through ${reportingDay(days[days.length - 1])}` : null;
}
