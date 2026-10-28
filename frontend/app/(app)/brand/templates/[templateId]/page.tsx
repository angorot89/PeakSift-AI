import type { Metadata } from "next";
import { TemplateBuilderView } from "@/components/app/brand/template-builder-view";

export const metadata: Metadata = { title: "Template" };

export default async function TemplatePage({ params }: { params: Promise<{ templateId: string }> }) {
  const { templateId } = await params;
  return <TemplateBuilderView templateId={templateId} />;
}
