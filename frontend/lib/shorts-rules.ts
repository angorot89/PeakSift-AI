// The Shorts library's rules in one place (no React, no fetch; unit-tested with node --test):
// what each status is called, how it filters, sorts and searches, which actions are valid, and
// where they go. The server derives each Short's status (services/shorts_library.py); this file
// only puts it into the creator's words.

import type { PublishJob, PublishPanel } from "./publishing-rules.ts";
import type { StatusTone } from "./status.ts";

export type ShortStatus =
  | "draft"
  | "rendering"
  | "ready"
  | "publishing"
  | "on_youtube"
  | "published"
  | "failed"
  | "needs_attention";

export type PublishState =
  | "not_published"
  | "preparing"
  | "uploading"
  | "processing"
  | "on_youtube"
  | "published"
  | "stalled"
  | "failed";

export type ShortReason = "render_failed" | "render_stalled" | "clip_failed" | "clip_stalled" | "publish_failed" | "publish_stalled";

export type ShortItem = {
  id: string;
  kind: "short" | "draft";
  status: ShortStatus;
  reason: ShortReason | null;
  title: string;
  edit_id: string | null;
  clip_id: string;
  project: { id: string; name: string };
  source: { id: string; filename: string };
  duration_seconds: number | null;
  /** What can be previewed: the rendered Short, the moment's cut, or nothing yet. */
  preview: "short" | "clip" | null;
  version: { number: number; count: number } | null;
  /** The template version and brand this Short was made with (recorded with it). */
  template: { id: string | null; name: string; version: number | null } | null;
  brand: { name: string } | null;
  /** V1.8: the local market it was made for, as recorded (absent or null for Global). */
  market?: { code: string; name: string } | null;
  auto_edit: boolean;
  /** A draft whose Auto Edit is prepared and waiting for review. */
  plan_ready: boolean;
  publish: {
    state: PublishState;
    platform: string | null;
    published_at: string | null;
    uploaded_at: string | null;
    privacy: string | null;
    simulated: boolean;
    video_url: string | null;
    job_id: string | null;
  };
  /** Latest reported figures; null fields are "not reported", never 0. */
  performance: {
    content_id: string;
    views: number | null;
    likes: number | null;
    comments: number | null;
    observed_at: string | null;
    simulated: boolean;
    analytics_through: string | null;
  } | null;
  created_at: string;
  updated_at: string;
  rendered_at: string | null;
};

export type ShortDetail = ShortItem & {
  moment: { start_time: number; end_time: number; rank: number; category: string };
  versions: { id: string; number: number; status: ShortStatus; created_at: string }[];
  render: { error_message: string | null; file_size: number | null; progress_percent: number };
  auto_edit_plan_id: string | null;
  /** Whether performance can be shown for this creator (and whether it is simulated). */
  analytics: ShortAnalyticsAccess;
};

export type ShortsLibrary = { shorts: ShortItem[]; truncated: boolean };

// --- status words -----------------------------------------------------------------------------

export type FilterKey = "all" | "drafts" | "ready" | "published" | "attention";

const STATUS: Record<ShortStatus, { label: string; tone: StatusTone; filter: FilterKey | null }> = {
  draft: { label: "Draft", tone: "info", filter: "drafts" },
  rendering: { label: "Rendering", tone: "processing", filter: null },
  ready: { label: "Ready", tone: "accent", filter: "ready" },
  publishing: { label: "Publishing", tone: "processing", filter: null },
  on_youtube: { label: "On YouTube", tone: "success", filter: "published" },
  published: { label: "Published", tone: "success", filter: "published" },
  failed: { label: "Failed", tone: "danger", filter: "attention" },
  needs_attention: { label: "Needs attention", tone: "warning", filter: "attention" },
};

export function statusLabel(status: ShortStatus): { label: string; tone: StatusTone } {
  const { label, tone } = STATUS[status] ?? { label: "Needs attention", tone: "warning" as const };
  return { label, tone };
}

/** One sentence on what is happening or what went wrong, in the creator's words. */
export function statusDetail(item: Pick<ShortItem, "status" | "reason" | "publish" | "plan_ready" | "kind">): string {
  switch (item.reason) {
    case "render_failed":
      return "This version couldn't be rendered. Open it in the editor to try again.";
    case "render_stalled":
      return "Rendering stopped responding. Open it in the editor to render it again.";
    case "clip_failed":
      return "The moment couldn't be cut from your video. Try again from the project's moments.";
    case "clip_stalled":
      return "Cutting the moment stopped responding. Try again from the project's moments.";
    case "publish_failed":
      return "The YouTube upload didn't finish. Review it and try again.";
    case "publish_stalled":
      return "The YouTube upload stopped responding. You can resume it.";
  }
  switch (item.status) {
    case "draft":
      return item.plan_ready ? "Auto Edit is ready for you to review." : "Not edited yet.";
    case "rendering":
      return item.kind === "draft" ? "Cutting the moment from your video…" : "Rendering your Short…";
    case "ready":
      return "Rendered and ready to publish or download.";
    case "publishing":
      return publishStage(item.publish.state);
    case "on_youtube":
      return "Uploaded to YouTube. PeakSift can't see when YouTube finishes processing it.";
    case "published":
      return "Published on YouTube.";
    default:
      return "";
  }
}

