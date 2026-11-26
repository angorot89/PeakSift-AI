import { ArrowRight, Check, ChevronDown, ChevronRight, Wand2 } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Announcement } from "@/components/landing/announcement";
import type { Faq } from "@/components/landing/content";
import { TOOLS } from "@/components/landing/content";
import { Reveal } from "@/components/landing/reveal";
import { ToolIcon } from "@/components/landing/tool-icon";
import { Visual, type VisualName } from "@/components/landing/visuals";
import { ButtonLink } from "@/components/ui/button-link";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

/** Every public page: light theme, announcement, floating navigation, footer. */
export function SiteShell({ children }: { children: ReactNode }) {
  return (
    <div className="theme-light flex flex-1 flex-col overflow-x-clip">
      <Announcement />
      <SiteHeader />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </div>
  );
}

/** "Website › Section › Page", for pages below the home page. */
export function Breadcrumbs({ trail }: { trail: { href?: string; label: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-6 flex justify-center">
      <ol className="flex flex-wrap items-center gap-1 text-small text-white/85">
        <li>
          <Link href="/" className="hover:text-white hover:underline">
            Home
          </Link>
        </li>
        {trail.map((crumb) => (
          <li key={crumb.label} className="flex items-center gap-1">
            <ChevronRight aria-hidden="true" className="size-3.5" />
            {crumb.href ? (
              <Link href={crumb.href} className="hover:text-white hover:underline">
                {crumb.label}
              </Link>
            ) : (
              <span aria-current="page" className="font-semibold text-white">
                {crumb.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** The blue band every page opens on: breadcrumbs, a title, a lead, the call to action and a picture. */
export function PageHero({
  trail,
  title,
  lead,
  cta = "Start clipping",
  visual,
  children,
}: {
  trail: { href?: string; label: string }[];
  title: string;
  lead: string;
  cta?: string | null;
  visual?: VisualName;
  children?: ReactNode;
}) {
  return (
    <section className="hero-band relative -mt-[4.75rem] px-6 pt-32 pb-16 sm:pt-36">
      <div className="mx-auto max-w-6xl text-center">
        <Breadcrumbs trail={trail} />
        <h1 className="lp-pop mx-auto max-w-4xl text-4xl leading-[1.05] font-extrabold tracking-tight text-balance text-white sm:text-6xl">
          {title}
        </h1>
        <p className="lp-pop mx-auto mt-5 max-w-2xl text-lg leading-relaxed text-pretty text-white [animation-delay:120ms] sm:text-xl">
          {lead}
        </p>
        {cta ? (
          <div className="lp-pop mt-8 flex justify-center [animation-delay:200ms]">
            <ButtonLink href="/register" size="lg" className="lp-key bg-white !text-[#1b2a8f] hover:!bg-white">
              <Wand2 aria-hidden="true" />
              {cta}
            </ButtonLink>
          </div>
        ) : null}
        {children}
        {visual ? <Visual name={visual} className="mx-auto mt-12 max-w-4xl text-left" /> : null}
      </div>
    </section>
  );
}

/** A centred section heading with one line of context. */
export function SectionTitle({ title, lead }: { title: string; lead?: string }) {
  return (
    <Reveal className="mx-auto max-w-2xl text-center">
      <h2 className="text-3xl font-extrabold tracking-tight text-balance sm:text-5xl">{title}</h2>
      {lead ? <p className="mt-4 text-lg text-pretty text-muted">{lead}</p> : null}
    </Reveal>
  );
}

/** A grid of features: a check, a title, one or two lines. */
export function FeatureGrid({ title, lead, items }: { title: string; lead?: string; items: { title: string; text: string }[] }) {
  return (
    <section className="px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <SectionTitle title={title} lead={lead} />
        <ul className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((item, i) => (
            <Reveal as="li" key={item.title} delay={(i % 3) * 80} className="rounded-card border border-border bg-surface p-6">
              <span className="flex size-9 items-center justify-center rounded-full bg-accent/10 text-accent-soft">
                <Check aria-hidden="true" className="size-5" />
              </span>
              <h3 className="mt-4 font-display text-lg font-bold">{item.title}</h3>
              <p className="mt-1.5 text-muted">{item.text}</p>
            </Reveal>
          ))}
        </ul>
      </div>
    </section>
  );
}

/** How it works: a real sequence of three steps. */
export function Steps({ title, steps }: { title: string; steps: { title: string; text: string }[] }) {
  return (
    <section className="border-y border-border bg-surface px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <SectionTitle title={title} />
        <ol className="mt-14 grid gap-6 md:grid-cols-3">
          {steps.map((step, i) => (
            <Reveal as="li" key={step.title} delay={i * 120} className="relative rounded-card bg-background p-7">
              <span className="tabular flex size-11 items-center justify-center rounded-full bg-accent-fill font-display text-lg font-extrabold text-white">
                {i + 1}
              </span>
              <h3 className="mt-5 font-display text-xl font-bold">{step.title}</h3>
              <p className="mt-2 text-muted">{step.text}</p>
              {i < steps.length - 1 ? (
                <ArrowRight aria-hidden="true" className="absolute top-10 -right-5 hidden size-5 text-subtle md:block" />
              ) : null}
            </Reveal>
          ))}
        </ol>
        <div className="mt-12 flex justify-center">
          <ButtonLink href="/register" size="lg" className="lp-key">
            <Wand2 aria-hidden="true" />
            Try it now
          </ButtonLink>
        </div>
      </div>
    </section>
  );
}

/** A long-form explanation beside a picture. */
export function Explainer({ title, paragraphs, visual }: { title: string; paragraphs: string[]; visual: VisualName }) {
  return (
    <section className="px-6 py-24">
      <div className="mx-auto grid max-w-6xl items-center gap-12 lg:grid-cols-2">
        <Reveal>
          <h2 className="text-3xl font-extrabold tracking-tight text-balance sm:text-4xl">{title}</h2>
          {paragraphs.map((paragraph) => (
            <p key={paragraph.slice(0, 24)} className="mt-5 text-lg leading-relaxed text-pretty text-muted">
              {paragraph}
            </p>
          ))}
        </Reveal>
        <Visual name={visual} />
      </div>
    </section>
  );
}

/** Cards that lead to other tools' pages. */
export function ToolCards({ title, slugs }: { title: string; slugs: string[] }) {
  const tools = slugs.map((slug) => TOOLS.find((tool) => tool.slug === slug)).filter((tool) => tool !== undefined);
  return (
    <section className="px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <SectionTitle title={title} />
        <ul className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {tools.map((tool) => (
            <li key={tool.slug}>
              <Link
                href={`/features/${tool.slug}`}
                className="group flex h-full flex-col rounded-card border border-border bg-surface p-6 transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-1 hover:border-accent/30 hover:shadow-[0_18px_40px_-20px_rgb(14_18_34/0.35)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <ToolIcon slug={tool.slug} />
                <span className="mt-4 font-display text-lg font-bold">{tool.name}</span>
                <span className="mt-1.5 flex-1 text-muted">{tool.summary}</span>
                <span className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-accent-soft">
                  Explore {tool.name}
                  <ArrowRight aria-hidden="true" className="size-4 transition-transform group-hover:translate-x-0.5" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/** Frequently asked questions as native disclosures. */
export function FaqList({ items, title = "Frequently asked questions", id = "faq" }: { items: Faq[]; title?: string; id?: string }) {
  return (
    <section id={id} className="scroll-mt-24 border-t border-border bg-surface px-6 py-24">
      <div className="mx-auto max-w-3xl">
        <Reveal as="h2" className="text-center text-3xl font-extrabold tracking-tight sm:text-5xl">
          {title}
        </Reveal>
        <div className="mt-12 divide-y divide-border rounded-canvas border border-border bg-background">
          {items.map(({ q, a }) => (
            <details key={q} className="group px-6">
              <summary className="flex min-h-16 cursor-pointer list-none items-center justify-between gap-4 py-4 font-display text-lg font-bold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden">
                {q}
                <ChevronDown aria-hidden="true" className="size-5 shrink-0 text-subtle transition-transform group-open:rotate-180" />
              </summary>
              <p className="pb-5 leading-relaxed text-muted">{a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
