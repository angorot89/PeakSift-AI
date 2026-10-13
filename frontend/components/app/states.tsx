import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState as EmptyBlock } from "@/components/ui/empty-state";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Spinner } from "@/components/ui/progress";

/** Context-specific loading line ("Loading transcript…"), never a bare "Loading…". */
export function LoadingState({ label }: { label: string }) {
  return (
    <div role="status" className="flex items-center gap-2.5 py-1 text-sm text-muted">
      <Spinner />
      {label}
    </div>
  );
}

export function ErrorState({
  message,
  title = "Something went wrong",
  onRetry,
}: {
  message: string;
  title?: string;
  onRetry?: () => void;
}) {
  return (
    <InlineAlert
      title={title}
      action={
        onRetry ? (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Try again
          </Button>
        ) : undefined
      }
    >
      {message}
    </InlineAlert>
  );
}

export function EmptyState(props: {
  icon?: LucideIcon;
  title: string;
  description: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  return <EmptyBlock {...props} />;
}
