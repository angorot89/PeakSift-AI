import type { Metadata } from "next";
import { ClosingCta } from "@/components/landing/closing-cta";
import { Breadcrumbs, FaqList, SectionTitle, SiteShell } from "@/components/landing/page-blocks";
import { ComparisonTable, PricingPlans } from "@/components/landing/pricing-plans";

export const metadata: Metadata = {
  title: "Pricing",
  description: "Free, Starter, Creator and Pro plans. Every tool is free during early access.",
};

export default function PricingPage() {
  return (
    <SiteShell>
      <section className="hero-band relative -mt-[4.75rem] px-6 pt-32 pb-20 sm:pt-36">
        <div className="mx-auto max-w-6xl text-center">
          <Breadcrumbs trail={[{ label: "Pricing" }]} />
          <h1 className="lp-pop text-4xl font-extrabold tracking-tight text-white sm:text-6xl">PeakSift pricing</h1>
          <p className="lp-pop mx-auto mt-5 max-w-2xl text-lg text-pretty text-white [animation-delay:120ms] sm:text-xl">
            Start free. Upgrade when you post more. Every tool is free during early access.
          </p>
          <PricingPlans />
        </div>
      </section>
      <section className="px-6 py-24">
        <SectionTitle title="Compare every plan" lead="Everything each plan includes, side by side." />
        <ComparisonTable />
      </section>
      <FaqList
        title="Questions about pricing"
        items={[
          { q: "Is PeakSift free?", a: "Yes. The Free plan stays free, and during early access every account has every tool for free." },
          { q: "When do paid plans start?", a: "When billing opens. You will be told before it does, and nothing is ever charged without your agreement." },
          { q: "What counts as an hour of video?", a: "The length of the long videos you upload in a month. Making Shorts from them does not count again." },
          { q: "Does PeakSift add a watermark?", a: "No, on any plan. Your Shorts carry only what you add, such as your own logo." },
          { q: "Can I change or cancel my plan?", a: "Yes — once billing opens you can move between plans or cancel at any time." },
          { q: "Is there a yearly discount?", a: "Yes. Paying yearly gives you two months free on every paid plan." },
        ]}
      />
      <ClosingCta />
    </SiteShell>
  );
}
