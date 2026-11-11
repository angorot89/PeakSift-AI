import type { Metadata } from "next";
import { ShortDetailView } from "@/components/app/shorts/short-detail-view";

export const metadata: Metadata = { title: "Short" };

export default function ShortPage() {
  return <ShortDetailView />;
}
