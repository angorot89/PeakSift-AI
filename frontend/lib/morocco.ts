// Morocco Mode (V1.8): Global PeakSift plus Moroccan context. Pure rules, no React; unit-tested
// with node --test.
//
// Morocco Mode *extends* Global — every Global tool, template and asset stays available. Each
// section shows only what really exists: the creator's own Moroccan visuals and sounds, the
// curated Morocco formats, hook ideas from the clip's own words. Nothing is called "trending":
// PeakSift has no trend source, and no figures, places or sounds are invented.

export type MoroccoSectionKey = "darija_hooks" | "local_templates" | "local_assets" | "local_sounds" | "ask";

export type MoroccoSection = {
  key: MoroccoSectionKey;
  title: string;
  /** What it does today, in creator words. */
  promise: string;
  /** Where it lives. */
  href: string;
  cta: string;
};

export const MOROCCO_SECTIONS: MoroccoSection[] = [
  {
    key: "darija_hooks",
    title: "Darija hooks",
    promise: "Opening lines from your clip's own words, in Arabic script or Latin letters — never Darija you didn't say.",
    href: "/projects",
    cta: "Open a Short's editor → Opening → Hook ideas",
  },
  {
    key: "local_templates",
    title: "Morocco content styles",
    promise: "Curated formats like Vox Pop, Darija Reaction and Food & Place Review, built from settings PeakSift already has.",
    href: "/morocco/kit?tab=templates",
    cta: "Explore the formats",
  },
  {
    key: "local_assets",
    title: "Local visuals",
    promise: "Your own Moroccan images and B-roll come first when they match a moment — with Global alternatives right after.",
    href: "/morocco/kit?tab=visuals",
    cta: "See your Moroccan visuals",
  },
  {
    key: "local_sounds",
    title: "Local sounds",
    promise: "Café, street and market ambience, transitions and reactions you made, own or licensed.",
    href: "/morocco/kit?tab=sounds",
    cta: "See your Moroccan sounds",
  },
  {
    key: "ask",
    title: "Ask PeakSift in Morocco Mode",
    promise: "“Do I have a Moroccan visual for this?”, “Which Morocco template fits this clip?”, “Can I keep this in French?”",
    href: "/projects",
    cta: "Ask from any project",
  },
];

export type KitTab = "visuals" | "sounds" | "hooks" | "templates";

export const KIT_TABS: { key: KitTab; label: string }[] = [
  { key: "visuals", label: "Visuals" },
  { key: "sounds", label: "Sounds" },
  { key: "hooks", label: "Hooks" },
  { key: "templates", label: "Templates" },
];

export const kitTab = (value: string | null): KitTab => KIT_TABS.find((t) => t.key === value)?.key ?? "visuals";

type Labelled = { category: string | null; location?: string | null };

/** Filters come only from the metadata the creator's assets really carry (empty when none). */
export function kitFilters(assets: Labelled[], categoryNames: Record<string, string>): { key: string; label: string }[] {
  const seen = new Map<string, string>();
  for (const asset of assets) {
    if (asset.category) seen.set(`category:${asset.category}`, categoryNames[asset.category] ?? asset.category);
    if (asset.location) seen.set(`location:${asset.location}`, asset.location);
  }
  return [...seen].map(([key, label]) => ({ key, label })).sort((a, b) => a.label.localeCompare(b.label));
}

type Searchable = Labelled & { display_name: string; tags?: string[]; description?: string };

const fold = (text: string) => text.normalize("NFKD").replace(/\p{M}/gu, "").toLocaleLowerCase();

/** A kit item matches every word of the query (name, tags, description, category, location) and
 * the chosen filter. */
export function kitMatches(item: Searchable, query: string, filter: string | null, categoryNames: Record<string, string>): boolean {
  if (filter) {
    const [kind, value] = filter.split(":");
    if (kind === "category" && item.category !== value) return false;
    if (kind === "location" && item.location !== value) return false;
  }
  const words = fold(query).split(/\s+/).filter(Boolean);
  const haystack = fold(
    [item.display_name, ...(item.tags ?? []), item.description ?? "", item.category ? categoryNames[item.category] ?? "" : "", item.location ?? ""].join(" "),
  );
  return words.every((word) => haystack.includes(word));
}

/** Local first, then global: the order matches are shown in (a stable sort; nothing is dropped). */
export function localFirst<T extends { local: boolean }>(items: T[]): T[] {
  return [...items.filter((item) => item.local), ...items.filter((item) => !item.local)];
}

/** Where the mode switch leads, and the default market it saves. */
export const MODES = [
  { key: "global", market: "global", href: "/home", label: "Global" },
  { key: "morocco", market: "ma", href: "/morocco", label: "Morocco Mode" },
] as const;
