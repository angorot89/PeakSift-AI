import type { Metadata } from "next";
import { ProjectSourcePage } from "@/components/app/project/project-sections";

export const metadata: Metadata = { title: "Source" };

export default function Page() {
  return <ProjectSourcePage />;
}
