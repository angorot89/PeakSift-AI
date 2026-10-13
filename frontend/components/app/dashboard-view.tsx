"use client";

import { FolderPlus, Plus } from "lucide-react";
import Link from "next/link";
import { PageHeader } from "@/components/app/page-header";
import { ProjectList } from "@/components/app/project-list";
import { EmptyState, ErrorState } from "@/components/app/states";
import { WORKFLOW_STEPS } from "@/components/app/workflow-steps";
import { ButtonLink } from "@/components/ui/button-link";
import { Skeleton } from "@/components/ui/skeleton";
import { listProjects } from "@/lib/projects";
import { useApi } from "@/lib/use-api";

const RECENT_LIMIT = 6;

/** A compact orientation strip: what PeakSift does, in the order a creator does it. */
function WorkflowGuide() {
  return (
    <section aria-labelledby="workflow-heading">
      <h2 id="workflow-heading" className="mb-3 text-sm font-medium text-muted">
        How a project works
      </h2>
      <ol className="grid gap-2 sm:grid-cols-5">
        {WORKFLOW_STEPS.map((step, index) => (
          <li
            key={step.key}
            className="flex items-center gap-3 rounded-xl border border-border bg-surface px-3 py-2.5 sm:flex-col sm:items-start sm:gap-2 sm:px-3.5 sm:py-3"
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-3 text-accent-soft">
              <step.icon aria-hidden="true" className="size-4" />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium text-foreground">
                <span className="tabular text-subtle">{index + 1}. </span>
                {step.label}
              </span>
              <span className="block text-xs text-subtle">{step.hint}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function DashboardView() {
  const { data: projects, error, loading, reload } = useApi(listProjects);

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Pick up a project or start a new one."
        action={
          <ButtonLink href="/projects/new">
            <Plus aria-hidden="true" />
            New project
          </ButtonLink>
        }
      />

      <section aria-labelledby="recent-heading" className="mb-10">
        <div className="mb-3 flex items-center justify-between">
          <h2 id="recent-heading" className="text-sm font-medium text-muted">
            Recent projects
          </h2>
          {projects && projects.length > RECENT_LIMIT ? (
            <Link href="/projects" className="text-sm text-muted hover:text-foreground">
              View all {projects.length}
            </Link>
          ) : null}
        </div>

        {loading ? (
          <div role="status" aria-label="Loading projects" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-[76px] rounded-xl" />
            ))}
          </div>
        ) : error ? (
          <ErrorState title="Projects could not be loaded" message={error} onRetry={reload} />
        ) : projects && projects.length > 0 ? (
          <ProjectList projects={projects.slice(0, RECENT_LIMIT)} />
        ) : (
          <EmptyState
            icon={FolderPlus}
            title="No projects yet"
            description="A project holds one long recording and every clip you make from it."
            action={<ButtonLink href="/projects/new">Create your first project</ButtonLink>}
          />
        )}
      </section>

      <WorkflowGuide />
    </>
  );
}
