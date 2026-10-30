import { AlertTriangle, Check, Clock } from "lucide-react";
import type { StatusTone } from "@/lib/status";

export type { StatusTone } from "@/lib/status";

const tones: Record<StatusTone, { text: string; tint: string; mark: "dot" | "pulse" | "check" | "alert" | "clock" }> = {
  neutral: { text: "text-muted", tint: "border-border bg-surface-2", mark: "dot" },
  waiting: { text: "text-muted", tint: "border-border bg-surface-2", mark: "clock" },
  processing: { text: "text-violet-200", tint: "border-violet/30 bg-violet/10", mark: "pulse" },
  success: { text: "text-emerald-200", tint: "border-success/30 bg-success/10", mark: "check" },
  warning: { text: "text-amber-200", tint: "border-warning/30 bg-warning/10", mark: "alert" },
  danger: { text: "text-rose-200", tint: "border-danger/35 bg-danger/10", mark: "alert" },
  accent: { text: "text-accent-soft", tint: "border-accent/35 bg-accent/10", mark: "dot" },
  info: { text: "text-sky-200", tint: "border-info/30 bg-info/10", mark: "dot" },
};

/** A small status label: a shape that differs by state plus words (never colour alone).
 * `overlay` sits on a thumbnail: an opaque dark chip that stays readable on any frame. */
export function StatusPill({ tone, overlay = false, children }: { tone: StatusTone; overlay?: boolean; children: React.ReactNode }) {
  const t = tones[tone];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-caption font-medium whitespace-nowrap ${t.text} ${
        overlay ? "border-white/10 bg-black/75 backdrop-blur-sm" : t.tint
      }`}
    >
      {t.mark === "check" ? (
        <Check aria-hidden="true" className="size-3" strokeWidth={3} />
      ) : t.mark === "alert" ? (
        <AlertTriangle aria-hidden="true" className="size-3" />
      ) : t.mark === "clock" ? (
        <Clock aria-hidden="true" className="size-3" />
      ) : (
        <span aria-hidden="true" className={`size-1.5 rounded-full bg-current ${t.mark === "pulse" ? "animate-pulse" : ""}`} />
      )}
      {children}
    </span>
  );
}
