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
};

export type PerformanceOverview = { access: AnalyticsAccess; videos: VideoPerformance[] };

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
export function analyticsOutcome(params: URLSearchParams): { ok: boolean; message: string } | null {
  const outcome = params.get("analytics");
  if (outcome === "connected") {
    return { ok: true, message: "Analytics access is connected. Metrics for your PeakSift uploads will appear as YouTube processes them (usually 2–3 days)." };
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
  return { ok: false, message: reasons[params.get("reason") ?? ""] ?? "Analytics access was not connected. Try again." };
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
