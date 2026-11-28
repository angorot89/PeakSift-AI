/** Filtering and wording for the library browser. Pure: unit-tested with node --test. */
import type { LibraryItem, LibraryKind } from "./library.ts";

const CATEGORY_LABELS: Record<string, string> = {
  transitions: "Transitions",
  hits: "Hits & booms",
  interface: "Clicks & pops",
  alerts: "Alerts",
  funny: "Funny",
  money: "Money",
  stings: "Stings",
  calm: "Calm",
  chill: "Chill",
  cinematic: "Cinematic",
  upbeat: "Upbeat",
  energetic: "Energetic",
  suspense: "Suspense",
  playful: "Playful",
  emoji: "Emoji",
  celebrate: "Celebrate",
  energy: "Energy",
  magic: "Magic",
};

export const categoryLabel = (category: string) =>
  CATEGORY_LABELS[category] ?? category.charAt(0).toUpperCase() + category.slice(1);

/** The categories of one kind, in the order they first appear in the catalogue. */
export function categoriesOf(items: readonly LibraryItem[], kind: LibraryKind): string[] {
  return [...new Set(items.filter((i) => i.kind === kind).map((i) => i.category))];
}

const fold = (text: string) => text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

/** Items of one kind matching the search (title, tags, category) and the chosen category. */
export function filterLibrary(
  items: readonly LibraryItem[],
  kind: LibraryKind,
  query: string,
  category: string | null,
): LibraryItem[] {
  const words = fold(query).split(/\s+/).filter(Boolean);
  return items.filter((item) => {
    if (item.kind !== kind || (category && item.category !== category)) return false;
    const haystack = fold([item.title, item.category, categoryLabel(item.category), ...item.tags].join(" "));
    return words.every((word) => haystack.includes(word));
  });
}

/** "0.6 s" or "1:24" */
export function lengthLabel(seconds: number | null): string {
  if (seconds == null) return "";
  if (seconds < 10) return `${(Math.round(seconds * 10) / 10).toFixed(1)} s`;
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
