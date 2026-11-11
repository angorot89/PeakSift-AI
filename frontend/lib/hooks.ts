import { apiFetch } from "@/lib/api";
import type { HookIdeas, HookTarget } from "@/lib/hooks-rules";

export * from "@/lib/hooks-rules";

export const getHookIdeas = (projectId: string, videoId: string, clipId: string, target: HookTarget) =>
  apiFetch<HookIdeas>(`/projects/${projectId}/videos/${videoId}/clips/${clipId}/hooks?target=${target}`);
