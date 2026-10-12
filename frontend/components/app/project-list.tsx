import Link from "next/link";
import { StatusBadge } from "@/components/app/status-badge";
import { formatDate } from "@/lib/format";
import type { Project } from "@/lib/projects";

export function ProjectList({ projects }: { projects: Project[] }) {
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface">
      {projects.map((project) => (
        <li key={project.id}>
          <Link
            href={`/projects/${project.id}`}
            className="flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-white/[0.03] focus-visible:bg-white/[0.03] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
          >
            <div className="min-w-0">
              <p className="truncate font-medium text-foreground">{project.name}</p>
              <p className="mt-0.5 text-xs text-muted">Created {formatDate(project.created_at)}</p>
            </div>
            <StatusBadge status={project.status} />
          </Link>
        </li>
      ))}
    </ul>
  );
}
