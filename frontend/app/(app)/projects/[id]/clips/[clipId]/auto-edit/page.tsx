import type { Metadata } from "next";
import { Suspense } from "react";
import { AutoEditView } from "@/components/app/auto-edit-view";

export const metadata: Metadata = { title: "Create a Short" };

export default function AutoEditPage() {
  // useSearchParams ("start a new draft") needs a Suspense boundary for static rendering.
  return (
    <Suspense>
      <AutoEditView />
    </Suspense>
  );
}
