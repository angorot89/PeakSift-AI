"use client";

import { useEffect, useState } from "react";
import { Reveal, useInView } from "@/components/landing/reveal";

/** Counts up to `to` once it is on screen (straight to the number under reduced motion). */
function CountUp({ to, suffix = "" }: { to: number; suffix?: string }) {
  const { ref, inView } = useInView<HTMLSpanElement>();
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!inView) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const start = performance.now();
    const duration = reduced ? 0 : 1200;
    let frame = 0;
    const tick = (now: number) => {
      const t = duration ? Math.min(1, (now - start) / duration) : 1;
      setValue(Math.round(to * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [inView, to]);
  return (
    <span ref={ref} className="tabular">
      <span aria-hidden="true">
        {value}
        {suffix}
      </span>
      <span className="sr-only">
        {to}
        {suffix}
      </span>
    </span>
  );
}

/**
 * PeakSift by its numbers — facts about the product (platforms, tools, the render and the mix),
 * never invented usage figures.
 */
export function Facts() {
  return (
    <section className="px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-4xl font-extrabold tracking-tight text-balance sm:text-5xl">Everything a Short needs, built in</h2>
          <p className="mt-4 text-lg text-pretty text-muted">The numbers behind every Short PeakSift makes.</p>
        </Reveal>
        <div className="mt-14 grid gap-4 lg:grid-cols-[1.6fr_1fr_1fr] lg:grid-rows-2">
          <Reveal className="flex min-h-72 flex-col justify-between rounded-canvas bg-[radial-gradient(70%_80%_at_80%_0%,rgb(140_160_255/0.6),transparent_70%),linear-gradient(150deg,#3d5afe,#5b3dfe)] p-8 text-white lg:row-span-2">
            <p className="text-sm font-semibold text-white/80">Platforms</p>
            <div>
              <p className="font-display text-8xl leading-none font-extrabold sm:text-9xl">
                <CountUp to={3} />
              </p>
              <p className="mt-4 max-w-sm text-lg text-white/90">
                places to post from one workspace: YouTube Shorts, TikTok and Instagram Reels.
              </p>
            </div>
          </Reveal>
          <Reveal delay={100} className="flex min-h-56 flex-col justify-between rounded-canvas bg-[#e3f25c] p-7 text-[#15170a] lg:row-span-2">
            <p className="text-sm font-semibold text-[#15170a]/70">Tools</p>
            <div>
              <p className="font-display text-7xl leading-none font-extrabold">
                <CountUp to={12} />
              </p>
              <p className="mt-3 text-[#15170a]/80">from finding the moment to posting it — no exporting between apps.</p>
            </div>
          </Reveal>
          <Reveal delay={200} className="rounded-canvas bg-[#141833] p-7 text-white">
            <p className="text-sm font-semibold text-white/70">Every render</p>
            <p className="mt-2 font-display text-4xl font-extrabold">1080×1920</p>
            <p className="mt-2 text-white/75">Full-HD vertical, ready for every platform.</p>
          </Reveal>
          <Reveal delay={300} className="rounded-canvas border border-accent/20 bg-accent/10 p-7">
            <p className="text-sm font-semibold text-accent-soft">Every mix</p>
            <p className="mt-2 font-display text-4xl font-extrabold text-accent-soft">
              −<CountUp to={14} /> LUFS
            </p>
            <p className="mt-2 text-muted">Loudness-matched sound, with music ducked under your voice.</p>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
