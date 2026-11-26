import { ArrowRight, BarChart3, Captions, ShieldCheck, Sparkles, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { TOOLS } from "@/components/landing/content";
import { ToolIcon } from "@/components/landing/tool-icon";
import { Reveal } from "@/components/landing/reveal";

/** Every tool, one card each, leading to its own page. */
export function Toolkit() {
  return (
    <section id="toolkit" className="scroll-mt-24 border-t border-border bg-surface px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-4xl font-extrabold tracking-tight text-balance sm:text-5xl">Everything in one workspace</h2>
          <p className="mt-4 text-lg text-pretty text-muted">Every tool you need to turn long videos into Shorts — no exporting between apps.</p>
        </Reveal>
        <ul className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {TOOLS.map((tool) => (
            <li key={tool.slug}>
              <Link
                href={`/features/${tool.slug}`}
                className="group block h-full rounded-card border border-border bg-background p-6 transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-1 hover:border-accent/30 hover:shadow-[0_18px_40px_-20px_rgb(14_18_34/0.35)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <span className="block w-fit transition-transform duration-200 group-hover:scale-110">
                  <ToolIcon slug={tool.slug} />
                </span>
                <span className="mt-4 flex items-center gap-1 font-display text-lg font-bold">
                  {tool.name}
                  <ArrowRight aria-hidden="true" className="size-4 text-subtle opacity-0 transition-[opacity,transform] group-hover:translate-x-0.5 group-hover:opacity-100" />
                </span>
                <span className="mt-1.5 block text-muted">{tool.summary}</span>
              </Link>
            </li>
          ))}
        </ul>
        <div className="mt-10 flex justify-center">
          <Link href="/features" className="inline-flex min-h-11 items-center gap-1.5 font-semibold text-accent-soft hover:underline">
            Explore all tools
            <ArrowRight aria-hidden="true" className="size-4" />
          </Link>
        </div>
      </div>
    </section>
  );
}

const PRINCIPLES: { title: string; text: string; icon: LucideIcon }[] = [
  { title: "Every pick has a reason", text: "See why a moment made the list — the line it opens on, the turn in the story.", icon: Sparkles },
  { title: "Your words, never invented", text: "Captions, hooks and search results come from your own transcript.", icon: Captions },
  { title: "Private by default", text: "Your media stays in your workspace. Nothing is posted without your click.", icon: ShieldCheck },
  { title: "No fake numbers", text: "Analytics show only what the platforms report — never predictions.", icon: BarChart3 },
];

/** Why PeakSift: the promises behind the product, in plain statements (no invented figures). */
export function WhyPeakSift() {
  return (
    <section className="px-6 pb-24">
      <Reveal className="mx-auto grid max-w-6xl gap-10 rounded-canvas border border-border bg-surface p-8 sm:p-12 lg:grid-cols-[1fr_1.3fr] lg:items-center">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight text-balance sm:text-5xl">Built to explain itself</h2>
          <p className="mt-4 text-lg text-pretty text-muted">
            PeakSift suggests; you decide. Every choice it makes comes with the reason, and nothing happens to your
            channel without you.
          </p>
        </div>
        <ul className="grid gap-4 sm:grid-cols-2">
          {PRINCIPLES.map((principle) => (
            <li key={principle.title} className="rounded-card bg-background p-5">
              <principle.icon aria-hidden="true" className="size-6 text-accent-soft" />
              <p className="mt-3 font-display text-lg font-bold">{principle.title}</p>
              <p className="mt-1 text-muted">{principle.text}</p>
            </li>
          ))}
        </ul>
      </Reveal>
    </section>
  );
}
