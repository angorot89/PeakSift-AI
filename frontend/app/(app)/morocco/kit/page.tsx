import type { Metadata } from "next";
import { Suspense } from "react";
import { CreatorKitView } from "@/components/app/morocco/morocco-views";

export const metadata: Metadata = { title: "Morocco Creator Kit" };

export default function Page() {
  // useSearchParams (the open tab) needs a Suspense boundary for static rendering.
  return (
    <Suspense>
      <CreatorKitView />
    </Suspense>
  );
}
