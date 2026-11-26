import { Check, Wand2 } from "lucide-react";
import type { Metadata } from "next";
import { ClosingCta } from "@/components/landing/closing-cta";
import { TOOLS } from "@/components/landing/content";
import { FaqList, PageHero, SiteShell, ToolCards } from "@/components/landing/page-blocks";
import { Reveal } from "@/components/landing/reveal";
import { ButtonLink } from "@/components/ui/button-link";

export const metadata: Metadata = {
  title: "Pricing",
  description: "PeakSift is free to use while it is in development.",
};

/**
 * Pricing, honestly: PeakSift has no paid plans, so there is one card — what you get today — and
 * no invented tiers or prices.
 */
export default function PricingPage() {
  return (
    <SiteShell>
      <PageHero
        trail={[{ label: "Pricing" }]}
        title="PeakSift pricing"
        lead="PeakSift is free to use while it is in development. There are no paid plans, and no payment details are asked for."
        cta="Create a free account"
      />
      <section className="-mt-10 px-6">
        <Reveal className="relative mx-auto max-w-xl rounded-canvas border-2 border-accent bg-surface p-8 shadow-[0_30px_60px_-30px_rgb(61_90_254/0.5)] sm:p-10">
          <span className="absolute -top-3.5 left-1/2 -translate-x-1/2 rounded-full bg-accent-fill px-3 py-1 text-small font-semibold text-white">
            Early access
          </span>
          <p className="font-display text-2xl font-extrabold">Everything PeakSift does</p>
          <p className="mt-3 flex items-baseline gap-2">
            <span className="font-display text-6xl font-extrabold">Free</span>
            <span className="text-muted">while in development</span>
          </p>
          <ButtonLink href="/register" size="lg" className="lp-key mt-6 w-full">
            <Wand2 aria-hidden="true" />
            Start clipping
          </ButtonLink>
          <p className="mt-6 text-small font-semibold text-subtle">Included</p>
          <ul className="mt-3 grid gap-2.5 sm:grid-cols-2">
            {TOOLS.map((tool) => (
              <li key={tool.slug} className="flex items-start gap-2 text-sm">
                <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-success" />
                {tool.name}
              </li>
            ))}
          </ul>
        </Reveal>
      </section>
      <ToolCards title="Every tool is included" slugs={TOOLS.map((tool) => tool.slug)} />
      <FaqList
        title="Questions about pricing"
        items={[
          { q: "Is PeakSift free?", a: "Yes, while it is in development. There are no paid plans today." },
          { q: "Do I need a card to sign up?", a: "No. PeakSift never asks for payment details." },
          { q: "Does PeakSift add a watermark?", a: "No. Your Shorts carry only what you add — your logo, if you choose one in Brand Studio." },
          { q: "Will there be paid plans?", a: "There are none today. If that ever changes, it will be announced here first — nothing is charged without your agreement." },
        ]}
      />
      <ClosingCta />
    </SiteShell>
  );
}
