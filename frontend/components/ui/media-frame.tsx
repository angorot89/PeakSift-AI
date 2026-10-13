import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

/**
 * One container for every video in the product, with a label saying *which* video it is
 * (source preview, generated clip, edited short) so they are never confused.
 */
export function MediaFrame({
  icon: Icon,
  label,
  meta,
  children,
  className = "",
}: {
  icon: LucideIcon;
  label: string;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <figure className={`min-w-0 ${className}`}>
      <figcaption className="mb-2 flex items-center justify-between gap-3 text-xs">
        <span className="inline-flex items-center gap-1.5 font-medium tracking-wide text-muted uppercase">
          <Icon aria-hidden="true" className="size-3.5" />
          {label}
        </span>
        {meta ? <span className="tabular truncate text-subtle">{meta}</span> : null}
      </figcaption>
      <div className="overflow-hidden rounded-xl border border-border bg-black">{children}</div>
    </figure>
  );
}
