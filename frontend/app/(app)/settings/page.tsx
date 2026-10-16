import type { Metadata } from "next";
import { Suspense } from "react";
import { SettingsView } from "@/components/app/settings-view";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  // useSearchParams (the OAuth outcome) needs a Suspense boundary for static rendering.
  return (
    <Suspense>
      <SettingsView />
    </Suspense>
  );
}
