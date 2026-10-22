import type { Metadata } from "next";
import { ProjectOverviewPage } from "@/components/app/project/project-sections";

export const metadata: Metadata = { title: "Project" };

export default function Page() {
  return <ProjectOverviewPage />;
}