/** Real stages only — no invented percentages. */
export function publishStage(state: PublishState): string {
  switch (state) {
    case "preparing":
      return "Preparing upload…";
    case "uploading":
      return "Uploading…";
    case "processing":
      return "Processing on YouTube…";
    case "on_youtube":
      return "On YouTube";
    case "published":
      return "Published";
    case "stalled":
      return "Upload stalled";
    case "failed":
      return "Upload didn't finish";
    default:
      return "Not published";
  }
}

const shortDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const longDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });

/** "Oct 18" this year, "Oct 18, 2025" otherwise. */
export function dayLabel(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  return (date.getFullYear() === now.getFullYear() ? shortDate : longDate).format(date);
}

/** The card's last line: where it went and when, or what is happening. */
export function contextLine(item: ShortItem, now: Date = new Date()): string {
  const publish = item.publish;
  if (item.status === "published" && publish.published_at) {
    return `YouTube · Published ${dayLabel(publish.published_at, now)}${publish.simulated ? " (simulated)" : ""}`;
  }
  if (item.status === "on_youtube") {
    return `YouTube · Uploaded${publish.uploaded_at ? ` ${dayLabel(publish.uploaded_at, now)}` : ""}${publish.simulated ? " (simulated)" : ""}`;
  }
  if (item.status === "publishing") return `YouTube · ${publishStage(publish.state)}`;
  if (item.status === "draft") return item.plan_ready ? "Auto Edit ready to review" : `Started ${dayLabel(item.created_at, now)}`;
  if (item.status === "rendering") return statusDetail(item);
  return `Updated ${dayLabel(item.updated_at, now)}`;
}

// --- filters, search and sort -----------------------------------------------------------------

export const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "drafts", label: "Drafts" },
  { key: "ready", label: "Ready" },
  { key: "published", label: "Published" },
  { key: "attention", label: "Needs attention" },
];

export function matchesFilter(item: ShortItem, filter: FilterKey): boolean {
  return filter === "all" || STATUS[item.status]?.filter === filter;
}

export function filterCounts(items: ShortItem[]): Record<FilterKey, number> {
  const counts: Record<FilterKey, number> = { all: items.length, drafts: 0, ready: 0, published: 0, attention: 0 };
  for (const item of items) {
    const key = STATUS[item.status]?.filter;
    if (key) counts[key] += 1;
  }
  return counts;
}

const fold = (text: string) => text.normalize("NFKD").replace(/\p{M}/gu, "").toLocaleLowerCase();

/** Every word of the query appears in the title, the project or the source file's name. */
export function matchesSearch(item: ShortItem, query: string): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const haystack = fold(`${item.title} ${item.project.name} ${item.source.filename}`);
  return words.every((word) => haystack.includes(word));
}

export type SortKey = "updated" | "newest" | "oldest" | "published";

export const SORTS: { key: SortKey; label: string }[] = [
  { key: "updated", label: "Recently updated" },
  { key: "newest", label: "Newest" },
  { key: "oldest", label: "Oldest" },
  { key: "published", label: "Recently published" },
];

const time = (iso: string | null) => (iso ? Date.parse(iso) : Number.NEGATIVE_INFINITY);
const onYouTubeAt = (item: ShortItem) => time(item.publish.published_at ?? item.publish.uploaded_at);

export function sortShorts(items: ShortItem[], sort: SortKey): ShortItem[] {
  const by: Record<SortKey, (a: ShortItem, b: ShortItem) => number> = {
    updated: (a, b) => time(b.updated_at) - time(a.updated_at),
    newest: (a, b) => time(b.created_at) - time(a.created_at),
    oldest: (a, b) => time(a.created_at) - time(b.created_at),
    // Published first, most recent first; the rest keep their most recent activity order.
    published: (a, b) => onYouTubeAt(b) - onYouTubeAt(a) || time(b.updated_at) - time(a.updated_at),
  };
  return [...items].sort((a, b) => by[sort](a, b) || a.id.localeCompare(b.id));
}

export function visibleShorts(items: ShortItem[], filter: FilterKey, query: string, sort: SortKey): ShortItem[] {
  return sortShorts(items.filter((item) => matchesFilter(item, filter) && matchesSearch(item, query)), sort);
}

// --- where things go --------------------------------------------------------------------------

