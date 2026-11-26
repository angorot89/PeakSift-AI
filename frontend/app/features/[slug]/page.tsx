import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ClosingCta } from "@/components/landing/closing-cta";
import { TOOLS, toolBySlug } from "@/components/landing/content";
import { Explainer, FaqList, FeatureGrid, PageHero, SiteShell, Steps, ToolCards } from "@/components/landing/page-blocks";
import { ShortsMarquee } from "@/components/landing/shorts-marquee";

type Props = { params: Promise<{ slug: string }> };

// Every page here is prerendered from generateStaticParams, so waiting on the slug never
// blocks a real navigation.
export const instant = false;

export function generateStaticParams() {
  return TOOLS.map((tool) => ({ slug: tool.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const tool = toolBySlug((await params).slug);
  return tool ? { title: tool.name, description: tool.summary } : {};
}

/** One tool's page: what it does, how it works, the details, and its questions. */
export default async function ToolPage({ params }: Props) {
  const tool = toolBySlug((await params).slug);
  if (!tool) notFound();
  return (
    <SiteShell>
      <PageHero trail={[{ href: "/features", label: "All tools" }, { label: tool.name }]} title={tool.title} lead={tool.lead} visual={tool.visual} />
      <FeatureGrid title={`What ${tool.name} does`} lead={tool.summary} items={tool.features} />
      <Steps title={`How ${tool.name} works`} steps={tool.steps} />
      <Explainer title={`Why ${tool.name}`} paragraphs={tool.explainer} visual={tool.visual} />
      <section className="px-6 pb-8">
        <div className="mx-auto flex max-w-4xl flex-wrap justify-center gap-2">
          <span className="mr-1 self-center text-small font-semibold text-subtle">More tools</span>
          {TOOLS.filter((other) => other.slug !== tool.slug).map((other) => (
            <Link
              key={other.slug}
              href={`/features/${other.slug}`}
              className="inline-flex min-h-9 items-center rounded-control border border-border bg-surface px-3 text-small font-medium text-foreground transition-colors hover:border-accent/40 hover:text-accent-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              {other.name}
            </Link>
          ))}
        </div>
      </section>
      <ToolCards title="Works well with" slugs={tool.related} />
      <ShortsMarquee />
      <FaqList items={tool.faq} />
      <ClosingCta />
    </SiteShell>
  );
}
