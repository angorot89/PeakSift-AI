// Pure workspace rules (no React, no fetch): from a project's real state to the one next step a
// creator should take, the continue-working cards on Home, and where the project is in the
// workflow. Facts come from GET /projects/{id}/summary; nothing here invents state.

export type SourceSummary = { id: string; filename: string; status: string; duration_seconds: number | null };
export type CandidateSummary = {
  id: string;
  rank: number;
  title: string;
  start_time: number;
  end_time: number;
  duration_seconds: number;
  category: string;
  overall_score: number;
};
export type ShortSummary = {
  edit_id: string;
  clip_id: string;
  clip_title: string;
  status: string;
  layout: string;
  captions_enabled: boolean;
  caption_style: string | null;
  duration_seconds: number | null;
  created_at: string;
  updated_at: string;
};
export type ProjectSummary = {
  id: string;
  name: string;
  created_at: string;
  last_activity_at: string;
  source: SourceSummary | null;
  transcript: { status: string; progress_percent: number } | null;
  detection: {
    run_id: string;
    status: string;
    candidates: number;
    undecided: number;
    saved: number;
    dismissed: number;
    top: CandidateSummary[];
  } | null;
  clips: { total: number; ready: number; working: number; failed: number; latest_ready_id: string | null };
  shorts: { total: number; ready: number; working: number; failed: number; recent: ShortSummary[] };
  plans: { ready: number; latest_ready: { plan_id: string; clip_id: string; recipe: string } | null };
  published: { uploads: number; working: number; failed: number; with_analytics: number; last_synced_at: string | null };
};
export type HomeShort = ShortSummary & { project_id: string; project_name: string };
export type Home = { projects: ProjectSummary[]; project_count: number; recent_shorts: HomeShort[] };

export type ActionTone = "attention" | "action" | "waiting" | "done";
export type NextAction = {
  /** A stable identifier (tests, analytics of the UI itself — never shown). */
  key: string;
  title: string;
  description: string;
  /** The button label; absent while PeakSift is working and nothing is needed. */
  cta?: string;
  href: string;
  tone: ActionTone;
};

const WORKING = new Set([
  "queued", "uploaded", "processing_metadata", "extracting_audio", "transcribing",
  "preparing_transcript", "analyzing", "validating", "ranking", "rendering",
]);
const working = (status: string | undefined) => !!status && WORKING.has(status);

const base = (p: ProjectSummary) => `/projects/${p.id}`;
export const editorLink = (projectId: string, clipId: string, editId?: string) =>
  `/projects/${projectId}/clips/${clipId}${editId ? `?edit=${editId}` : ""}`;