export const shortHref = (id: string) => `/shorts/${id}`;
export const editorHref = (item: Pick<ShortItem, "project" | "clip_id" | "edit_id">) =>
  `/projects/${item.project.id}/clips/${item.clip_id}${item.edit_id ? `?edit=${item.edit_id}` : ""}`;
export const createHref = (item: Pick<ShortItem, "project" | "clip_id">) => `/projects/${item.project.id}/clips/${item.clip_id}/create`;
export const autoEditHref = (item: Pick<ShortItem, "project" | "clip_id">) => `/projects/${item.project.id}/clips/${item.clip_id}/auto-edit`;
export const momentsHref = (item: Pick<ShortItem, "project">) => `/projects/${item.project.id}/clips`;
export const analyticsHref = (contentId: string) => `/analytics/${contentId}`;

/** Where "continue editing" goes: the waiting Auto Edit, the guided creation, or the editor. */
export function continueHref(item: ShortItem): string {
  if (item.kind === "draft") return item.plan_ready ? autoEditHref(item) : createHref(item);
  return editorHref(item);
}

export type ShortAction = "continue" | "publish" | "performance" | "fix_render" | "fix_publish" | "retry_cut" | "edit" | "download" | "analytics" | "project";

/** The one primary action for a state (null while there is nothing to do but wait). */
export function primaryAction(item: ShortItem): { action: ShortAction; label: string } | null {
  switch (item.status) {
    case "draft":
      return { action: "continue", label: "Continue editing" };
    case "ready":
      return { action: "publish", label: "Publish" };
    case "published":
    case "on_youtube":
      return { action: "performance", label: "View performance" };
    case "failed":
    case "needs_attention":
      if (item.reason === "publish_failed" || item.reason === "publish_stalled") return { action: "fix_publish", label: "Fix issue" };
      if (item.reason === "clip_failed" || item.reason === "clip_stalled") return { action: "retry_cut", label: "Fix issue" };
      return { action: "fix_render", label: "Fix issue" };
    default:
      return null;
  }
}

/** The overflow menu: only actions valid now (no disabled entries). */
export function menuActions(item: ShortItem): { action: ShortAction; label: string }[] {
  const actions: { action: ShortAction; label: string }[] = [];
  if (item.kind === "short") actions.push({ action: "edit", label: "Edit" });
  else if (item.status === "draft") actions.push({ action: "continue", label: "Continue editing" });
  if (item.kind === "short" && item.preview === "short") actions.push({ action: "download", label: "Download" });
  if (item.status === "ready") actions.push({ action: "publish", label: "Publish" });
  if (item.performance) actions.push({ action: "analytics", label: "View analytics" });
  actions.push({ action: "project", label: "Open project" });
  return actions;
}

/** "Short: Lava jump — Published, 0:42, from Speedrun Fails": a card's accessible name. */
export function cardLabel(item: ShortItem): string {
  const parts = [`${item.title}`, statusLabel(item.status).label];
  if (item.duration_seconds) parts.push(clock(item.duration_seconds));
  return `${parts.join(", ")}, from ${item.project.name}`;
}

/** "0:42" / "1:05:09". */
export function clock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

// --- the Short's publishing panel -------------------------------------------------------------

export type PublishingView = {
  state: PublishState;
  pill: { label: string; tone: StatusTone };
  /** The connection, in words. */
  connection: string;
  stage: string;
  /** The one action that fits now (nothing while an upload runs or once YouTube has it). */
  action: "connect" | "publish" | "publish_again" | null;
  reconnect: boolean;
  showMetadata: boolean;
  publishedOn: "published" | "uploaded" | null;
  date: string | null;
};

/** A publish attempt's state in the library's terms (same rules as the server's). */
export function jobState(job: PublishJob): PublishState {
  switch (job.status) {
    case "published":
      return "published";
    case "uploaded":
    case "processing":
      return job.awaiting_processing ? "processing" : "on_youtube";
    case "failed":
    case "provider_failed":
      return "failed";
    case "uploading":
      return job.is_stale ? "stalled" : "uploading";
    default:
      return job.is_stale ? "stalled" : "preparing";
  }
}

const PILLS: Record<PublishState, { label: string; tone: StatusTone }> = {
  not_published: { label: "Not published", tone: "neutral" },
  preparing: { label: "Publishing", tone: "processing" },
  uploading: { label: "Publishing", tone: "processing" },
  processing: { label: "Publishing", tone: "processing" },
  on_youtube: { label: "On YouTube", tone: "success" },
  published: { label: "Published", tone: "success" },
  stalled: { label: "Stalled", tone: "warning" },
  failed: { label: "Failed", tone: "danger" },
};

const HELD: PublishState[] = ["published", "on_youtube", "processing"];

/**
 * What the publishing panel shows. `job` is the newest attempt (it updates live); once YouTube
 * has the video from an earlier attempt, that outranks it — exactly like the library's status.
 */
