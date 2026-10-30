import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { ShellSearch } from "@/components/app/shell-search";
import { PeakArt } from "@/components/ui/peak-art";

type PageHeaderProps = {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  /** A back link (href + label) rendered above the title. */
  back?: { href: string; label: string };
  /** "hero" for a destination's front page (Home, Analytics, Brand Studio): a larger title and
   * the decorative peak art. */
  size?: "page" | "hero";
  /** Extra content under the title row (e.g. the workflow stepper). */
  children?: ReactNode;
};

/** Page title row: one clear title, an optional back link; on large screens the search field and
 * the page's one primary action sit at the top right. */
export function PageHeader({ title, description, action, back, size = "page", children }: PageHeaderProps) {
  return (
    <header className="relative mb-8">
      {size === "hero" ? <PeakArt /> : null}
      <div className="relative grid gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
        <div className="min-w-0">
          {back ? (
            <Link
              href={back.href}
              className="-ml-1 mb-1 inline-flex min-h-11 items-center gap-1 rounded-md px-1 text-sm text-muted transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <ChevronLeft aria-hidden="true" className="size-4" />
              {back.label}
            </Link>
          ) : null}
          <h1 className={`text-balance break-words ${size === "hero" ? "text-page sm:text-display" : "text-page"}`}>{title}</h1>
          {description ? (
            <p className={`mt-2 max-w-2xl text-muted ${size === "hero" ? "text-lead sm:text-lg" : "text-sm"}`}>{description}</p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          <ShellSearch />
          {action}
        </div>
      </div>
      {children ? <div className="relative">{children}</div> : null}
    </header>
  );
}
