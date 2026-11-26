"use client";

import { FolderPlus, Plus } from "lucide-react";
import { PageHeader } from "@/components/app/page-header";
import { ProjectList } from "@/components/app/project-list";
import { EmptyState, ErrorState } from "@/components/app/states";
import { ButtonLink } from "@/components/ui/button-link";
import { Skeleton } from "@/components/ui/skeleton";
import { listProjects } from "@/lib/projects";
import { useApi } from "@/lib/use-api";

export function ProjectsView() {
  const { data: projects, error, loading, reload } = useApi(listProjects);

  return (
    <>
      <PageHeader
        title="Projects"
        description="Every long-form recording you are turning into clips."
        action={
          <ButtonLink href="/projects/new">
            <Plus aria-hidden="true" />
            New project
          </ButtonLink>
        }
      />

      {loading ? (
        <div role="status" aria-label="Loading projects" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-[76px] rounded-block" />
          ))}
        </div>
      ) : error ? (
        <ErrorState title="Projects could not be loaded" message={error} onRetry={reload} />
      ) : projects && projects.length > 0 ? (
        <ProjectList projects={projects} />
      ) : (
        <EmptyState
          icon={FolderPlus}
          title="No projects yet"
          description="Create a project for each stream, podcast or recording you want to clip."
          action={<ButtonLink href="/projects/new">Create your first project</ButtonLink>}
        />
      )}
    </>
  );
}