export const autoEditLink = (projectId: string, clipId: string) => `/projects/${projectId}/clips/${clipId}/auto-edit`;
export const createLink = (projectId: string, clipId: string) => `/projects/${projectId}/clips/${clipId}/create`;

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The single most useful next step for a project, from its real state. */
export function nextAction(p: ProjectSummary): NextAction {
  const source = p.source;
  if (!source) {
    return { key: "upload", title: "Add your long video", description: "Upload a recording, stream, podcast or interview to start.", cta: "Upload a video", href: `${base(p)}/source`, tone: "action" };
  }
  if (source.status === "failed") {
    return { key: "source-failed", title: "This file couldn't be read as a video", description: "Upload a different export (MP4, MOV or WebM).", cta: "Upload a different file", href: `${base(p)}/source`, tone: "attention" };
  }
  if (source.status !== "ready") {
    return { key: "source-working", title: "Preparing your video", description: "Reading the file. This usually takes a moment.", href: `${base(p)}/source`, tone: "waiting" };
  }
  const t = p.transcript;
  if (!t) {
    return { key: "transcribe", title: "Transcribe your video", description: "PeakSift needs the words to find the best moments.", cta: "Start transcription", href: `${base(p)}/source`, tone: "action" };
  }
  if (t.status === "failed") {
    return { key: "transcript-failed", title: "Transcription needs attention", description: "It stopped before finishing. You can try again.", cta: "Review and retry", href: `${base(p)}/source`, tone: "attention" };
  }
  if (t.status !== "completed") {
    return { key: "transcribing", title: "Transcribing your video", description: "You can leave this page; it keeps going.", href: `${base(p)}/source`, tone: "waiting" };
  }
  // A plan or a short waiting for the creator comes before finding more moments. A draft is the
  // next step only until the project has a Short: drafts used through the editor stay "ready".
  const plan = p.plans.latest_ready;
  if (plan && p.shorts.total === 0) {
    return { key: "plan-ready", title: "Your Auto Edit draft is ready", description: "See what PeakSift chose, then use it or adjust it.", cta: "Review the draft", href: autoEditLink(p.id, plan.clip_id), tone: "action" };
  }
  const recent = p.shorts.recent;
  const rendering = recent.find((s) => working(s.status));
  const readyShort = recent.find((s) => s.status === "ready");
  const failedShort = recent[0]?.status === "failed" ? recent[0] : undefined;
  if (failedShort) {
    return { key: "short-failed", title: "A Short needs attention", description: `“${failedShort.clip_title}” didn't finish rendering.`, cta: "Open the editor", href: editorLink(p.id, failedShort.clip_id), tone: "attention" };
  }
  if (rendering) {
    return { key: "rendering", title: "Rendering your Short", description: `“${rendering.clip_title}” will be ready soon.`, href: editorLink(p.id, rendering.clip_id), tone: "waiting" };
  }
  const published = p.published.uploads > 0 || p.published.with_analytics > 0;
  if (readyShort && !published && p.published.working === 0 && p.published.failed > 0) {
    return { key: "upload-failed", title: "A YouTube upload needs attention", description: "Open the Short to see what happened and try again.", cta: "Open the Short", href: editorLink(p.id, readyShort.clip_id, readyShort.edit_id), tone: "attention" };
  }
  if (p.published.working > 0) {
    return { key: "uploading", title: "Uploading to YouTube", description: "You can leave this page; it keeps going.", href: readyShort ? editorLink(p.id, readyShort.clip_id, readyShort.edit_id) : `${base(p)}/clips`, tone: "waiting" };
  }
  if (readyShort && !published) {
    return { key: "short-ready", title: "Your Short is ready", description: "Publish it to YouTube or download it.", cta: "Publish or download", href: editorLink(p.id, readyShort.clip_id, readyShort.edit_id), tone: "action" };
  }
  if (published) {
    return {
      key: "published",
      title: p.published.with_analytics ? "See how your Shorts are doing" : "Your Short is on YouTube",
      description: p.published.with_analytics ? "Views, engagement and what seems to be working." : "Figures appear once YouTube has processed them (2–3 days).",
      cta: "View performance",
      href: `${base(p)}/analytics`,
      tone: "done",
    };
  }
  if (p.clips.latest_ready_id) {
    return { key: "create-short", title: "Make your clip a Short", description: "Auto Edit prepares framing, captions, visuals and sound; you can change everything.", cta: "Create Short", href: createLink(p.id, p.clips.latest_ready_id), tone: "action" };
  }
  if (p.clips.working > 0) {
    return { key: "clip-working", title: "Preparing your clip", description: "Cutting the moment from your video.", href: `${base(p)}/clips`, tone: "waiting" };
  }
  const d = p.detection;
  if (!d) {
    return { key: "find-clips", title: "Find the best moments", description: "PeakSift reads the transcript and ranks moments worth clipping.", cta: "Find clips", href: `${base(p)}/clips`, tone: "action" };
  }
  if (d.status === "failed") {
    return { key: "detection-failed", title: "Finding clips needs attention", description: "It stopped before finishing. You can try again.", cta: "Review and retry", href: `${base(p)}/clips`, tone: "attention" };
  }
  if (d.status !== "completed") {
    return { key: "finding", title: "Finding the best moments", description: "Reading the transcript and ranking moments.", href: `${base(p)}/clips`, tone: "waiting" };
  }
  if (d.candidates === 0) {
    return { key: "no-moments", title: "No moments stood out", description: "Try again, or with another model if one is available.", cta: "Try again", href: `${base(p)}/clips`, tone: "attention" };
  }
  return {
    key: "review-clips",
    title: d.undecided > 0 ? `${plural(d.undecided, "clip")} ready to review` : "Pick a clip to make into a Short",
    description: "Preview the moments PeakSift found and choose one.",
    cta: "Review clips",
    href: `${base(p)}/clips`,
    tone: "action",
  };
}

