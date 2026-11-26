import { ClosingCta } from "@/components/landing/closing-cta";
import { Faq } from "@/components/landing/faq";
import { FeatureRows } from "@/components/landing/feature-rows";
import { Hero } from "@/components/landing/hero";
import { Toolkit, WhyPeakSift } from "@/components/landing/toolkit";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

/** The public website: light, with the dark workspace shown inside it. */
export default function Home() {
  return (
    <div className="theme-light flex flex-1 flex-col">
      <SiteHeader />
      <main className="flex-1">
        <Hero />
        <FeatureRows />
        <Toolkit />
        <WhyPeakSift />
        <Faq />
        <ClosingCta />
      </main>
      <SiteFooter />
    </div>
  );
}
