"use client";

import { useParams } from "next/navigation";
import { useCallback } from "react";
import { PageHeader } from "@/components/app/page-header";
import { SourceVideo } from "@/components/app/source-video";
import { EmptyState, ErrorState, LoadingState } from "@/components/app/states";
import { StatusBadge } from "@/components/app/status-badge";
import { ButtonLink } from "@/components/ui/button-link";
import { ApiError } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { getProject, isProjectId } from "@/lib/projects";
import { useApi } from "@/lib/use-api";

function NotFound() {
  return (
    <EmptyState
      title="Project not found"
      description="This project does not exist or you do not have access to it."
      action={
        <ButtonLink href="/projects" variant="secondary">
          Back to projects
        </ButtonLink>
      }
    />
  );
}

export function ProjectDetailView() {
  const { id } = useParams<{ id: string }>();
  const validId = isProjectId(id);

  const load = useCallback(() => {
    if (!validId) return Promise.reject(new ApiError(404, "Project not found"));
    return getProject(id);
  }, [id, validId]);
  const { data: project, error, loading, reload } = useApi(load);

  const back = { href: "/projects", label: "Projects" };

  if (loading) {
    return (
      <>
        <PageHeader back={back} title="Project" />
        <LoadingState label="Loading project…" />
      </>
    );
  }

  if (error || !project) {
    const notFound = !validId || error === "Project not found";
    return (
      <>
        <PageHeader back={back} title="Project" />
        {notFound ? <NotFound /> : <ErrorState message={error ?? "Project unavailable."} onRetry={reload} />}
      </>
    );
  }

  return (
    <>
      <PageHeader
        back={back}
        title={project.name}
        action={<StatusBadge status={project.status} />}
      />

      <dl className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-2xl border border-border bg-surface p-5">
          <dt className="text-sm text-muted">Status</dt>
          <dd className="mt-1 font-medium capitalize">{project.status}</dd>
        </div>
        <div className="rounded-2xl border border-border bg-surface p-5">
          <dt className="text-sm text-muted">Created</dt>
          <dd className="mt-1 font-medium">{formatDate(project.created_at)}</dd>
        </div>
      </dl>

      <SourceVideo projectId={project.id} />
    </>
  );
}
