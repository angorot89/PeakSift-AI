// Morocco Mode (preview): the UI architecture for Global + Moroccan intelligence. Pure rules, no
// React; unit-tested with node --test.
//
// Morocco Mode *extends* Global — every Global tool and library stays available. No Moroccan
// data source exists yet (no Darija hooks, sound library, trends or local assets), so every
// Morocco capability is "not available yet" and says so; nothing here is generated or invented.
// When a real source lands, its capability flips to available and its section shows real data.

/** The preview is off unless the build enables it (NEXT_PUBLIC_MOROCCO_MODE_PREVIEW=1). */
export function moroccoPreviewEnabled(value: string | undefined = process.env.NEXT_PUBLIC_MOROCCO_MODE_PREVIEW): boolean {
  return value === "1" || value === "true";
}

export type MoroccoCapabilityKey = "darija_hooks" | "local_sounds" | "local_trends" | "local_templates" | "local_assets" | "clip_suggestions";

export type MoroccoCapability = {
  key: MoroccoCapabilityKey;
  title: string;
  /** What it will do, in creator words. */
  promise: string;
  /** False until a real data source exists; the UI then shows "Not available yet". */
  available: boolean;
  /** What works today in Global instead (always a real page). */
  today: { label: string; href: string } | null;
};

export const MOROCCO_CAPABILITIES: MoroccoCapability[] = [
  {
    key: "darija_hooks",
    title: "Darija hook ideas",
    promise: "Opening lines in Darija — Arabic script or Latin letters — grounded in your clip's own words.",
    available: false,
    today: { label: "Write your own opening in the editor (Arabic script works)", href: "/projects" },
  },
  {
    key: "local_sounds",
    title: "Moroccan sound library",
    promise: "Music, ambience and reactions from Morocco, cleared for your Shorts.",
    available: false,
    today: { label: "Upload sounds you own to a project", href: "/projects" },
  },
  {
    key: "local_trends",
    title: "What Moroccan audiences watch",
    promise: "Topics and formats doing well with Moroccan viewers.",
    available: false,
    today: null,
  },
  {
    key: "local_templates",
    title: "Templates for Moroccan content",
    promise: "Caption styles and hooks made for Darija and mixed-script captions.",
    available: false,
    today: { label: "Use your own templates", href: "/brand" },
  },
  {
    key: "local_assets",
    title: "Moroccan visuals",
    promise: "B-roll and images of Moroccan places and culture, matched to your clip first — with global alternatives next to them.",
    available: false,
    today: { label: "Search the visuals you uploaded", href: "/projects" },
  },
  {
    key: "clip_suggestions",
    title: "Morocco-aware suggestions",
    promise: "Which moments fit a Moroccan audience, which also travel globally, and why.",
    available: false,
    today: { label: "Ask PeakSift about your moments", href: "/home" },
  },
];

export const capability = (key: MoroccoCapabilityKey) => MOROCCO_CAPABILITIES.find((c) => c.key === key)!;

export type KitTab = "images" | "broll" | "sounds" | "hooks" | "templates";

/** The Creator Kit's library tabs and the capability each depends on. */
export const KIT_TABS: { key: KitTab; label: string; needs: MoroccoCapabilityKey }[] = [
  { key: "images", label: "Images", needs: "local_assets" },
  { key: "broll", label: "B-roll", needs: "local_assets" },
  { key: "sounds", label: "Sounds", needs: "local_sounds" },
  { key: "hooks", label: "Hooks", needs: "darija_hooks" },
  { key: "templates", label: "Templates", needs: "local_templates" },
];

/** Place and topic filters ship only with data behind them: none until a local library exists. */
export function kitFilters(capabilities: MoroccoCapability[] = MOROCCO_CAPABILITIES): string[] {
  return capabilities.find((c) => c.key === "local_assets")?.available ? ["All"] : [];
}

/** Local first, then global: the order matches are shown in (a stable sort; nothing is dropped). */
export function localFirst<T extends { local: boolean }>(items: T[]): T[] {
  return [...items.filter((item) => item.local), ...items.filter((item) => !item.local)];
}
