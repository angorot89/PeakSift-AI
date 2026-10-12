import type { Metadata } from "next";
import { NewProjectForm } from "@/components/app/new-project-form";

export const metadata: Metadata = { title: "New project" };

export default function NewProjectPage() {
  return <NewProjectForm />;
}
