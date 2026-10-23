import { apiFetch } from "@/lib/api";
import type { Home, ProjectSummary } from "@/lib/workspace-rules";

export * from "@/lib/workspace-rules";

export const getHome = () => apiFetch<Home>("/workspace/home");
export const getProjectSummary = (projectId: string) => apiFetch<ProjectSummary>(`/projects/${projectId}/summary`);
