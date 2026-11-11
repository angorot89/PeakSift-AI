// Asset labels (V1.8), pure rules: where an asset comes from, whether it is local to a market,
// its category and — local only — its location. Chosen by the creator; the server validates.

export type AssetLabels = {
  origin: string;
  license_note: string | null;
  market: string;
  category: string | null;
  location: string | null;
};

export const labelsOf = (asset: Partial<AssetLabels>): AssetLabels => ({
  origin: asset.origin ?? "creator_upload",
  license_note: asset.license_note ?? null,
  market: asset.market ?? "global",
  category: asset.category ?? null,
  location: asset.location ?? null,
});

/** What the form would send: only fields that changed, Global assets never keep a location, and
 * a licence note only with a licensed origin… unless the creator wrote one. */
export function labelChanges(before: AssetLabels, after: AssetLabels): Partial<AssetLabels> {
  const next = { ...after, location: after.market === "global" ? null : after.location };
  const changes: Partial<AssetLabels> = {};
  for (const key of Object.keys(next) as (keyof AssetLabels)[]) {
    if ((next[key] ?? null) !== (before[key] ?? null)) (changes as Record<string, unknown>)[key] = next[key];
  }
  return changes;
}

/** A form problem to show before saving (the server checks again). */
export function labelProblem(labels: AssetLabels): string | null {
  if (labels.origin === "licensed" && !(labels.license_note ?? "").trim()) return "Write down the licence or where you licensed it from.";
  return null;
}

/** "Moroccan · Café · Casablanca · CC0" — a card's short line (empty for unlabelled Global). */
export function labelLine(
  labels: AssetLabels,
  names: { localLabel: string | null; categories: Record<string, string>; origins: Record<string, string> },
): string {
  const parts: string[] = [];
  if (labels.market !== "global" && names.localLabel) parts.push(names.localLabel);
  if (labels.category) parts.push(names.categories[labels.category] ?? labels.category);
  if (labels.location) parts.push(labels.location);
  if (labels.origin !== "creator_upload") parts.push(names.origins[labels.origin] ?? labels.origin);
  return parts.join(" · ");
}
