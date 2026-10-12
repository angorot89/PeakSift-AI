import type { Metadata } from "next";
import { ProjectDetailView } from "@/components/app/project-detail-view";

export const metadata: Metadata = { title: "Project" };

export default function ProjectDetailPage() {
  return <ProjectDetailView />;
}
