// Ask PeakSift: typed calls to /copilot/*. The rules for pages, starters and wording are in
// copilot-rules.ts (unit-tested).
import { apiFetch, postJson } from "@/lib/api";
import type { CopilotScope } from "@/lib/copilot-rules";

export * from "@/lib/copilot-rules";

export type CopilotAction = { index: number; type: string; label: string };
export type CopilotReference = { kind: string; label: string };
export type CopilotCard = {
  kind: "idea";
  title: string;
  time: string | null;
  angle: string | null;
  why: string | null;
  style: string | null;
  note: string | null;
  action: number | null;
};
export type CopilotMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  suggestion: string | null;
  status: "ok" | "unavailable";
  page: string;
  actions: CopilotAction[];
  references: CopilotReference[];
  cards: CopilotCard[];
  created_at: string;
};
export type CopilotThread = { scope: string; messages: CopilotMessage[] };
export type CopilotContext = { page: string; scope: string; facts: string[] };
export type CopilotStatus = { enabled: boolean; available: boolean };
export type CopilotResolution =
  | { kind: "navigate"; href: string }
  | { kind: "create_short"; project_id: string; video_id: string; run_id: string; candidate_id: string };

const projectQuery = (projectId: string | null) => (projectId ? `?project_id=${projectId}` : "");

export const getCopilotStatus = () => apiFetch<CopilotStatus>("/copilot/status");

export function getCopilotContext(scope: CopilotScope) {
  const params = new URLSearchParams({ page: scope.page });
  if (scope.projectId) params.set("project_id", scope.projectId);
  if (scope.clipId) params.set("clip_id", scope.clipId);
  if (scope.editId) params.set("edit_id", scope.editId);
  return apiFetch<CopilotContext>(`/copilot/context?${params}`);
}

export const getCopilotThread = (projectId: string | null) =>
  apiFetch<CopilotThread>(`/copilot/thread${projectQuery(projectId)}`);

export const clearCopilotThread = (projectId: string | null) =>
  apiFetch<void>(`/copilot/thread${projectQuery(projectId)}`, { method: "DELETE" });

export const askCopilot = (scope: CopilotScope, text: string) =>
  postJson<{ question: CopilotMessage; answer: CopilotMessage }>("/copilot/messages", {
    text,
    page: scope.page,
    project_id: scope.projectId,
    clip_id: scope.clipId,
    edit_id: scope.editId,
  });

export const resolveCopilotAction = (messageId: string, index: number) =>
  postJson<CopilotResolution>(`/copilot/messages/${messageId}/actions/${index}`, undefined);
