import { AlertTriangle, Check, Clock } from "lucide-react";
import type { StatusTone } from "@/lib/status";

export type { StatusTone } from "@/lib/status";

const tones: Record<StatusTone, { text: string; mark: "dot" | "pulse" | "check" | "alert" | "clock" }> = {
  neutral: { text: "text-muted", mark: "dot" },
  waiting: { text: "text-muted", mark: "clock" },
  processing: { text: "text-accent-soft", mark: "pulse" },
  success: { text: "text-emerald-200", mark: "check" },
  warning: { text: "text-amber-200", mark: "alert" },
  danger: { text: "text-rose-200", mark: "alert" },
  accent: { text: "text-accent-soft", mark: "dot" },
};

/** A small status label: a shape that differs by state plus words (never colour alone). */
export function StatusPill({ tone, children }: { tone: StatusTone; children: React.ReactNode }) {
  const t = tones[tone];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-caption font-medium whitespace-nowrap ${t.text}`}
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
