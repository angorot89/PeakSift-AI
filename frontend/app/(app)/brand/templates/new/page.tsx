import type { Metadata } from "next";
import { Suspense } from "react";
import { NewTemplate } from "@/components/app/brand/new-template";

export const metadata: Metadata = { title: "New template" };

export default function NewTemplatePage() {
  // useSearchParams (the starting style) needs a Suspense boundary for static rendering.
  return (
    <Suspense>
      <NewTemplate />
    </Suspense>
  );
}
