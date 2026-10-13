"use client";

import { FolderX } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback } from "react";
import { PageHeader } from "@/components/app/page-header";
import { ProjectWorkspace } from "@/components/app/source-video";
import { WorkflowProvider, WorkflowStepper } from "@/components/app/project-workflow";
import { EmptyState, ErrorState } from "@/components/app/states";
import { ButtonLink } from "@/components/ui/button-link";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { getProject, isProjectId } from "@/lib/projects";
import { useApi } from "@/lib/use-api";

const back = { href: "/projects", label: "Projects" };

export function ProjectDetailView() {
  const { id } = useParams<{ id: string }>();
  const validId = isProjectId(id);

  const load = useCallback(() => {
    if (!validId) return Promise.reject(new ApiError(404, "Project not found"));
    return getProject(id);
  }, [id, validId]);
  const { data: project, error, loading, reload } = useApi(load);

  if (loading) {
    return (
      <div role="status" aria-label="Loading project">
        <Skeleton className="mb-3 h-4 w-20" />
        <Skeleton className="mb-8 h-8 w-64" />
        <Skeleton className="mb-6 h-14 w-full rounded-2xl" />
        <Skeleton className="h-80 w-full rounded-2xl" />
      </div>
    );
  }

  if (error || !project) {
    const notFound = !validId || error === "Project not found";
    return (
      <>
        <PageHeader back={back} title="Project" />
        {notFound ? (
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
        )}
      </>
    );
  }

  return (
    <WorkflowProvider>
      <PageHeader back={back} title={project.name} description={`Created ${formatDate(project.created_at)}`}>
        <WorkflowStepper />
      </PageHeader>
      <ProjectWorkspace projectId={project.id} />
    </WorkflowProvider>
  );
}
