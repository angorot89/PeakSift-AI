import { ClosingCta } from "@/components/landing/closing-cta";
import { Facts } from "@/components/landing/facts";
import { Faq } from "@/components/landing/faq";
import { FeatureRows } from "@/components/landing/feature-rows";
import { Hero } from "@/components/landing/hero";
import { SiteShell } from "@/components/landing/page-blocks";
import { ShortsMarquee } from "@/components/landing/shorts-marquee";
import { TeamShorts } from "@/components/landing/team-shorts";
import { Toolkit, WhyPeakSift } from "@/components/landing/toolkit";

/** The public website's home page. */
export default function Home() {
  return (
    <SiteShell>
      <Hero />
      <ShortsMarquee />
      <TeamShorts />
      <FeatureRows />
      <Toolkit />
      <Facts />
      <WhyPeakSift />
      <Faq />
      <ClosingCta />
    </SiteShell>
  );
}
