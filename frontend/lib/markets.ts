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

export type Markets = { markets: MarketProfile[]; content_languages: { code: string; label: string }[] };

export const getMarkets = () => apiFetch<Markets>("/markets");

/** The default market for new projects (never changes existing projects or Shorts). */
export const setDefaultMarket = (market: string) =>
  apiFetch<User>("/auth/me", { method: "PATCH", body: JSON.stringify({ default_market: market }), headers: { "Content-Type": "application/json" } });
