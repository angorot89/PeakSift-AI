import { ArrowUpRight, Folder } from "lucide-react";
import Link from "next/link";
import { formatDate } from "@/lib/format";
import type { Project } from "@/lib/projects";

/** Projects as scannable cards: name first, creation date as quiet metadata. */
export function ProjectList({ projects }: { projects: Project[] }) {
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {projects.map((project) => (
        <li key={project.id}>
          <Link
            href={`/projects/${project.id}`}
            className="group flex h-full items-start gap-3 rounded-block border border-border bg-surface p-4 transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <span className="flex size-9 shrink-0 items-center justify-center rounded-control bg-surface-3 text-muted transition-colors group-hover:text-accent-soft">
              <Folder aria-hidden="true" className="size-4" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="line-clamp-2 font-medium break-words text-foreground">{project.name}</span>
              <span className="mt-1 block text-xs text-subtle">Created {formatDate(project.created_at)}</span>
            </span>
            <ArrowUpRight
              aria-hidden="true"
              className="size-4 shrink-0 text-subtle transition-colors group-hover:text-foreground"
            />
          </Link>
        </li>
      ))}
    </ul>
  );
}
