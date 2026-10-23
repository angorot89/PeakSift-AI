import type { ReactNode } from "react";

/** A section's title row inside a page: a heading, one line of context, and its actions. */
export function SectionHeader({
  id,
  title,
  description,
  actions,
  as: Heading = "h2",
}: {
  id?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  as?: "h2" | "h3";
}) {
  return (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <Heading id={id} className={Heading === "h2" ? "text-section" : "text-title"}>
          {title}
        </Heading>
        {description ? <p className="mt-1 text-sm text-pretty text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
