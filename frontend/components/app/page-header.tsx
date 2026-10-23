import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

type PageHeaderProps = {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  /** A back link (href + label) rendered above the title. */
  back?: { href: string; label: string };
  /** Extra content under the title row (e.g. the workflow stepper). */
  children?: ReactNode;
};

/** Page title row: one clear title, an optional back link, one primary action. */
export function PageHeader({ title, description, action, back, children }: PageHeaderProps) {
  return (
    <div className="mb-8">
      {back ? (
        <Link
          href={back.href}
          className="-ml-1 mb-2 inline-flex min-h-11 items-center gap-1 rounded-md px-1 text-sm text-muted transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <ChevronLeft aria-hidden="true" className="size-4" />
          {back.label}
        </Link>
      ) : null}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-page text-balance break-words">{title}</h1>
          {description ? <p className="mt-1.5 text-sm text-muted">{description}</p> : null}
        </div>
        {action ? <div className="flex shrink-0 flex-wrap gap-2">{action}</div> : null}
      </div>
      {children}
    </div>
  );
}
