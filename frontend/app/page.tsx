import { Announcement } from "@/components/landing/announcement";
import { ClosingCta } from "@/components/landing/closing-cta";
import { Facts } from "@/components/landing/facts";
import { Faq } from "@/components/landing/faq";
import { FeatureRows } from "@/components/landing/feature-rows";
import { Hero } from "@/components/landing/hero";
import { ShortsMarquee } from "@/components/landing/shorts-marquee";
import { Toolkit, WhyPeakSift } from "@/components/landing/toolkit";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

/** The public website: light, with the dark workspace shown inside it. */
export default function Home() {
  return (
    <div className="theme-light flex flex-1 flex-col overflow-x-clip">
      <Announcement />
      <SiteHeader />
      <main className="flex-1">
        <Hero />
        <ShortsMarquee />
        <FeatureRows />
        <Toolkit />
        <Facts />
        <WhyPeakSift />
        <Faq />
        <ClosingCta />
      </main>
      <SiteFooter />
    </div>
  );
}
