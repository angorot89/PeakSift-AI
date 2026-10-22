import type { Metadata } from "next";
import { ProjectAnalyticsPage } from "@/components/app/project/project-sections";

export const metadata: Metadata = { title: "Project analytics" };

export default function Page() {
  return <ProjectAnalyticsPage />;
}
