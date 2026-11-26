import { Wand2 } from "lucide-react";
import { DemoCarousel } from "@/components/landing/demo-carousel";
import { PlatformBadge, type Platform } from "@/components/landing/scene-parts";
import { ButtonLink } from "@/components/ui/button-link";

const PLATFORMS: { key: Platform; label: string }[] = [
  { key: "youtube", label: "YouTube Shorts" },
  { key: "tiktok", label: "TikTok" },
  { key: "instagram", label: "Instagram Reels" },
];

export function Hero() {
  return (
    <section className="hero-band relative -mt-[4.75rem] px-6 pt-32 pb-16 sm:pt-40">
      <div className="mx-auto max-w-6xl text-center">
        <ul aria-label="Publish to" className="flex flex-wrap justify-center gap-2">
          {PLATFORMS.map((platform) => (
            <li
              key={platform.key}
              className="lp-pop inline-flex items-center gap-1.5 rounded-full border border-white/30 bg-white/15 py-1 pr-3 pl-1 text-small font-semibold text-white backdrop-blur"
            >
              <PlatformBadge platform={platform.key} className="size-6 rounded-full" />
              {platform.label}
            </li>
          ))}
        </ul>
        <h1 className="lp-pop mx-auto mt-6 max-w-5xl text-5xl leading-[1.02] font-extrabold tracking-tight text-balance text-white [animation-delay:80ms] sm:text-7xl lg:text-[5.25rem]">
          Turn long videos into Shorts worth watching
        </h1>
        <p className="lp-pop mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-pretty text-white [animation-delay:160ms] sm:text-xl">
          Drop a stream, podcast or interview. PeakSift finds the moments worth clipping, edits them for vertical and helps
          you post them everywhere.
        </p>
        <div className="lp-pop mt-9 flex flex-col items-center justify-center gap-3 [animation-delay:240ms] sm:flex-row">
          <ButtonLink href="/register" size="lg" className="lp-key w-full bg-white !text-[#1b2a8f] hover:!bg-white sm:w-auto">
            <Wand2 aria-hidden="true" />
            Start clipping
          </ButtonLink>
          <a
            href="#features"
            className="inline-flex min-h-12 items-center rounded-control px-4 font-semibold text-white underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            See what it does
          </a>
        </div>

        <DemoCarousel />
      </div>
    </section>
  );
}
