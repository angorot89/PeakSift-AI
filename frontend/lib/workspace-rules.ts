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
  /** YouTube confirmed the upload; never an upload still in flight. */
  published: boolean;
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
  /** The next best step, decided by the server (one rule set for Home, the Overview and the Copilot). */
  next_action: NextAction;
};
export type HomeShort = ShortSummary & { project_id: string; project_name: string };
export type ContinueItem = NextAction & { project_id: string; project_name: string };
export type Home = {
  projects: ProjectSummary[];
  project_count: number;
  recent_shorts: HomeShort[];
  /** Home's *Continue working*: each project's next step, problems first (server order). */
  continue_items: ContinueItem[];
};

export type ActionTone = "attention" | "action" | "waiting" | "done";
export type NextAction = {
  /** A stable identifier (tests, analytics of the UI itself — never shown). */
  key: string;
  title: string;
  description: string;
  /** The button label; null while PeakSift is working and nothing is needed. */
  cta: string | null;
  href: string;
  tone: ActionTone;
};

export const editorLink = (projectId: string, clipId: string, editId?: string) =>
  `/projects/${projectId}/clips/${clipId}${editId ? `?edit=${editId}` : ""}`;

/** Where the project is: Source → Clips → Edit → Publish → Learn (the furthest stage reached). */
export const STAGES = ["Source", "Clips", "Edit", "Publish", "Learn"] as const;
export function projectStage(p: ProjectSummary): number {
  if (p.published.with_analytics > 0) return 4;
  if (p.published.uploads > 0) return 3;
  if (p.shorts.total > 0 || p.clips.total > 0) return 2;
  if (p.detection || p.transcript?.status === "completed") return 1;
  return 0;
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

/** "amine.k@example.com" → "Amine.k": a friendly name from the sign-in email (no profile names yet). */
export function displayName(email: string): string {
  const local = email.split("@")[0] ?? "";
  return local ? local.charAt(0).toUpperCase() + local.slice(1) : "";
}

const MOMENT_STEPS = new Set(["review-clips", "create-short", "clip-working", "find-clips"]);
const SHORT_STEPS = new Set(["plan-ready", "short-failed", "rendering", "upload-failed", "uploading", "short-ready", "published"]);

export type ContinueVisual =
  | { kind: "moments"; moments: CandidateSummary[]; count: number }
  | { kind: "short"; short: ShortSummary }
  | { kind: "source" }
  | { kind: "none" };

/** What a Home "Continue working" card shows for a next step, from the project's real data:
 * the moments waiting, the Short in question, or the source video. */
export function continueVisual(key: string, project: ProjectSummary | undefined): ContinueVisual {
  if (!project) return { kind: "none" };
  const top = project.detection?.top ?? [];
  if (MOMENT_STEPS.has(key) && top.length) {
    return { kind: "moments", moments: top.slice(0, 3), count: project.detection?.candidates ?? top.length };
  }
  const short = project.shorts.recent[0];
  if (SHORT_STEPS.has(key) && short) return { kind: "short", short };
  return project.source && project.source.status !== "failed" ? { kind: "source" } : { kind: "none" };
}

export type FlowState = "done" | "current" | "working" | "attention" | "upcoming";
export type FlowStep = {
  key: "upload" | "transcribe" | "moments" | "short" | "publish";
  title: string;
  /** One short line under the title, from the project's real state. */
  detail: string;
  state: FlowState;
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/**
 * The project's workflow in creator words — Upload → Transcribe → Find moments → Create Short →
 * Edit & publish — each step's state read from the real summary (never guessed).
 */
export function workflowSteps(p: ProjectSummary): FlowStep[] {
  const source = p.source;
  const sourceReady = source?.status === "ready";
  const upload: FlowStep = !source
    ? { key: "upload", title: "Upload", detail: "Add a long video", state: "current" }
    : source.status === "failed"
      ? { key: "upload", title: "Upload", detail: "Try another file", state: "attention" }
      : sourceReady
        ? { key: "upload", title: "Upload", detail: "Video added", state: "done" }
        : { key: "upload", title: "Upload", detail: "Preparing the video…", state: "working" };

  const t = p.transcript?.status;
  const transcribe: FlowStep =
    t === "completed"
      ? { key: "transcribe", title: "Transcribe", detail: "Transcript ready", state: "done" }
      : t === "failed"
        ? { key: "transcribe", title: "Transcribe", detail: "Needs another try", state: "attention" }
        : t
          ? { key: "transcribe", title: "Transcribe", detail: "Transcribing…", state: "working" }
          : { key: "transcribe", title: "Transcribe", detail: "Get the words", state: sourceReady ? "current" : "upcoming" };

  const d = p.detection;
  const moments: FlowStep =
    d?.status === "completed"
      ? d.candidates > 0
        ? { key: "moments", title: "Find moments", detail: plural(d.candidates, "moment"), state: "done" }
        : { key: "moments", title: "Find moments", detail: "None stood out", state: "attention" }
      : d?.status === "failed"
        ? { key: "moments", title: "Find moments", detail: "Needs another try", state: "attention" }
        : d
          ? { key: "moments", title: "Find moments", detail: "Finding moments…", state: "working" }
          : { key: "moments", title: "Find moments", detail: "Best moments, ranked", state: t === "completed" ? "current" : "upcoming" };

  const s = p.shorts;
  const short: FlowStep =
    s.ready > 0
      ? { key: "short", title: "Create Short", detail: `${plural(s.ready, "Short")} ready`, state: "done" }
      : s.working > 0 || p.clips.working > 0
        ? { key: "short", title: "Create Short", detail: "Rendering…", state: "working" }
        : s.failed > 0
          ? { key: "short", title: "Create Short", detail: "A render needs attention", state: "attention" }
          : { key: "short", title: "Create Short", detail: "Pick a moment", state: moments.state === "done" ? "current" : "upcoming" };

  const u = p.published;
  const publish: FlowStep =
    u.uploads > 0
      ? { key: "publish", title: "Edit & publish", detail: "On YouTube", state: "done" }
      : u.working > 0
        ? { key: "publish", title: "Edit & publish", detail: "Uploading…", state: "working" }
        : u.failed > 0
          ? { key: "publish", title: "Edit & publish", detail: "An upload needs attention", state: "attention" }
          : { key: "publish", title: "Edit & publish", detail: "Polish, publish or download", state: s.ready > 0 ? "current" : "upcoming" };

  return [upload, transcribe, moments, short, publish];
}
