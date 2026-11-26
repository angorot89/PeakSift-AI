// Quick start (pure rules, no React): the name a dropped video gives its project, and the words
// for what PeakSift does next. Unit-tested with node --test. The server applies the same naming
// rule (backend/app/services/quick_start.py) when no name is sent.

export const QUICK_START_NAME_MAX = 200;
export const QUICK_START_FALLBACK_NAME = "New project";

/** `Friday_stream-2026.09.28.mp4` → `Friday stream 2026 09 28`. */
export function nameFromFile(filename: string): string {
  const base = filename.replace(/\\/g, "/").split("/").pop() ?? "";
  const dot = base.lastIndexOf(".");
  const stem = dot > 0 ? base.slice(0, dot) : base.replace(/^\./, "");
  const readable = stem
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/[\s_\-.]+/g, " ")
    .trim();
  return readable.slice(0, QUICK_START_NAME_MAX).trim() || QUICK_START_FALLBACK_NAME;
}

export type QuickStartOutcome = { video_status: string; transcription_started: boolean };

/** What to tell the creator once the upload has landed, before the project page takes over. */
export function quickStartNotice(outcome: QuickStartOutcome): string | null {
  if (outcome.video_status === "failed") return "That file couldn't be read as a video. Upload a different export in the project.";
  if (!outcome.transcription_started) return "Your video is in. Start the transcription from the project when you're ready.";
  return null;
}
