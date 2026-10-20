import type { Metadata } from "next";
import { AutoEditView } from "@/components/app/auto-edit-view";

export const metadata: Metadata = { title: "Auto Edit" };

export default function AutoEditPage() {
  return <AutoEditView />;
}