/** Where the project is: Source → Clips → Edit → Publish → Learn (the furthest stage reached). */
export const STAGES = ["Source", "Clips", "Edit", "Publish", "Learn"] as const;
export function projectStage(p: ProjectSummary): number {
  if (p.published.with_analytics > 0) return 4;
  if (p.published.uploads > 0) return 3;
  if (p.shorts.total > 0 || p.clips.total > 0) return 2;
  if (p.detection || p.transcript?.status === "completed") return 1;
  return 0;
}

const PRIORITY: Record<ActionTone, number> = { attention: 0, action: 1, waiting: 2, done: 3 };

/** Home's continue cards: each project's next step, problems first, then the most recent. */
export function continueItems(home: Home, limit = 4): (NextAction & { projectId: string; projectName: string })[] {
  return home.projects
    .map((p) => ({ ...nextAction(p), projectId: p.id, projectName: p.name, at: p.last_activity_at }))
    .sort((a, b) => PRIORITY[a.tone] - PRIORITY[b.tone] || b.at.localeCompare(a.at))
    .slice(0, limit)
    .map((item) => ({ key: item.key, title: item.title, description: item.description, cta: item.cta, href: item.href, tone: item.tone, projectId: item.projectId, projectName: item.projectName }));
}

/** "just now", "5 min ago", "3 h ago", "yesterday", "4 days ago", then the date. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  const days = Math.floor(seconds / 86400);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return new Date(iso).toLocaleDateString("en", { month: "short", day: "numeric" });
}

/**
 * A creator-friendly word for a moment's place in the ranking, grounded in the run's own rank
 * and its 0–100 editorial score (never a prediction of views).
 */
export function momentLabel(rank: number, score: number): "Top pick" | "Strong moment" | "Worth reviewing" {
  if (rank === 1) return "Top pick";
  if (score >= 75) return "Strong moment";
  return "Worth reviewing";
}

/** 112 → "1:52"; 3725 → "1:02:05". */
export function clock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

const LAYOUTS: Record<string, string> = {
  smart_reframe: "Smart reframe", center_crop: "Center crop", blur_background: "Blur background",
  fit: "Fit", manual_crop: "Focal point",
};

/** What tells two versions of one clip apart: "Blur background · Minimal captions". */
export function shortLabel(short: Pick<ShortSummary, "layout" | "captions_enabled" | "caption_style">): string {
  const layout = LAYOUTS[short.layout] ?? "Vertical";
  if (!short.captions_enabled) return `${layout} · No captions`;
  const style = short.caption_style ? short.caption_style.charAt(0).toUpperCase() + short.caption_style.slice(1) : "";
  return `${layout} · ${style ? `${style} captions` : "Captions"}`;
}

export type StartStep = { key: "upload" | "moments" | "short"; title: string; done: boolean };

/** The first-run checklist on Home, from real progress only; complete once a Short is ready. */
export function gettingStarted(home: Home): { steps: StartStep[]; complete: boolean } {
  const short = home.recent_shorts.length > 0 || home.projects.some((p) => p.shorts.ready > 0);
  const moments = short || home.projects.some((p) => p.detection?.status === "completed" && p.detection.candidates > 0);
  const upload = moments || home.projects.some((p) => p.source !== null);
  const steps: StartStep[] = [
    { key: "upload", title: "Upload a long video", done: upload },
    { key: "moments", title: "Let PeakSift find the best moments", done: moments },
    { key: "short", title: "Create your first Short", done: short },
  ];
  return { steps, complete: short };
}
