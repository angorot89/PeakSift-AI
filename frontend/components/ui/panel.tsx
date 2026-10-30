import type { ReactNode } from "react";

type PanelProps = {
  id?: string;
  /** Small step marker shown before the title (e.g. "1"), for workflow sections. */
  step?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  status?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
};

/** The standard section surface: one border, one radius, a clear header row. */
export function Panel({ id, step, title, description, status, actions, children, className = "" }: PanelProps) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section
      id={id}
      aria-labelledby={headingId}
      className={`scroll-mt-24 rounded-card border border-border bg-surface shadow-card ${className}`}
    >
      <header className="flex flex-col gap-3 border-b border-border px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="flex min-w-0 items-start gap-3">
          {step ? (
            <span
              aria-hidden="true"
              className="tabular mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-surface-3 text-xs font-semibold text-muted"
            >
              {step}
            </span>
          ) : null}
          <div className="min-w-0">
            <h2 id={headingId} className="text-title text-foreground">
              {title}
            </h2>
            {description ? <p className="mt-0.5 text-sm text-muted">{description}</p> : null}
          </div>
        </div>
        {status || actions ? (
          <div className={`flex shrink-0 flex-wrap items-center gap-2 ${step ? "pl-9 sm:pl-0" : ""}`}>
            {status}
            {actions}
          </div>
        ) : null}
      </header>
      <div className="px-4 py-5 sm:px-6">{children}</div>
    </section>
  );
}
