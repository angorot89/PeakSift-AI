// Find Clips (pure rules, no React): example requests, what to say when nothing was found, and
// how a result describes its match. Unit-tested with node --test.

export const FIND_CLIPS_QUERY_MAX = 200;
export const FIND_CLIPS_QUERY_MIN = 2;

export const FIND_CLIPS_EXAMPLES = [
  "the part where I explain pricing",
  "when I tell the story about my first video",
  "the funniest moment",
];

export type FoundMatch = { matched: string[]; related: string[] };

/** "Heard: pricing, price" / "Related words heard: cost" — what a result is based on. */
export function matchSummary(result: FoundMatch): string {
  if (result.matched.length) {
    const own = `Heard: ${result.matched.join(", ")}`;
    return result.related.length ? `${own} · related: ${result.related.join(", ")}` : own;
  }
  return result.related.length ? `Related words heard: ${result.related.join(", ")}` : "";
}

/** Why a search came back empty, and what to try. */
export function emptySearch(terms: string[], related: string[]): { title: string; description: string } {
  if (!terms.length) {
    return {
      title: "Add a word you would have said",
      description: "PeakSift searches the words spoken in your video. Try a topic, a name or a number — “pricing”, not “the best part”.",
    };
  }
  const looked = [...terms, ...related].map((word) => `“${word}”`).join(", ");
  return {
    title: "Nothing in this video matches",
    description: `Looked for ${looked}. Try another word you remember saying.`,
  };
}

/** A request is searchable once it has two real characters. */
export function canSearch(query: string): boolean {
  return query.trim().length >= FIND_CLIPS_QUERY_MIN;
}
