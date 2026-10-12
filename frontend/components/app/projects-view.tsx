"use client";

import { PageHeader } from "@/components/app/page-header";
import { ProjectList } from "@/components/app/project-list";
import { EmptyState, ErrorState, LoadingState } from "@/components/app/states";
import { ButtonLink } from "@/components/ui/button-link";
import { listProjects } from "@/lib/projects";
import { useApi } from "@/lib/use-api";

export function ProjectsView() {
  const { data: projects, error, loading, reload } = useApi(listProjects);

  return (
    <>
      <PageHeader
        title="Projects"
        description="Every long-form recording you are turning into clips."
        action={<ButtonLink href="/projects/new">Create Project</ButtonLink>}
      />

      {loading ? (
        <LoadingState label="Loading projects…" />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : projects && projects.length > 0 ? (
        <ProjectList projects={projects} />
      ) : (
        <EmptyState
          title="No projects yet"
          description="Create a project for each stream, podcast or recording you want to clip."
          action={<ButtonLink href="/projects/new">Create Project</ButtonLink>}
        />
      )}
    </>
  );
}
