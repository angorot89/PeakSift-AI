"use client";

import { AnalyticsView } from "@/components/app/analytics-view";
import { useProject } from "@/components/app/project/project-frame";
import { ProjectOverview } from "@/components/app/project/project-overview";
import { ClipsSection, SourceSection } from "@/components/app/source-video";
import { VisualLibrary } from "@/components/app/visual-library";

export function ProjectOverviewPage() {
  return <ProjectOverview />;
}

export function ProjectSourcePage() {
  const { project } = useProject();
  return <SourceSection projectId={project.id} />;
}

export function ProjectClipsPage() {
  const { project } = useProject();
  return <ClipsSection projectId={project.id} />;
}

export function ProjectAssetsPage() {
  const { project } = useProject();
  return <VisualLibrary projectId={project.id} />;
}

export function ProjectAnalyticsPage() {
  const { project } = useProject();
  return <AnalyticsView projectId={project.id} />;
}
