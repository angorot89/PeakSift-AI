import { AlertTriangle } from "lucide-react";
import { ClosingCta } from "@/components/landing/closing-cta";
import { Breadcrumbs, SiteShell } from "@/components/landing/page-blocks";

export type LegalSection = { heading: string; body: string[] };

const anchor = (heading: string) => heading.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

/**
 * A legal document page: title band, a clear "draft" notice, a table of contents and numbered
 * sections. Text in [brackets] is a placeholder the company must fill in.
 */
export function LegalPage({ title, updated, intro, sections }: { title: string; updated: string; intro: string; sections: LegalSection[] }) {
  return (
    <SiteShell>
      <section className="hero-band relative -mt-[4.75rem] px-6 pt-32 pb-14 sm:pt-36">
        <div className="mx-auto max-w-3xl text-center">
          <Breadcrumbs trail={[{ label: title }]} />
          <h1 className="text-4xl font-extrabold tracking-tight text-white sm:text-5xl">{title}</h1>
          <p className="mt-3 text-white/90">Last updated {updated}</p>
        </div>
      </section>
      <div className="mx-auto max-w-6xl px-6 pt-10">
        <div role="note" className="flex gap-3 rounded-card border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-900">
          <AlertTriangle aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
          <p>
            <strong>Draft for legal review.</strong> This document describes how PeakSift works today. It has not yet been
            reviewed by a lawyer and is not in force; text in [brackets] is still to be completed.
          </p>
        </div>
      </div>
      <div className="mx-auto grid max-w-6xl gap-12 px-6 py-12 lg:grid-cols-[15rem_1fr]">
        <nav aria-label="Contents" className="hidden lg:block">
          <div className="sticky top-28">
            <p className="text-small font-semibold text-subtle">Contents</p>
            <ol className="mt-3 space-y-1 border-l border-border">
              {sections.map((section, i) => (
                <li key={section.heading}>
                  <a href={`#${anchor(section.heading)}`} className="-ml-px block border-l-2 border-transparent py-1.5 pl-4 text-sm text-muted hover:border-accent hover:text-foreground">
                    {i + 1}. {section.heading}
                  </a>
                </li>
              ))}
            </ol>
          </div>
        </nav>
        <article className="max-w-3xl">
          <p className="text-lg leading-relaxed text-muted">{intro}</p>
          {sections.map((section, i) => (
            <section key={section.heading} id={anchor(section.heading)} className="mt-10 scroll-mt-28">
              <h2 className="text-2xl font-extrabold tracking-tight">
                {i + 1}. {section.heading}
              </h2>
              {section.body.map((paragraph) => (
                <p key={paragraph.slice(0, 32)} className="mt-3 leading-relaxed text-pretty text-muted">
                  {paragraph}
                </p>
              ))}
            </section>
          ))}
        </article>
      </div>
      <ClosingCta />
    </SiteShell>
  );
}
