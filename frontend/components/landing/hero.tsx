import { ButtonLink } from "@/components/ui/button-link";
import { MomentStrip } from "@/components/ui/moment-strip";

export function Hero() {
  return (
    <section className="relative">
      <div className="mx-auto max-w-6xl px-6 pt-20 pb-20 sm:pt-28">
        <h1 className="max-w-4xl text-5xl leading-[0.95] font-semibold tracking-tight text-balance sm:text-7xl lg:text-8xl">
          Find the moments worth clipping.
        </h1>

        <p className="mt-6 max-w-xl text-lg leading-relaxed text-pretty text-muted sm:text-xl">
          Upload a long video. PeakSift reads what was said, marks the strongest moments and helps you cut
          them into Shorts for YouTube, TikTok and Instagram Reels.
        </p>

        <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
          <ButtonLink href="/register" size="lg" className="w-full sm:w-auto">
            Get started
          </ButtonLink>
          <ButtonLink href="#how-it-works" variant="secondary" size="lg" className="w-full sm:w-auto">
            See how it works
          </ButtonLink>
          <span className="text-sm text-subtle sm:ml-3">In development</span>
        </div>

        <MomentStrip className="mt-14 sm:mt-20" />
      </div>
    </section>
  );
}
