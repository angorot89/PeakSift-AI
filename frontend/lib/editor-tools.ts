// The editor's tool groups and how links (e.g. from an Auto Edit review) open one of them.

export type ToolKey = "style" | "captions" | "opening" | "visuals" | "sound" | "brand";

export const TOOLS: { key: ToolKey; label: string }[] = [
  { key: "style", label: "Style" },
  { key: "captions", label: "Captions" },
  { key: "opening", label: "Opening" },
  { key: "visuals", label: "Visuals" },
  { key: "sound", label: "Sound" },
  { key: "brand", label: "Brand" },
];

/** Auto Edit's section names, as used in `?tool=` links from its review. */
const FROM_SECTION: Record<string, ToolKey> = { layout: "style", hook: "opening", audio: "sound" };

/** The tool group a `?tool=` value opens; anything unknown opens Style. */
export function toolFromParam(value: string | null): ToolKey {
  if (!value) return "style";
  if (TOOLS.some((tool) => tool.key === value)) return value as ToolKey;
  return FROM_SECTION[value] ?? "style";
}

export type ToolMark = "on" | "attention" | null;

/** A tool's mark: "attention" when it blocks rendering, "on" when it adds something. */
export function toolMarks(state: {
  awaitingAnalysis: boolean;
  awaitingWords: boolean;
  hookOn: boolean;
  hookInvalid: boolean;
  visuals: number;
  visualsInvalid: boolean;
  audioActive: boolean;
  branded: boolean;
}): Record<ToolKey, ToolMark> {
  return {
    style: state.awaitingAnalysis ? "attention" : null,
    captions: state.awaitingWords ? "attention" : null,
    opening: state.hookInvalid ? "attention" : state.hookOn ? "on" : null,
    visuals: state.visualsInvalid ? "attention" : state.visuals > 0 ? "on" : null,
    sound: state.audioActive ? "on" : null,
    brand: state.branded ? "on" : null,
  };
}
