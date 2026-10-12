type Tone = "neutral" | "accent" | "success" | "danger";

const presentation: Record<string, { label: string; tone: Tone }> = {
  // projects
  created: { label: "Created", tone: "accent" },
  // videos
  uploaded: { label: "Uploaded", tone: "neutral" },
  processing_metadata: { label: "Processing", tone: "accent" },
  ready: { label: "Ready", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  // transcriptions
  queued: { label: "Queued", tone: "neutral" },
  extracting_audio: { label: "Preparing audio", tone: "accent" },
  transcribing: { label: "Transcribing", tone: "accent" },
  completed: { label: "Completed", tone: "success" },
};

const dot: Record<Tone, string> = {
  neutral: "bg-zinc-400",
  accent: "bg-accent",
  success: "bg-emerald-400",
  danger: "bg-rose-400",
};

export function StatusBadge({ status }: { status: string }) {
  const { label, tone } = presentation[status] ?? { label: status, tone: "neutral" as Tone };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white/[0.03] px-2.5 py-0.5 text-xs font-medium text-muted">
      <span aria-hidden="true" className={`size-1.5 rounded-full ${dot[tone]}`} />
      {label}
    </span>
  );
}
