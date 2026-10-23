import type { Metadata } from "next";
import { CreateShortView } from "@/components/app/create/create-short-view";

export const metadata: Metadata = { title: "Create a Short" };

export default function CreateShortPage() {
  return <CreateShortView />;
}
