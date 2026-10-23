// Reviewing found moments: the four filters, what each asks the API for, and its empty state.

export type MomentFilter = "all" | "top" | "saved" | "dismissed";
export type MomentCounts = { active: number; top: number; saved: number; dismissed: number };

export const MOMENT_FILTERS: { value: MomentFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "top", label: "Top picks" },
  { value: "saved", label: "Saved" },
  { value: "dismissed", label: "Dismissed" },
];

/** The listing query for a filter: "All" leaves dismissed moments out (they have their own filter). */
export function momentQuery(filter: MomentFilter): { view?: "active" | "top"; decision?: "saved" | "dismissed" } {
  if (filter === "all") return { view: "active" };
  if (filter === "top") return { view: "top" };
  return { decision: filter };
}

export function momentCount(counts: MomentCounts, filter: MomentFilter): number {
  return filter === "all" ? counts.active : counts[filter];
}

/** What an empty filter says, and which filter (if any) to offer instead. */
export function emptyMoments(
  filter: MomentFilter,
  counts: MomentCounts,
): { title: string; description: string; offer?: MomentFilter } {
  if (filter === "all") {
    return counts.dismissed > 0
      ? { title: "You dismissed every moment", description: "Dismissed moments are kept; restore any of them.", offer: "dismissed" }
      : {
          title: "No moments worth clipping were found",
          description: "Nothing in this transcript met the bar. Try finding moments again with another model.",
        };
  }
  if (filter === "top") {
    return {
      title: "No top picks",
      description: "None of these moments was ranked first or scored strongly. All shows every moment.",
      offer: counts.active > 0 ? "all" : undefined,
    };
  }
  if (filter === "saved") return { title: "Nothing saved yet", description: "Save the moments you want to come back to." };
  return { title: "Nothing dismissed", description: "Moments you dismiss are kept here, so you can restore them." };
}
