import type { Metadata } from "next";
import { ProjectClipsPage } from "@/components/app/project/project-sections";

export const metadata: Metadata = { title: "Moments" };

export default function Page() {
  return <ProjectClipsPage />;
}
