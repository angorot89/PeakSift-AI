import { apiFetch } from "@/lib/api";
import type { User } from "@/lib/auth";

/** A market PeakSift offers (Global, or a local market such as Morocco, "ma"). */
export type MarketProfile = {
  code: string;
  name: string;
  /** How local resources are called ("Moroccan"); null for Global. */
  local_label: string | null;
  hook_languages: string[];
  locations: string[];
};

type Labelled = { code: string; label: string }[];

export type Markets = {
  markets: MarketProfile[];
  content_languages: Labelled;
  asset_origins: Labelled;
  visual_categories: Labelled;
  audio_categories: Labelled;
};

/** The creator's assets marked local to a market, across their projects (the Creator Kit). */
export type KitAsset = {
  id: string;
  project: { id: string; name: string };
  kind: string;
  display_name: string;
  duration_seconds: number | null;
  origin: string;
  license_note: string | null;
  market: string;
  category: string | null;
  location: string | null;
  has_thumbnail?: boolean;
  description?: string;
  tags?: string[];
};

export const getLocalAssets = (market: string, kind: "visual" | "audio") =>
  apiFetch<{ market: string; kind: string; assets: KitAsset[] }>(`/markets/${market}/assets?kind=${kind}`);

export const getMarkets = () => apiFetch<Markets>("/markets");

/** The default market for new projects (never changes existing projects or Shorts). */
export const setDefaultMarket = (market: string) =>
  apiFetch<User>("/auth/me", { method: "PATCH", body: JSON.stringify({ default_market: market }), headers: { "Content-Type": "application/json" } });

/** A project's content language: the creator's choice (which wins) and a hedged detection. */
export type ProjectLanguage = {
  chosen: string;
  detected: { language: string; confidence: "likely" | "possible"; scripts: string[]; languages: string[]; label: string };
  /** What PeakSift works with: the choice, else the detection (null when it can't tell). */
  effective: string | null;
};

export const getProjectLanguage = (projectId: string) => apiFetch<ProjectLanguage>(`/projects/${projectId}/language`);
