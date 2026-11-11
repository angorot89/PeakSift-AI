import type { Metadata } from "next";
import { ShortsLibraryView } from "@/components/app/shorts/shorts-library-view";

export const metadata: Metadata = { title: "Shorts" };

export default function ShortsPage() {
  return <ShortsLibraryView />;
}
