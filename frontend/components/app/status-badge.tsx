import type { ProjectStatus } from "@/lib/projects";

const labels: Record<ProjectStatus, string> = {
  created: "Created",
};

export function StatusBadge({ status }: { status: ProjectStatus }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white/[0.03] px-2.5 py-0.5 text-xs font-medium text-muted">
      <span aria-hidden="true" className="size-1.5 rounded-full bg-accent" />
      {labels[status] ?? status}
    </span>
  );
}
