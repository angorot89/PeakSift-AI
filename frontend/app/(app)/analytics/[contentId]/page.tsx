import type { Metadata } from "next";
import { VideoAnalyticsView } from "@/components/app/video-analytics-view";

export const metadata: Metadata = { title: "Short analytics" };

export default function VideoAnalyticsPage() {
  return <VideoAnalyticsView />;
}
