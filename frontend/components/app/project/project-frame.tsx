"use client";

import { FolderX } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { createContext, type ReactNode, useCallback, useContext } from "react";
import { EmptyState, ErrorState } from "@/components/app/states";
import { ButtonLink } from "@/components/ui/button-link";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { PROJECT_SECTIONS, projectHref, projectLocation } from "@/lib/navigation";
import { getProject, isProjectId, type Project } from "@/lib/projects";
import { useApi } from "@/lib/use-api";

type ProjectContextValue = { project: Project; reload: () => void };
const ProjectContext = createContext<ProjectContextValue | null>(null);

/** The project every page under /projects/[id] works in (loaded once, owner-checked by the API). */
export function useProject(): ProjectContextValue {
  const value = useContext(ProjectContext);
  if (!value) throw new Error("useProject outside a project");
  return value;
}

/** The project's sections as tabs: always visible, so the creator knows where they are. */
function ProjectTabs({ projectId, compact }: { projectId: string; compact: boolean }) {
  const pathname = usePathname();
  const location = projectLocation(pathname);
  return (
    <nav aria-label="Project sections" className="-mx-4 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:px-0">
      <ul className={`flex min-w-max gap-1 ${compact ? "" : "border-b border-border"}`}>
        {PROJECT_SECTIONS.map((section) => {
          const active = location?.section === section.key;
          const exact = active && !location?.clipId;
          return (
            <li key={section.key}>
              <Link
                href={projectHref(projectId, section.key)}
                aria-current={exact ? "page" : active ? "location" : undefined}
                className={`relative flex min-h-11 items-center px-3 text-sm transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent ${
                  active ? "font-medium text-foreground" : "text-muted hover:text-foreground"
                }`}
              >
                {section.label}
                {active ? (
                  <span aria-hidden="true" className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-accent" />
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/**
 * Every project page: the project's name and its sections. Inside one clip (the editor, Auto
 * Edit) the header is compact so the work keeps the space; the clip page has its own title.
 */
export function ProjectFrame({ children }: { children: ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const validId = isProjectId(id);
  const load = useCallback(() => {
    if (!validId) return Promise.reject(new ApiError(404, "Project not found"));
    return getProject(id);
  }, [id, validId]);
  const { data: project, error, loading, reload } = useApi(load);
  const inClip = !!projectLocation(pathname)?.clipId;

  if (loading && !project) {
    return (
      <div role="status" aria-label="Loading project">
        <Skeleton className="mb-4 h-8 w-64" />
        <Skeleton className="mb-8 h-11 w-full max-w-lg" />
        <Skeleton className="h-72 w-full rounded-2xl" />
      </div>
    );
  }
  if (error || !project) {
    const notFound = !validId || error === "Project not found";
    return notFound ? (
      <EmptyState
        icon={FolderX}
        title="Project not found"
        description="This project does not exist or you do not have access to it."
        action={
          <ButtonLink href="/projects" variant="secondary">
            Back to projects
          </ButtonLink>
        }
      />
    ) : (
      <ErrorState title="Project could not be loaded" message={error ?? "Project unavailable."} onRetry={reload} />
    );
  }

  return (
    <ProjectContext.Provider value={{ project, reload }}>
      {inClip ? (
        <div className="mb-6 flex flex-col gap-1 border-b border-border sm:flex-row sm:items-end sm:justify-between sm:gap-6">
          <Link
            href={projectHref(project.id)}
            className="min-h-11 truncate py-2.5 text-sm font-medium text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent sm:max-w-xs"
          >
            {project.name}
          </Link>
          <ProjectTabs projectId={project.id} compact />
        </div>
      ) : (
        <div className="mb-8">
          <p className="text-caption font-medium tracking-wide text-subtle uppercase">Project</p>
          <h1 className="mt-1 mb-4 text-page text-balance break-words">{project.name}</h1>
          <ProjectTabs projectId={project.id} compact={false} />
        </div>
      )}
      {children}
    </ProjectContext.Provider>
  );
}
