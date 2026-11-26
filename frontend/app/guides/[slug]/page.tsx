import { ArrowLeft, ArrowRight, Clock } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ClosingCta } from "@/components/landing/closing-cta";
import { GUIDES, guideBySlug } from "@/components/landing/content";
import { Breadcrumbs, SiteShell } from "@/components/landing/page-blocks";

type Props = { params: Promise<{ slug: string }> };

// Every page here is prerendered from generateStaticParams, so waiting on the slug never
// blocks a real navigation.
export const instant = false;

export function generateStaticParams() {
  return GUIDES.map((guide) => ({ slug: guide.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const guide = guideBySlug((await params).slug);
  return guide ? { title: guide.title, description: guide.summary } : {};
}

const anchor = (heading: string) => heading.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

/** One guide: a title band, a table of contents beside numbered steps, and the next guide. */
export default async function GuidePage({ params }: Props) {
  const guide = guideBySlug((await params).slug);
  if (!guide) notFound();
  const index = GUIDES.indexOf(guide);
  const next = GUIDES[(index + 1) % GUIDES.length];
  return (
    <SiteShell>
      <section className="hero-band relative -mt-[4.75rem] px-6 pt-32 pb-16 sm:pt-36">
        <div className="mx-auto max-w-3xl text-center">
          <Breadcrumbs trail={[{ href: "/guides", label: "Guides" }, { label: guide.title }]} />
          <h1 className="text-4xl leading-tight font-extrabold tracking-tight text-balance text-white sm:text-5xl">{guide.title}</h1>
          <p className="mt-4 text-lg text-white">{guide.summary}</p>
          <p className="mt-3 inline-flex items-center gap-1.5 text-small text-white/85">
            <Clock aria-hidden="true" className="size-3.5" />
            {guide.minutes} min read
          </p>
        </div>
      </section>
      <div className="mx-auto grid max-w-6xl gap-12 px-6 py-16 lg:grid-cols-[14rem_1fr]">
        <nav aria-label="In this guide" className="hidden lg:block">
          <div className="sticky top-28">
            <p className="text-small font-semibold text-subtle">In this guide</p>
            <ol className="mt-3 space-y-1 border-l border-border">
              {guide.sections.map((section) => (
                <li key={section.heading}>
                  <a href={`#${anchor(section.heading)}`} className="-ml-px block border-l-2 border-transparent py-1.5 pl-4 text-sm text-muted hover:border-accent hover:text-foreground">
                    {section.heading}
                  </a>
                </li>
              ))}
            </ol>
          </div>
        </nav>
        <article className="max-w-2xl">
          <ol className="space-y-12">
            {guide.sections.map((section, i) => (
              <li key={section.heading} id={anchor(section.heading)} className="scroll-mt-28">
                <h2 className="flex items-center gap-3 text-2xl font-extrabold tracking-tight sm:text-3xl">
                  <span className="tabular flex size-9 shrink-0 items-center justify-center rounded-full bg-accent-fill font-display text-base font-extrabold text-white">
                    {i + 1}
                  </span>
                  {section.heading}
                </h2>
                {section.body.map((paragraph) => (
                  <p key={paragraph.slice(0, 24)} className="mt-4 text-lg leading-relaxed text-pretty text-muted">
                    {paragraph}
                  </p>
                ))}
              </li>
            ))}
          </ol>
          <div className="mt-16 flex flex-col gap-3 border-t border-border pt-8 sm:flex-row sm:justify-between">
            <Link href="/guides" className="inline-flex min-h-11 items-center gap-2 font-semibold text-muted hover:text-foreground">
              <ArrowLeft aria-hidden="true" className="size-4" />
              All guides
            </Link>
            <Link href={`/guides/${next.slug}`} className="inline-flex min-h-11 items-center gap-2 font-semibold text-accent-soft hover:underline">
              Next: {next.title}
              <ArrowRight aria-hidden="true" className="size-4" />
            </Link>
          </div>
        </article>
      </div>
      <ClosingCta />
    </SiteShell>
  );
}
