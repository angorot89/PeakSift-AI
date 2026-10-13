import { StatusPill, type StatusTone } from "@/components/ui/status-pill";

const presentation: Record<string, { label: string; tone: StatusTone }> = {
  // videos
  uploaded: { label: "Uploaded", tone: "neutral" },
  processing_metadata: { label: "Processing", tone: "processing" },
  ready: { label: "Ready", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  // background jobs
  queued: { label: "Queued", tone: "neutral" },
  extracting_audio: { label: "Preparing audio", tone: "processing" },
  transcribing: { label: "Transcribing", tone: "processing" },
  completed: { label: "Completed", tone: "success" },
  preparing_transcript: { label: "Preparing transcript", tone: "processing" },
  analyzing: { label: "Analyzing", tone: "processing" },
  validating: { label: "Validating", tone: "processing" },
  ranking: { label: "Ranking", tone: "processing" },
  rendering: { label: "Rendering", tone: "processing" },
};

export function StatusBadge({ status, stale = false }: { status: string; stale?: boolean }) {
  if (stale) return <StatusPill tone="warning">Stalled</StatusPill>;
  const { label, tone } = presentation[status] ?? { label: status, tone: "neutral" as StatusTone };
  return <StatusPill tone={tone}>{label}</StatusPill>;
}
