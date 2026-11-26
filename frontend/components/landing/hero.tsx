import { Captions, Crop, Search, Wand2 } from "lucide-react";
import { ButtonLink } from "@/components/ui/button-link";
import { MomentStrip } from "@/components/ui/moment-strip";

const PLATFORMS = ["YouTube Shorts", "TikTok", "Instagram Reels"];

/** Where each feature is explained further down the page. */
const FEATURES = [
  { href: "#find", label: "AI moments", icon: Search },
  { href: "#edit", label: "Smart reframe", icon: Crop },
  { href: "#edit", label: "Captions", icon: Captions },
  { href: "#edit", label: "Auto Edit", icon: Wand2 },
];

/** Three moments as PeakSift lists them (an illustration, not real data). */
const MOMENTS = [
  { at: "04:12", title: "“Here's the one thing nobody tells you about pricing”", why: "Opens on a clear question", top: true },
  { at: "21:37", title: "“We lost every customer in a week — and this is why”", why: "A turn in the story" },
  { at: "38:05", title: "“Do this before you hit record”", why: "A complete, quotable tip" },
];

/**
 * The product, in one frame: a recording's waveform with its moments marked, and the moments
 * listed the way PeakSift shows them. Dark, like the workspace. An illustration.
 */
function ProductFrame() {
  return (
    <div className="theme-dark mx-auto mt-14 max-w-5xl rounded-canvas border border-white/10 p-3 text-left shadow-[0_40px_80px_-30px_rgb(14_18_34/0.6)] sm:p-4">
      <div className="flex items-center justify-between px-2 pb-3">
        <span className="flex gap-1.5" aria-hidden="true">
          <span className="size-2.5 rounded-full bg-surface-3" />
          <span className="size-2.5 rounded-full bg-surface-3" />
          <span className="size-2.5 rounded-full bg-surface-3" />
        </span>
        <span className="text-caption text-subtle">Illustration</span>
      </div>
      <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
        <div className="rounded-card border border-border bg-surface p-5">
          <p className="text-title">Founder interview — full episode</p>
          <p className="text-small text-subtle">45 minutes · 3 moments found</p>
          <MomentStrip compact className="mt-10" />
        </div>
        <ul className="flex flex-col gap-2">
          {MOMENTS.map((moment) => (
            <li key={moment.at} className="rounded-block border border-border bg-surface p-3.5">
              <span className="flex items-center gap-2">
                <span className="tabular rounded-full bg-accent/20 px-2 py-0.5 text-caption font-semibold text-accent-soft">{moment.at}</span>
                {moment.top ? (
                  <span className="rounded-full bg-success/15 px-2 py-0.5 text-caption font-medium text-emerald-200">Top pick</span>
                ) : null}
              </span>
              <p className="mt-2 text-sm font-medium text-foreground">{moment.title}</p>
              <p className="mt-1 text-small text-subtle">{moment.why}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function Hero() {
  return (
    <section className="hero-band relative -mt-[4.75rem] px-6 pt-32 pb-20 sm:pt-40">
      <div className="mx-auto max-w-6xl text-center">
        <ul aria-label="Made for" className="flex flex-wrap justify-center gap-2">
          {PLATFORMS.map((platform) => (
            <li key={platform} className="rounded-full border border-white/30 bg-white/15 px-3 py-1 text-small font-medium text-white">
              {platform}
            </li>
          ))}
        </ul>
        <h1 className="mx-auto mt-6 max-w-4xl text-5xl leading-[1.02] font-extrabold tracking-tight text-balance text-white sm:text-7xl">
          Turn long videos into Shorts worth watching
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-pretty text-white/90 sm:text-xl">
          Drop a stream, podcast or interview. PeakSift finds the moments worth clipping, edits them for vertical and helps
          you post them everywhere.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <ButtonLink
            href="/register"
            size="lg"
            className="w-full bg-white !text-[#1b2a8f] shadow-[0_10px_30px_-10px_rgb(14_18_34/0.5)] hover:!bg-white/90 sm:w-auto"
          >
            <Wand2 aria-hidden="true" />
            Start clipping
          </ButtonLink>
          <a
            href="#features"
            className="inline-flex min-h-12 items-center rounded-control px-4 font-medium text-white underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            See what it does
          </a>
        </div>

        <ProductFrame />

        <ul className="mt-8 flex flex-wrap justify-center gap-2">
          {FEATURES.map((feature) => (
            <li key={feature.label}>
              <a
                href={feature.href}
                className="inline-flex min-h-10 items-center gap-2 rounded-control border border-border bg-surface px-3 text-sm font-medium text-foreground transition-colors hover:border-accent/50 hover:text-accent-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <feature.icon aria-hidden="true" className="size-4 text-accent-soft" />
                {feature.label}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
