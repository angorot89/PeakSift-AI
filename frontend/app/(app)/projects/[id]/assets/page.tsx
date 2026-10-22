import type { Metadata } from "next";
import { ProjectAssetsPage } from "@/components/app/project/project-sections";

export const metadata: Metadata = { title: "Assets" };

export default function Page() {
  return <ProjectAssetsPage />;
}
