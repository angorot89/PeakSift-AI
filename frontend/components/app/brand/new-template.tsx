"use client";

import { useSearchParams } from "next/navigation";
import { TemplateBuilderView } from "@/components/app/brand/template-builder-view";

/** A new template, optionally started from a style (`?start=punchy`). */
export function NewTemplate() {
  return <TemplateBuilderView start={useSearchParams().get("start")} />;
}
