import type { Metadata } from "next";
import { Suspense } from "react";
import { NewProjectForm } from "@/components/app/new-project-form";

export const metadata: Metadata = { title: "New project" };

export default function NewProjectPage() {
  // useSearchParams (?market=) needs a Suspense boundary for static rendering.
  return (
    <Suspense>
      <NewProjectForm />
    </Suspense>
  );
}
