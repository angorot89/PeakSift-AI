import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ClosingCta } from "@/components/landing/closing-cta";
import { AUDIENCES, audienceBySlug } from "@/components/landing/content";
import { FaqList, FeatureGrid, PageHero, SiteShell, Steps, ToolCards } from "@/components/landing/page-blocks";
import { ShortsMarquee } from "@/components/landing/shorts-marquee";

type Props = { params: Promise<{ slug: string }> };

// Every page here is prerendered from generateStaticParams, so waiting on the slug never
// blocks a real navigation.
export const instant = false;

export function generateStaticParams() {
  return AUDIENCES.map((audience) => ({ slug: audience.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const audience = audienceBySlug((await params).slug);
  return audience ? { title: `For ${audience.name.toLowerCase()}`, description: audience.summary } : {};
}

/** PeakSift for one kind of creator. */
export default async function AudiencePage({ params }: Props) {
  const audience = audienceBySlug((await params).slug);
  if (!audience) notFound();
  return (
    <SiteShell>
      <PageHero trail={[{ href: "/#made-for", label: "Made for" }, { label: audience.name }]} title={audience.title} lead={audience.lead} visual={audience.visual} />
      <FeatureGrid title={`Why ${audience.name.toLowerCase()} use PeakSift`} items={audience.reasons} />
      <Steps title="Your workflow" steps={audience.steps} />
      <ToolCards title="The tools you'll use most" slugs={audience.tools} />
      <ShortsMarquee />
      <FaqList items={audience.faq} />
      <ClosingCta />
    </SiteShell>
  );
}
