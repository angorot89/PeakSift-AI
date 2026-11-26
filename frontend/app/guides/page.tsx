import { ArrowRight, Clock } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { ClosingCta } from "@/components/landing/closing-cta";
import { GUIDES } from "@/components/landing/content";
import { PageHero, SiteShell } from "@/components/landing/page-blocks";
import { Reveal } from "@/components/landing/reveal";

export const metadata: Metadata = {
  title: "Guides",
  description: "Step-by-step guides to getting the most out of PeakSift.",
};

export default function GuidesPage() {
  return (
    <SiteShell>
      <PageHero
        trail={[{ label: "Guides" }]}
        title="Guides"
        lead="Short, step-by-step guides — from your first upload to a week of scheduled Shorts."
        cta={null}
      />
      <section className="px-6 py-20">
        <ul className="mx-auto grid max-w-6xl gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {GUIDES.map((guide, i) => (
            <Reveal as="li" key={guide.slug} delay={(i % 3) * 80}>
              <Link
                href={`/guides/${guide.slug}`}
                className="group flex h-full flex-col overflow-hidden rounded-card border border-border bg-surface transition-[transform,box-shadow] duration-200 hover:-translate-y-1 hover:shadow-[0_18px_40px_-20px_rgb(14_18_34/0.35)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <span className="flex aspect-[16/7] items-end bg-[linear-gradient(140deg,#3d5afe,#6f4bff)] p-5">
                  <span className="font-display text-2xl leading-tight font-extrabold text-balance text-white">{guide.title}</span>
                </span>
                <span className="flex flex-1 flex-col p-5">
                  <span className="flex items-center gap-1.5 text-small text-subtle">
                    <Clock aria-hidden="true" className="size-3.5" />
                    {guide.minutes} min read
                  </span>
                  <span className="mt-2 flex-1 text-muted">{guide.summary}</span>
                  <span className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-accent-soft">
                    Read the guide
                    <ArrowRight aria-hidden="true" className="size-4 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </span>
              </Link>
            </Reveal>
          ))}
        </ul>
      </section>
      <ClosingCta />
    </SiteShell>
  );
}
