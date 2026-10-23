// Human status language (no React): what a creator reads instead of a job's internal state.
// Waiting · Processing (or the specific step, when that says more) · Ready · Needs attention.

export type StatusTone = "neutral" | "waiting" | "processing" | "success" | "warning" | "danger" | "accent";

const PRESENTATION: Record<string, { label: string; tone: StatusTone }> = {
  // waiting for a worker
  queued: { label: "Waiting", tone: "waiting" },
  uploaded: { label: "Processing", tone: "processing" },
  // working: the specific step when a creator would recognise it
  processing_metadata: { label: "Processing", tone: "processing" },
  extracting_audio: { label: "Preparing audio", tone: "processing" },
  transcribing: { label: "Transcribing", tone: "processing" },
  preparing_transcript: { label: "Reading the transcript", tone: "processing" },
  analyzing: { label: "Finding moments", tone: "processing" },
  validating: { label: "Checking", tone: "processing" },
  ranking: { label: "Ranking", tone: "processing" },
  rendering: { label: "Rendering", tone: "processing" },
  syncing: { label: "Updating", tone: "processing" },
  // done
  ready: { label: "Ready", tone: "success" },
  completed: { label: "Ready", tone: "success" },
  // needs the creator
  failed: { label: "Needs attention", tone: "danger" },
};

/** The label and tone of an internal status; a job that stopped reporting needs attention. */
export function humanStatus(status: string, stale = false): { label: string; tone: StatusTone } {
  if (stale) return { label: "Needs attention", tone: "warning" };
  return PRESENTATION[status] ?? { label: "Processing", tone: "processing" };
}
