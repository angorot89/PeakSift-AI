/** Auto Edit: plan types and the pure display rules (stages, sections, honest notes).
 * No imports: unit-tested with node --test. The API is the authority on every value. */
export type RecipeName = "clean" | "punchy" | "story" | "minimal";
export type PlanStatus = "queued" | "analyzing" | "planning" | "validating" | "ready" | "applied" | "failed";

export type Recipe = { name: RecipeName; version: string; label: string; description: string };

export type PlanVisualItem = { start: number; end: number; mode: string; asset_name: string; query: string };
export type PlanSection = { choice: string; reason: string; items?: PlanVisualItem[] };
export type SectionKey = "layout" | "captions" | "hook" | "visuals" | "audio";

/** Creator-facing explanations (product copy; never a prompt or a model's reasoning). */
export type PlanExplanations = { version: string; sections: Partial<Record<SectionKey, PlanSection>>; notes: string[] };

/** What a plan was based on, in plain values (never a score). */
export type PlanConfidence = {
  planner: "local_ai" | "rules";
  fallback: boolean;
  framing: "high" | "mixed" | "fallback" | null;
  word_timing: boolean;
  phrase_timing: boolean;
  broll_method: "local_ai" | "keyword" | "keyword_fallback" | null;
  broll_suggestions: number;
  matched_assets: number;
};

export type AutoEditPlan = {
  id: string;
  clip_id: string;
  status: PlanStatus;
  progress_percent: number;
  attempt: number;
  is_stale: boolean;
  generation: number;
  recipe: RecipeName;
  recipe_version: string;
  recipe_label: string;
  music_asset_id: string | null;
  /** A normal edit configuration (the same snapshot an edit stores), once ready. */
  configuration: Record<string, unknown> | null;
  explanations: PlanExplanations | null;
  confidence: PlanConfidence | null;
  clip_edit_id: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  applied_at: string | null;
  /** Patterns from the creator's own shorts this plan was given (only when they asked). */
  performance_hints?: string[] | null;
};

/** Whether patterns from the creator's published shorts can inform a plan right now. */
export type PerformanceContext = { available: boolean; simulated: boolean; sample_size: number; hints: string[] };
export const ACTIVE_PLAN_STATUSES: PlanStatus[] = ["queued", "analyzing", "planning", "validating"];
export const isPlanActive = (status: PlanStatus) => ACTIVE_PLAN_STATUSES.includes(status);

// Creator words for the plan's sections (the editor's tools use the same names).
export const SECTIONS: { key: SectionKey; title: string }[] = [
  { key: "layout", title: "Framing" },
  { key: "captions", title: "Captions" },
  { key: "hook", title: "Opening" },
  { key: "visuals", title: "Visuals" },
  { key: "audio", title: "Sound" },
];

/**
 * What each recipe feels like, in three short traits that follow its real bounds (caption
 * presets, how many visuals, sound effects, music level) — not marketing.
 */
export const RECIPE_TRAITS: Record<RecipeName, string[]> = {
  clean: ["Balanced", "clean captions", "a few supporting visuals"],
  punchy: ["Bold captions", "a sharp opening", "quick cutaways and sound effects"],
  story: ["Calm captions", "meaningful cutaways", "music kept low"],
  minimal: ["Speaker first", "minimal captions", "almost nothing added"],
};

export type StepState = "done" | "current" | "todo" | "failed";
export type PlanStep = { label: string; state: StepState };

// One label per stage the job really reports (queued/analyzing → planning → validating → ready).
export const STEP_LABELS = [
  "Understanding the clip",
  "Choosing framing, captions, visuals and sound",
  "Checking every choice",
  "Ready to review",
];
const STEP_INDEX: Record<PlanStatus, number> = {
  queued: 0,
  analyzing: 0,
  planning: 1,
  validating: 2,
  ready: 3,
  applied: 3,
  failed: -1,
};

/** Honest stages (the job reports stages, not a percentage of work). */
export function planSteps(status: PlanStatus, failedAt = 0): PlanStep[] {
  const current = STEP_INDEX[status];
  return STEP_LABELS.map((label, index) => {
    if (status === "failed") return { label, state: index < failedAt ? "done" : index === failedAt ? "failed" : "todo" };
    if (index < current || ((status === "ready" || status === "applied") && index === current)) return { label, state: "done" };
    return { label, state: index === current ? "current" : "todo" };
  });
}

/** One line on who planned it, said honestly. */
export function plannerNote(confidence: PlanConfidence | null): string | null {
  if (!confidence) return null;
  if (confidence.planner === "local_ai") return "Planned by the local AI, then checked by PeakSift.";
  if (confidence.fallback) return "The local AI was unavailable, so PeakSift planned this with its built-in rules.";
  return "Planned with PeakSift's built-in rules.";
}

/** The sections in display order, skipping any the plan does not explain. */
export function planSections(plan: AutoEditPlan): { key: SectionKey; title: string; section: PlanSection }[] {
  const sections = plan.explanations?.sections ?? {};
  return SECTIONS.flatMap(({ key, title }) => {
    const section = sections[key];
    return section ? [{ key, title, section }] : [];
  });
}

/** What the plan was based on, for a short "Based on" line (only facts that are true). */
export function basedOn(confidence: PlanConfidence | null): string[] {
  if (!confidence) return [];
  const facts: string[] = [];
  const framing = { high: "face framing", mixed: "face framing (faces in part of the clip)", fallback: "centred framing (no clear face)" };
  if (confidence.framing) facts.push(framing[confidence.framing]);
  if (confidence.word_timing) facts.push("word timing");
  else if (confidence.phrase_timing) facts.push("transcript timing");
  if (confidence.broll_suggestions)
    facts.push(`${confidence.broll_suggestions} B-roll suggestion${confidence.broll_suggestions === 1 ? "" : "s"}`);
  if (confidence.matched_assets)
    facts.push(`${confidence.matched_assets} matching asset${confidence.matched_assets === 1 ? "" : "s"}`);
  return facts;
}

/** What is still missing that would let Auto Edit do more (offered, never started for you). */
export function missingInputs(confidence: PlanConfidence | null): string[] {
  if (!confidence) return [];
  const missing: string[] = [];
  if (!confidence.framing) missing.push("Analyze framing for Smart Reframe");
  if (!confidence.word_timing) missing.push("Generate word sync for word-by-word captions");
  if (!confidence.broll_suggestions) missing.push("Suggest B-roll to add matching visuals");
  return missing;
}

export function formatSpan(start: number, end: number): string {
  const f = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
  return `${f(start)}–${f(end)}`;
}

/** The editor opened on this plan (or the version made from it), at one tool group. */
export function planEditorLink(
  editorLink: string,
  plan: Pick<AutoEditPlan, "id" | "status" | "clip_edit_id">,
  tool?: SectionKey,
): string {
  const from = plan.status === "applied" && plan.clip_edit_id ? `edit=${plan.clip_edit_id}` : `plan=${plan.id}`;
  return `${editorLink}?${from}${tool ? `&tool=${tool}` : ""}`;
}
