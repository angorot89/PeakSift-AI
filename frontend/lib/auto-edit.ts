import { apiFetch, postJson } from "@/lib/api";
import { ACTIVE_PLAN_STATUSES, type AutoEditPlan, type Recipe, type RecipeName } from "@/lib/auto-edit-rules";
import type { ClipEdit } from "@/lib/edits";
import { stageRanks } from "@/lib/status-sync";

export * from "@/lib/auto-edit-rules";

const base = (projectId: string, videoId: string, clipId: string) =>
  `/projects/${projectId}/videos/${videoId}/clips/${clipId}/auto-edits`;

export const listRecipes = () => apiFetch<Recipe[]>("/auto-edit/recipes");
export const createPlan = (p: string, v: string, c: string, recipe: RecipeName, musicAssetId: string | null) =>
  postJson<AutoEditPlan>(base(p, v, c), { recipe, ...(musicAssetId ? { music_asset_id: musicAssetId } : {}) });
export const listPlans = (p: string, v: string, c: string) => apiFetch<{ plans: AutoEditPlan[] }>(base(p, v, c));
export const getPlan = (p: string, v: string, c: string, id: string) => apiFetch<AutoEditPlan>(`${base(p, v, c)}/${id}`);
export const retryPlan = (p: string, v: string, c: string, id: string) =>
  postJson<AutoEditPlan>(`${base(p, v, c)}/${id}/retry`, {});
export const regeneratePlan = (p: string, v: string, c: string, id: string) =>
  postJson<AutoEditPlan>(`${base(p, v, c)}/${id}/regenerate`, {});
export const applyPlan = (p: string, v: string, c: string, id: string) =>
  postJson<{ plan: AutoEditPlan; edit: ClipEdit }>(`${base(p, v, c)}/${id}/apply`, {});

export const autoEditHref = (projectId: string, clipId: string) => `/projects/${projectId}/clips/${clipId}/auto-edit`;

export const PLAN_STAGES = stageRanks(ACTIVE_PLAN_STATUSES, ["ready", "applied", "failed"]);
