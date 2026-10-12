import { ButtonLink } from "@/components/ui/button-link";

const platforms = ["YouTube Shorts", "TikTok", "Instagram Reels"];

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_60%_50%_at_50%_0%,rgb(249_115_22/0.16),transparent_70%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,rgb(255_255_255/0.04)_1px,transparent_1px),linear-gradient(to_bottom,rgb(255_255_255/0.04)_1px,transparent_1px)] bg-[size:64px_64px] [mask-image:radial-gradient(ellipse_70%_60%_at_50%_0%,black,transparent)]"
      />

      <div className="relative mx-auto max-w-6xl px-6 pt-24 pb-16 text-center sm:pt-32">
        <p className="inline-flex animate-fade-up items-center gap-2 rounded-full border border-border bg-white/[0.03] px-3 py-1 text-xs font-medium text-muted">
          <span className="size-1.5 rounded-full bg-accent" />
          Now in development
        </p>

        <h1 className="mx-auto mt-6 max-w-4xl animate-fade-up text-5xl font-semibold tracking-tight text-balance [animation-delay:80ms] sm:text-6xl lg:text-7xl">
          Find the moments{" "}
          <span className="bg-gradient-to-br from-accent-soft via-accent to-rose-500 bg-clip-text text-transparent">
            worth clipping.
          </span>
        </h1>

        <p className="mx-auto mt-6 max-w-2xl animate-fade-up text-lg leading-relaxed text-pretty text-muted [animation-delay:160ms] sm:text-xl">
          PeakSift AI helps creators discover the strongest moments inside
          long-form content and turn them into short-form content for YouTube
          Shorts, TikTok, and Instagram Reels.
        </p>

        <div className="mt-10 flex animate-fade-up flex-col items-center justify-center gap-3 [animation-delay:240ms] sm:flex-row">
          <ButtonLink href="/register" size="lg" className="w-full sm:w-auto">
            Get Started
          </ButtonLink>
          <ButtonLink
            href="#how-it-works"
            variant="secondary"
            size="lg"
            className="w-full sm:w-auto"
          >
            See How It Works
          </ButtonLink>
        </div>

        <ul className="mt-10 flex animate-fade-up flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-subtle [animation-delay:320ms]">
          <li className="w-full sm:w-auto">Built for</li>
          {platforms.map((platform) => (
            <li key={platform} className="text-zinc-400">
              {platform}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
