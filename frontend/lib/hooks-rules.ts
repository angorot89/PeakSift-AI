// Hook ideas (V1.8), pure rules (no React; unit-tested): which languages to offer and in what
// order, and how to name an idea's kind and source. The server checks every suggestion.

export type HookTarget = "original" | "darija_arabic" | "darija_latin" | "arabic" | "french" | "english";

export type HookIdea = {
  text: string;
  kind: "question" | "reaction" | "curiosity" | "story" | "lesson" | "comparison" | "local_context" | "direct";
  language: string;
  script: "arabic" | "latin" | "mixed";
  method: "transcript" | "transliteration" | "local_ai";
  /** The transcript sentence it comes from (transcript) or rephrases (local AI). */
  source: string;
  meaning: string | null;
};

export type HookIdeas = {
  target: HookTarget;
  language: { chosen: string; detected: { language: string; label: string } };
  market: string;
  ideas: HookIdea[];
  note: "unavailable" | "none_grounded" | "unsupported" | null;
};

const LABELS: Record<HookTarget, string> = {
  original: "From your clip",
  darija_arabic: "Darija · Arabic script",
  darija_latin: "Darija · Latin letters",
  arabic: "Arabic",
  french: "French",
  english: "English",
};

/** The language choices, in a sensible order — never forcing Darija: "From your clip" (the
 * original language) always comes first; Darija leads the rest only when the project is in
 * Darija or mixed, or made for Morocco. */
export function hookTargets(market: string, language: string | null): { key: HookTarget; label: string }[] {
  const darijaFirst = language === "darija" || language === "mixed" || market === "ma";
  const rest: HookTarget[] = darijaFirst
    ? ["darija_arabic", "darija_latin", "french", "arabic", "english"]
    : ["english", "french", "arabic", "darija_arabic", "darija_latin"];
  return (["original", ...rest] as HookTarget[]).map((key) => ({ key, label: LABELS[key] }));
}

const KINDS: Record<HookIdea["kind"], string> = {
  question: "Question",
  reaction: "Reaction",
  curiosity: "Curiosity",
  story: "Story",
  lesson: "Lesson",
  comparison: "Comparison",
  local_context: "Local context",
  direct: "Direct statement",
};
export const kindLabel = (kind: HookIdea["kind"]) => KINDS[kind] ?? "Idea";

export function methodLabel(idea: HookIdea): string {
  if (idea.method === "transcript") return "Your clip's own words";
  if (idea.method === "transliteration") return "Your words in the other script — check the spelling";
  return "Local AI rewrite of your line — check it says the same";
}

export function noteText(note: HookIdeas["note"]): string | null {
  if (note === "unavailable") return "The local assistant isn't available right now, so these are lines from your clip.";
  if (note === "none_grounded") return "Nothing the local assistant suggested stayed true to your clip, so only your clip's own lines are shown.";
  if (note === "unsupported") return "PeakSift can't write this language from your clip yet — here are your clip's own lines. Darija comes only from words you said.";
  return null;
}

/** The HTML lang of an idea (for screen readers and Arabic shaping). */
export function langOf(idea: Pick<HookIdea, "language" | "script">): string | undefined {
  if (idea.script === "arabic") return "ar";
  return { french: "fr", english: "en" }[idea.language];
}
