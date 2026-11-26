import type { Metadata } from "next";
import { ClosingCta } from "@/components/landing/closing-cta";
import { Facts } from "@/components/landing/facts";
import { Explainer, PageHero, SiteShell } from "@/components/landing/page-blocks";
import { WhyPeakSift } from "@/components/landing/toolkit";

export const metadata: Metadata = {
  title: "About",
  description: "Why PeakSift exists and how it is built.",
};

export default function AboutPage() {
  return (
    <SiteShell>
      <PageHero
        trail={[{ label: "About" }]}
        title="We build the tool that finds the moments worth clipping"
        lead="Creators record hours of good material and post only minutes of it. PeakSift exists to close that gap — honestly, and without taking control away from the creator."
        cta="Try PeakSift"
        visual="moments"
      />
      <Explainer
        title="Why PeakSift"
        visual="find"
        paragraphs={[
          "The best moment of a podcast, a stream or a lesson is usually buried in the middle of it. Finding it, cutting it, framing it, captioning it and posting it to three apps takes longer than recording it did — so most of it never gets posted.",
          "PeakSift does that work in one place: it reads what was said, ranks the moments worth a Short with the reason for each, edits them for vertical and posts them where you choose.",
        ]}
      />
      <Explainer
        title="How it is built"
        visual="ask"
        paragraphs={[
          "AI in PeakSift proposes; the product decides. Every model answer is checked against your real transcript and your real files before you see it, and anything that cannot be checked is dropped rather than guessed.",
          "Your media stays private on the server, the AI that looks at your faces and visuals runs there too, and nothing is posted to a platform without your click. There are no virality scores and no invented numbers — only what was said and what the platforms report.",
        ]}
      />
      <Facts />
      <WhyPeakSift />
      <ClosingCta />
    </SiteShell>
  );
}
