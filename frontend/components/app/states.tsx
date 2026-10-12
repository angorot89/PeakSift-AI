import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 text-sm text-muted">
      <span
        aria-hidden="true"
        className="size-4 animate-spin rounded-full border-2 border-white/15 border-t-accent"
      />
      {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-4 rounded-2xl border border-rose-500/30 bg-rose-500/10 p-6 sm:flex-row sm:items-center sm:justify-between"
    >
      <p className="text-sm text-rose-200">{message}</p>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-white/15 px-6 py-14 text-center">
      <h3 className="font-medium text-foreground">{title}</h3>
      <p className="mx-auto mt-2 max-w-sm text-sm text-muted">{description}</p>
      {action ? <div className="mt-6 flex justify-center">{action}</div> : null}
    </div>
  );
}
