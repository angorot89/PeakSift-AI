import type { ReactNode } from "react";

type PageHeaderProps = {
  title: string;
  description?: string;
  action?: ReactNode;
  eyebrow?: ReactNode;
};

export function PageHeader({ title, description, action, eyebrow }: PageHeaderProps) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow ? <div className="mb-2 text-sm text-muted">{eyebrow}</div> : null}
        <h1 className="text-2xl font-semibold tracking-tight break-words sm:text-3xl">{title}</h1>
        {description ? <p className="mt-1.5 text-sm text-muted">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
