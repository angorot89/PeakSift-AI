import type { Metadata } from "next";
import { BrandStudioView } from "@/components/app/brand/brand-studio-view";
import { TemplateLibrary } from "@/components/app/brand/template-library";

export const metadata: Metadata = { title: "Brand Studio" };

export default function BrandStudioPage() {
  return <BrandStudioView templates={<TemplateLibrary />} />;
}