export function publishingView(short: Pick<ShortItem, "publish">, panel: PublishPanel, job: PublishJob | null): PublishingView {
  const held = HELD.includes(short.publish.state) && (!job || job.id !== short.publish.job_id);
  const state = held || !job ? short.publish.state : jobState(job);
  const connection = panel.connection;
  const connected = connection?.status === "connected";
  const connectionText = !panel.enabled
    ? "Publishing isn't enabled on this server"
    : !connection
      ? "Not connected"
      : connected
        ? connection.account_title
          ? `Connected · ${connection.account_title}`
          : "Connected"
        : "Needs reconnecting";
  let action: PublishingView["action"] = null;
  const settled = state === "not_published" || state === "failed";
  if (panel.enabled && settled) {
    if (!connected) action = "connect";
    else if (state === "not_published" && panel.edit_ready) action = "publish";
    else if (state === "failed" && job && !job.retryable) action = "publish_again";
  }
  const publishedOn = state === "published" ? "published" : state === "on_youtube" ? "uploaded" : null;
  const date =
    state === "published"
      ? (job?.status === "published" ? job.published_at : null) ?? short.publish.published_at
      : state === "on_youtube"
        ? (job && jobState(job) === "on_youtube" ? job.completed_at : null) ?? short.publish.uploaded_at
        : null;
  return {
    state,
    pill: PILLS[state],
    connection: connectionText,
    stage: publishStage(state),
    action,
    reconnect: Boolean(connection && !connected),
    showMetadata: Boolean(job) && state !== "not_published",
    publishedOn,
    date,
  };
}

// --- the Short's performance ------------------------------------------------------------------

export type ShortAnalyticsAccess = {
  enabled: boolean;
  connected: boolean;
  connection_status: string | null;
  analytics_access: boolean;
  simulated: boolean;
};

type Daily = { date: string; watch_time_seconds: number | null; subscribers_gained: number | null };
type Detail = { processed_through: string | null; counters_observed_at: string | null; daily: Daily[] };

function reportingDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** Whether new figures can arrive (otherwise the panel offers to connect analytics). */
export const analyticsReady = (access: ShortAnalyticsAccess | null) =>
  Boolean(access?.enabled && access.connected && access.analytics_access && access.connection_status === "connected");

/** How fresh the figures are, or why there are none — always one plain line. */
export function performanceFreshness(access: ShortAnalyticsAccess | null, detail: Detail | null): string {
  const kept = detail?.processed_through ? ` Showing what was collected through ${reportingDay(detail.processed_through)}.` : "";
  if (!access || !access.enabled) return `Analytics isn't available on this server.${kept}`;
  if (!access.connected || !access.analytics_access) {
    return `Analytics not connected.${kept || " Connect read-only analytics in Settings to see how this Short is doing."}`;
  }
  if (access.connection_status !== "connected") return `Analytics paused: reconnect YouTube in Settings to update it.${kept}`;
  if (detail?.processed_through) return `Updated through ${reportingDay(detail.processed_through)} (YouTube's processed days; recent days may still change).`;
  return "Waiting for YouTube data. Processed figures usually arrive 2–3 days after publishing.";
}

/** "1 h 12 min" / "35 min" / "48 s". */
export function watchTime(seconds: number): string {
  const total = Math.round(seconds);
  if (total < 60) return `${total} s`;
  const h = Math.floor(total / 3600);
  const m = Math.round((total % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

/** Totals over the days YouTube reported ("—" when no day reported the figure) and the first
 * seven reporting days, for the chart. */
export function performanceTotals(detail: Detail): { watchTime: string; subscribers: string; firstWeek: Set<string> } {
  let time: number | null = null;
  let subscribers: number | null = null;
  for (const day of detail.daily) {
    if (day.watch_time_seconds !== null) time = (time ?? 0) + day.watch_time_seconds;
    if (day.subscribers_gained !== null) subscribers = (subscribers ?? 0) + day.subscribers_gained;
  }
  const days = [...new Set(detail.daily.map((day) => day.date))].sort().slice(0, 7);
  return {
    watchTime: time === null ? "—" : watchTime(time),
    subscribers: subscribers === null ? "—" : new Intl.NumberFormat("en").format(subscribers),
    firstWeek: new Set(days),
  };
}

type InsightLike = { id: string; statement: string; dismissed: boolean; group: { id: string }[]; comparison: { id: string }[] };

/** Observed patterns whose evidence includes this Short (never dismissed ones, at most two). */
export function relatedInsights<T extends InsightLike>(insights: { insights: T[] }, contentId: string): T[] {
  return insights.insights
    .filter((insight) => !insight.dismissed && insight.group.some((short) => short.id === contentId))
    .slice(0, 2);
}
