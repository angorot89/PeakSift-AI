import { apiFetch, postJson } from "@/lib/api";

export type ProjectStatus = "created";

export type Project = {
  id: string;
  name: string;
  status: ProjectStatus;
  /** The market its Shorts are made for ("global", "ma") and the language its videos are in. */
  market: string;
  content_language: string;
  created_at: string;
  updated_at: string;
};

export const PROJECT_NAME_MAX_LENGTH = 200;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const isProjectId = (value: string) => UUID_PATTERN.test(value);

export const listProjects = () => apiFetch<Project[]>("/projects");
export const getProject = (id: string) => apiFetch<Project>(`/projects/${id}`);
export const createProject = (name: string, market?: string) =>
  postJson<Project>("/projects", market ? { name, market } : { name });
/** An explicit change of market or language; Shorts already made keep theirs. */
export const updateProject = (id: string, changes: { market?: string; content_language?: string }) =>
  apiFetch<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(changes), headers: { "Content-Type": "application/json" } });

export type MediaDeletion = {
  media_files_removed: number;
  /** Files that could not be removed right away; the server's storage cleanup removes them. */
  media_files_pending_cleanup: number;
};

/** Permanently delete a project and its media. ``confirmName`` must be the exact name. */
export const deleteProject = (id: string, confirmName: string) =>
  apiFetch<MediaDeletion>(`/projects/${id}`, {
    method: "DELETE",
    body: JSON.stringify({ confirm_name: confirmName }),
  });
