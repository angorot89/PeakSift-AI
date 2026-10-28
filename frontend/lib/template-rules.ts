// Short template rules for the builder, the library and the create flow (pure, unit-tested).
// A setting left empty means "the starting style decides": these resolve what a preview shows
// and describe a template in a few creator words.

import type { TemplateRecipe, TemplateSettings, TemplateStarter } from "./brand.ts";

export const BLANK: TemplateSettings = {
  framing: "auto",
  captions: true,
  caption_preset: null,
  caption_position: null,
  hook: true,
  hook_style: null,
  hook_position: null,
  hook_seconds: null,
  broll: "recipe",
  music_level: null,
  ducking: null,
  sound_effects: true,
  normalize_loudness: true,
  logo: true,
  end_card: false,
  end_card_seconds: null,
};

export const RECIPE_LABELS: Record<TemplateRecipe, string> = {
  clean: "Clean",
  punchy: "Punchy",
  story: "Story",
  minimal: "Minimal",
};

const LABEL: Record<string, string> = {
  focus: "Focus",
  punch: "Punch",
  minimal: "Minimal",
  boxed: "Boxed",
  headline: "Headline",
  auto: "Auto framing",
  smart_reframe: "Smart Reframe",
  blur_background: "Blur background",
  center_crop: "Center crop",
  fit: "Fit",
};

/** What a preview shows: empty settings resolved from the starting style's own defaults. */
export function resolved(settings: TemplateSettings, starter: TemplateSettings | null) {
  const base = starter ?? BLANK;
  return {
    captions: settings.captions,
    preset: settings.caption_preset ?? base.caption_preset ?? "focus",
    captionPosition: settings.caption_position ?? base.caption_position ?? "bottom",
    hook: settings.hook,
    hookStyle: settings.hook_style ?? base.hook_style ?? "headline",
    hookPosition: settings.hook_position ?? base.hook_position ?? (settings.caption_position === "top" ? "center" : "top"),
    hookSeconds: settings.hook_seconds ?? base.hook_seconds ?? 2,
    logo: settings.logo,
    endCard: settings.end_card,
    endCardSeconds: settings.end_card_seconds ?? 2,
  } as const;
}

/** A few creator words for a template card ("Punch captions · Boxed hook · Light B-roll"). */
export function summary(settings: TemplateSettings, hasLogo: boolean): string {
  const parts: string[] = [];
  if (settings.framing !== "auto") parts.push(LABEL[settings.framing]);
  parts.push(settings.captions ? `${settings.caption_preset ? LABEL[settings.caption_preset] : "Style's"} captions` : "No captions");
  if (!settings.hook) parts.push("No hook");
  else if (settings.hook_style) parts.push(`${LABEL[settings.hook_style]} hook`);
  parts.push(settings.broll === "none" ? "No B-roll" : settings.broll === "light" ? "Light B-roll" : "B-roll as the style suggests");
  if (settings.logo && hasLogo) parts.push("Logo");
  if (settings.end_card) parts.push(`End card +${settings.end_card_seconds ?? 2}s`);
  return parts.join(" · ");
}

/** The settings a starting point gives (a recipe's defaults, or blank). */
export function startFrom(starter: TemplateStarter | null): TemplateSettings {
  return { ...BLANK, ...(starter?.config ?? {}) };
}

/** Whether two settings would edit Shorts the same way (for "Unsaved changes"). */
export function sameSettings(a: TemplateSettings, b: TemplateSettings): boolean {
  const keys = Object.keys(BLANK) as (keyof TemplateSettings)[];
  return keys.every((key) => (a[key] ?? null) === (b[key] ?? null));
}

/** Captions and the hook never share a place: the hook positions still free. */
export function freeHookPositions(captionPosition: TemplateSettings["caption_position"]): ("top" | "center")[] {
  return (["top", "center"] as const).filter((p) => p !== captionPosition);
}
