// Ask PeakSift: what the current page is about, what to suggest asking, and how answers read.
// Pure functions (unit-tested); the API calls live in copilot.ts.

export type CopilotPage =
  | "home" | "projects" | "new_project" | "overview" | "source" | "moments" | "create"
  | "auto_edit" | "editor" | "assets" | "project_analytics" | "analytics" | "short_analytics"
  | "settings";

export type CopilotScope = {
  page: CopilotPage;
  projectId: string | null;
  clipId: string | null;
  editId: string | null;
};

const ID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const PROJECT = new RegExp(`^/projects/(${ID})(?:/(source|clips|assets|analytics))?/?$`);
const CLIP = new RegExp(`^/projects/(${ID})/clips/(${ID})(?:/(create|auto-edit))?/?$`);
const SHORT_ANALYTICS = new RegExp(`^/analytics/(${ID})/?$`);
const EDIT = new RegExp(`(?:^|[?&])edit=(${ID})(?:&|$)`);

/** Where the creator is, from the address (and its query, for the editor's version). */
export function copilotScope(pathname: string, search = ""): CopilotScope {
  const none = { projectId: null, clipId: null, editId: null };
  const clip = CLIP.exec(pathname);
  if (clip) {
    const page = clip[3] === "create" ? "create" : clip[3] === "auto-edit" ? "auto_edit" : "editor";
    const edit = page === "editor" ? EDIT.exec(search) : null;
    return { page, projectId: clip[1], clipId: clip[2], editId: edit ? edit[1] : null };
  }
  const project = PROJECT.exec(pathname);
  if (project) {
    const section = project[2] as "source" | "clips" | "assets" | "analytics" | undefined;
    const page: CopilotPage = !section ? "overview" : section === "clips" ? "moments"
      : section === "analytics" ? "project_analytics" : section;
    return { ...none, page, projectId: project[1] };
  }
  if (SHORT_ANALYTICS.test(pathname)) return { ...none, page: "short_analytics" };
  if (pathname.startsWith("/analytics")) return { ...none, page: "analytics" };
  if (pathname === "/projects/new") return { ...none, page: "new_project" };
  if (pathname.startsWith("/projects")) return { ...none, page: "projects" };
  if (pathname.startsWith("/settings")) return { ...none, page: "settings" };
  return { ...none, page: "home" };
}

/** The conversation a page belongs to: one per project, one for the workspace. */
export function threadKey(scope: CopilotScope): string {
  return scope.projectId ?? "workspace";
}

const STARTERS: Record<CopilotPage, string[]> = {
  home: ["What should I work on next?", "What has worked best for my recent Shorts?"],
  projects: ["Which project should I finish first?", "What should I work on next?"],
  new_project: ["What kind of video works best to start with?"],
  overview: ["What should I do next?", "Give me 3 Short ideas from this video"],
  source: ["Give me 3 Short ideas from this video", "What is this video about?"],
  moments: ["Which moment should I start with?", "Why is this the top pick?"],
  create: ["Should I use Auto Edit or edit by hand?", "Which style fits this clip?"],
  auto_edit: ["Should I use Punchy or Story here?", "Why didn't Auto Edit add B-roll?"],
  editor: ["How can I improve this edit?", "Do I have useful B-roll for this clip?"],
  assets: ["Do I have a visual of a bridge?", "Which visuals am I not using?"],
  project_analytics: ["How are this project's Shorts doing?", "Do I have enough data yet?"],
  analytics: ["What seems to be working?", "Do I have enough data yet?"],
  short_analytics: ["How is this Short doing?", "Do I have enough data yet?"],
  settings: ["What does PeakSift do with my YouTube connection?"],
};

const PROJECT_PAGES: CopilotPage[] = ["overview", "source", "moments", "assets", "project_analytics"];
const NO_SOURCE = ["What should I do next?", "What kind of video works best to start with?"];

/** The suggested questions for a page — about getting started while a project has no video. */
export function starters(page: CopilotPage, hasSource: boolean | null = null): string[] {
  return hasSource === false && PROJECT_PAGES.includes(page) ? NO_SOURCE : STARTERS[page];
}

/** The waiting line: the context first, then the local model. */
export function waitingText(elapsedMs: number): string {
  return elapsedMs < 1200 ? "Looking at this project…" : "Thinking…";
}

export const QUESTION_MAX = 1000;

/** Characters as the server counts them (code points: an emoji is one, not two). */
export function charCount(text: string): number {
  return [...text].length;
}

/** What to tell the creator about the length of their question, if anything. */
export function lengthNote(text: string): string | null {
  const left = QUESTION_MAX - charCount(text);
  if (left < 0) return `${-left} characters too long`;
  if (left <= 100) return `${left} characters left`;
  return null;
}
