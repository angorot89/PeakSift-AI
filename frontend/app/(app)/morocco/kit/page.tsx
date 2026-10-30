import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { CreatorKitView } from "@/components/app/morocco/morocco-views";
import { moroccoPreviewEnabled } from "@/lib/morocco";

export const metadata: Metadata = { title: "Morocco Creator Kit" };

// A preview behind NEXT_PUBLIC_MOROCCO_MODE_PREVIEW: without it the page does not exist.
export default function Page() {
  if (!moroccoPreviewEnabled()) notFound();
  return <CreatorKitView />;
}
