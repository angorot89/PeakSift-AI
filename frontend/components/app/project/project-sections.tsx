"use client";

import { BarChart3, Clapperboard, Film, Images, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { AnalyticsView } from "@/components/app/analytics-view";
import { DeleteProject } from "@/components/app/delete-project";
import { useProject } from "@/components/app/project/project-frame";
import { ClipsSection, SourceSection } from "@/components/app/source-video";
import { VisualLibrary } from "@/components/app/visual-library";
import { projectHref, type ProjectSection } from "@/lib/navigation";

const HUB: { section: ProjectSection; title: string; description: string; icon: LucideIcon }[] = [
  { section: "source", title: "Source", description: "The long recording and its transcript.", icon: Film },
  { section: "clips", title: "Clips", description: "The best moments, the clips made from them and their shorts.", icon: Clapperboard },
  { section: "assets", title: "Assets", description: "Your images and B-roll for this project.", icon: Images },
  { section: "analytics", title: "Analytics", description: "How the shorts you published are doing.", icon: BarChart3 },
];

export function ProjectOverviewPage() {
  const { project } = useProject();
  return (
    <div className="space-y-10">
      <ul className="grid gap-3 sm:grid-cols-2">
        {HUB.map((item) => (
          <li key={item.section}>
            <Link
              href={projectHref(project.id, item.section)}
              className="flex h-full gap-3 rounded-2xl border border-border bg-surface p-4 transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-3 text-accent-soft">
                <item.icon aria-hidden="true" className="size-[18px]" />
              </span>
              <span>
                <span className="block text-title">{item.title}</span>
                <span className="mt-0.5 block text-sm text-muted">{item.description}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
      <DeleteProject project={project} />
    </div>
  );
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
