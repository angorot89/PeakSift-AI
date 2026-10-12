"use client";

import Link from "next/link";
import { PageHeader } from "@/components/app/page-header";
import { ProjectList } from "@/components/app/project-list";
import { EmptyState, ErrorState, LoadingState } from "@/components/app/states";
import { useAuth } from "@/components/auth/auth-provider";
import { ButtonLink } from "@/components/ui/button-link";
import { listProjects } from "@/lib/projects";
import { useApi } from "@/lib/use-api";

const RECENT_LIMIT = 5;

function StatCard({ label, value, note }: { label: string; value: number | string; note?: string }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-2 text-4xl font-semibold tracking-tight">{value}</p>
      {note ? <p className="mt-2 text-xs text-subtle">{note}</p> : null}
    </div>
  );
}

export function DashboardView() {
  const { user } = useAuth();
  const { data: projects, error, loading, reload } = useApi(listProjects);

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={user ? `Signed in as ${user.email}` : undefined}
        action={<ButtonLink href="/projects/new">Create Project</ButtonLink>}
      />

      <section aria-labelledby="overview-heading">
        <h2 id="overview-heading" className="sr-only">
          Overview
        </h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <StatCard label="Projects" value={projects ? projects.length : "–"} />
          <StatCard label="Videos" value="–" note="Upload a source video from a project page." />
          <StatCard label="Clips Found" value={0} note="AI clip detection arrives in Milestone 4." />
        </div>
      </section>

      <section aria-labelledby="recent-heading" className="mt-10">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="recent-heading" className="text-lg font-medium">
            Recent Projects
          </h2>
          {projects && projects.length > RECENT_LIMIT ? (
            <Link href="/projects" className="text-sm text-muted hover:text-foreground">
              View all
            </Link>
          ) : null}
        </div>

        {loading ? (
          <LoadingState label="Loading projects…" />
        ) : error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : projects && projects.length > 0 ? (
          <ProjectList projects={projects.slice(0, RECENT_LIMIT)} />
        ) : (
          <EmptyState
            title="No projects yet"
            description="A project holds one long-form recording and the clips you make from it. Create your first one to get started."
            action={<ButtonLink href="/projects/new">Create Project</ButtonLink>}
          />
        )}
      </section>
    </>
  );
}
