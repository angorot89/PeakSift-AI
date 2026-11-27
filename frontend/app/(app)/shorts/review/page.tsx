import type { Metadata } from "next";
import { ReviewQueueView } from "@/components/app/shorts/review-queue-view";

export const metadata: Metadata = { title: "Review & post" };

export default function ReviewPage() {
  return <ReviewQueueView />;
}
