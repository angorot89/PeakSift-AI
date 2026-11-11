// Brand Studio API (V1.7): the creator's brands, Short templates and logo images.
// Brands and templates are preferences; a Short copies the values it uses into its snapshot.

import { API_URL, apiFetch, postJson } from "@/lib/api";
import type { LogoCorner, LogoSize } from "@/lib/brand-rules";

export type BrandLogo = {
  id: string;
  project_id: string;
  project_name: string;
  name: string;
  width: number;
  height: number;
  transparent: boolean;
  has_thumbnail: boolean;
};

export type Brand = {
  id: string;
  name: string;
  is_default: boolean;
  primary_color: string;
  secondary_color: string | null;
  accent_color: string | null;
  caption_emphasis_color: string | null;
  caption_emphasis_readable: boolean | null;
  logo: BrandLogo | null;
  logo_position: LogoCorner;
  logo_size: LogoSize;
  end_card_text: string | null;
  created_at: string;
  updated_at: string;
};

export type BrandInput = {
  name: string;
  primary_color: string;
  accent_color: string | null;
  caption_emphasis_color: string | null;
  logo_asset_id: string | null;
  logo_position: LogoCorner;
  logo_size: LogoSize;
  end_card_text: string | null;
};

export type BrandLayout = {
  logo_width_fraction: Record<LogoSize, number>;
  card: { logo_fraction: number; logo_center_y: number; name_y: number; text_y: number };
  end_card_seconds: [number, number];
  frame: { width: number; height: number };
  margins: { top: number; bottom: number; left: number; right: number };
};

export const listBrands = () => apiFetch<Brand[]>("/brand/profiles");
export const getBrand = (id: string) => apiFetch<Brand>(`/brand/profiles/${id}`);
export const createBrand = (input: BrandInput & { is_default?: boolean }) => postJson<Brand>("/brand/profiles", input);
export const updateBrand = (id: string, changes: Partial<BrandInput> & { is_default?: boolean }) =>
  apiFetch<Brand>(`/brand/profiles/${id}`, { method: "PATCH", body: JSON.stringify(changes) });
export const deleteBrand = (id: string) => apiFetch<null>(`/brand/profiles/${id}`, { method: "DELETE" });
export const listLogoCandidates = () => apiFetch<BrandLogo[]>("/brand/logo-candidates");
export const getBrandLayout = () => apiFetch<BrandLayout>("/brand/layout");

/** The brand section a Short would use now (a template, the default template or the default
 * brand) and the template it came from. */
export type EditSection = {
  brand: Record<string, unknown> | null;
  template: { id: string; name: string; version: number } | null;
};
export const getEditSection = (templateId?: string | null) =>
  apiFetch<EditSection>(`/brand/edit-section${templateId ? `?template_id=${templateId}` : ""}`);

/** The logo image itself (private, served with the creator's session). */
export const logoUrl = (logo: Pick<BrandLogo, "id" | "project_id">) =>
  `${API_URL}/projects/${logo.project_id}/visual-assets/${logo.id}/content`;
export const logoThumbnailUrl = (logo: Pick<BrandLogo, "id" | "project_id">) =>
  `${API_URL}/projects/${logo.project_id}/visual-assets/${logo.id}/thumbnail`;

// --- Short templates ---------------------------------------------------------------------------

export type TemplateRecipe = "clean" | "punchy" | "story" | "minimal";

/** Mirrors branding/template_config.py: null = "let the recipe decide". */
export type TemplateSettings = {
  version?: string;
  framing: "auto" | "smart_reframe" | "blur_background" | "center_crop" | "fit";
  captions: boolean;
  caption_preset: "focus" | "punch" | "minimal" | "boxed" | null;
  caption_position: "top" | "center" | "bottom" | null;
  hook: boolean;
  hook_style: "headline" | "boxed" | "minimal" | null;
  hook_position: "top" | "center" | null;
  hook_seconds: number | null;
  broll: "none" | "light" | "recipe";
  music_level: "quiet" | "low" | "medium" | null;
  ducking: "off" | "light" | "medium" | "strong" | null;
  sound_effects: boolean;
  normalize_loudness: boolean;
  logo: boolean;
  end_card: boolean;
  end_card_seconds: number | null;
};

export type Template = {
  id: string;
  name: string;
  description: string;
  recipe: TemplateRecipe | null;
  brand: { id: string; name: string; primary_color: string; has_logo: boolean } | null;
  config: TemplateSettings;
  version: number;
  is_default: boolean;
  /** The market it was made for ("global", or "ma" for a Morocco format); works everywhere. */
  market?: string;
  created_at: string;
  updated_at: string;
};

export type TemplateStarter = {
  /** A recipe's name, or a curated market format ("ma_vox_pop"). */
  key: string;
  market: string;
  recipe: TemplateRecipe;
  label: string;
  description: string;
  config: TemplateSettings;
};

export type TemplateInput = {
  name: string;
  description: string;
  recipe: TemplateRecipe | null;
  brand_profile_id: string | null;
  config: TemplateSettings;
  is_default?: boolean;
  market?: string;
};

export const listTemplates = () => apiFetch<Template[]>("/brand/templates");
export const getTemplate = (id: string) => apiFetch<Template>(`/brand/templates/${id}`);
/** The Global starters; with a market, its curated formats first (Global ones always included). */
export const listTemplateStarters = (market?: string) =>
  apiFetch<TemplateStarter[]>(`/brand/template-starters${market && market !== "global" ? `?market=${market}` : ""}`);
export const createTemplate = (input: TemplateInput) => postJson<Template>("/brand/templates", input);
export const updateTemplate = (id: string, changes: Partial<TemplateInput>) =>
  apiFetch<Template>(`/brand/templates/${id}`, { method: "PATCH", body: JSON.stringify(changes) });
export const duplicateTemplate = (id: string) =>
  apiFetch<Template>(`/brand/templates/${id}/duplicate`, { method: "POST" });
export const deleteTemplate = (id: string) => apiFetch<null>(`/brand/templates/${id}`, { method: "DELETE" });
