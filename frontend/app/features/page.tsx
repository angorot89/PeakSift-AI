import type { Metadata } from "next";
import { ClosingCta } from "@/components/landing/closing-cta";
import { TOOLS } from "@/components/landing/content";
import { PageHero, SiteShell, ToolCards } from "@/components/landing/page-blocks";
import { ShortsMarquee } from "@/components/landing/shorts-marquee";

export const metadata: Metadata = {
  title: "All tools",
  description: "Every PeakSift tool, from finding the moment to posting the Short.",
};

export default function FeaturesPage() {
  return (
    <SiteShell>
      <PageHero
        trail={[{ label: "All tools" }]}
        title="Every tool you need, in one workspace"
        lead="From finding the moment to posting the Short — twelve tools that work together, so nothing has to be exported between apps."
        visual="auto-edit"
      />
      <ToolCards title="Explore the full toolkit" slugs={TOOLS.map((tool) => tool.slug)} />
      <ShortsMarquee />
      <ClosingCta />
    </SiteShell>
  );
}
