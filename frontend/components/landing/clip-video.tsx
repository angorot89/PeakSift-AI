"use client";

import { Play } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { RealClip } from "@/components/landing/clips";
import { PlatformBadge } from "@/components/landing/scene-parts";

function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const query = window.matchMedia("(prefers-reduced-motion: reduce)");
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
}

/**
 * A real Short made with PeakSift: muted, looping, playing only while on screen. Under reduced
 * motion it waits on its poster until the play button is pressed.
 */
export function ClipVideo({ clip, className = "" }: { clip: RealClip; className?: string }) {
  const ref = useRef<HTMLVideoElement>(null);
  const reduced = useReducedMotion();
  const [started, setStarted] = useState(false);
  const autoplay = !reduced || started;

  useEffect(() => {
    const video = ref.current;
    if (!video || !autoplay) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) void video.play().catch(() => undefined);
      else video.pause();
    });
    observer.observe(video);
    return () => observer.disconnect();
  }, [autoplay]);

  return (
    <span className={`relative block aspect-[9/16] overflow-hidden rounded-[8%/4.5%] bg-[#0d0f1c] shadow-[0_18px_40px_-18px_rgb(0_0_0/0.7)] ring-1 ring-white/10 ${className}`}>
      <video
        ref={ref}
        src={clip.src}
        poster={clip.poster}
        muted
        loop
        playsInline
        preload="none"
        aria-label={clip.title ?? `A ${clip.kind.toLowerCase()} Short`}
        className="size-full object-cover"
      />
      {!autoplay ? (
        <button
          type="button"
          onClick={() => setStarted(true)}
          aria-label={`Play “${clip.title ?? clip.kind}”`}
          className="absolute top-1/2 left-1/2 flex size-14 -translate-1/2 items-center justify-center rounded-full bg-black/40 text-white backdrop-blur-sm"
        >
          <Play aria-hidden="true" className="size-6 fill-white" />
        </button>
      ) : null}
      {clip.platform ? <PlatformBadge platform={clip.platform} className="absolute right-[5%] bottom-[3%] size-7" /> : null}
    </span>
  );
}
