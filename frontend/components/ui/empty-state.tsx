import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

/** A concise next-step prompt: icon, one line of title, one line of guidance, one action. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  compact = false,
}: {
  icon?: LucideIcon;
  title: string;
  description: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={`flex flex-col items-center rounded-xl border border-dashed border-border-strong text-center ${
        compact ? "px-5 py-8" : "px-6 py-12"
      }`}
    >
      {Icon ? (
        <span className="mb-3 flex size-10 items-center justify-center rounded-xl bg-surface-3 text-muted">
          <Icon aria-hidden="true" className="size-5" />
        </span>
      ) : null}
      <h3 className="text-title font-medium text-foreground">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-pretty text-muted">{description}</p>
      {action ? <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  );
}
