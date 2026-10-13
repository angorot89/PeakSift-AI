export type StatusTone = "neutral" | "processing" | "success" | "warning" | "danger" | "accent";

const tones: Record<StatusTone, { dot: string; text: string }> = {
  neutral: { dot: "bg-zinc-400", text: "text-muted" },
  processing: { dot: "bg-accent animate-pulse", text: "text-accent-soft" },
  success: { dot: "bg-success", text: "text-emerald-200" },
  warning: { dot: "bg-warning", text: "text-amber-200" },
  danger: { dot: "bg-danger", text: "text-rose-200" },
  accent: { dot: "bg-accent", text: "text-accent-soft" },
};

/** A small, restrained status label: a coloured dot plus words (never colour alone). */
export function StatusPill({ tone, children }: { tone: StatusTone; children: React.ReactNode }) {
  const t = tones[tone];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${t.text}`}
    >
      <span aria-hidden="true" className={`size-1.5 rounded-full ${t.dot}`} />
      {children}
    </span>
  );
}
