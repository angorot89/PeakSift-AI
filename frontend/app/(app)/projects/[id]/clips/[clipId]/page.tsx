import type { Metadata } from "next";
import { ShortEditorView } from "@/components/app/short-editor-view";

export const metadata: Metadata = { title: "Edit Short" };

export default function ShortEditorPage() {
  return <ShortEditorView />;
}
