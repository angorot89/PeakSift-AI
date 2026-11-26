"use client";

import { Play } from "lucide-react";
import { useState } from "react";
import type { YouTubeShort as Short } from "@/components/landing/clips";

/**
 * A YouTube Short shown as its thumbnail; pressing play swaps in YouTube's privacy-enhanced
 * player. Nothing is loaded from YouTube except the thumbnail until then.
 */
export function YouTubeShort({ short }: { short: Short }) {
  const [playing, setPlaying] = useState(false);
  return (
    <span className="relative block aspect-[9/16] overflow-hidden rounded-[8%/4.5%] bg-[#0d0f1c] shadow-[0_18px_40px_-18px_rgb(0_0_0/0.7)] ring-1 ring-white/10">
      {playing ? (
        <iframe
          src={`https://www.youtube-nocookie.com/embed/${encodeURIComponent(short.id)}?autoplay=1&playsinline=1&rel=0`}
          title={short.title}
          allow="autoplay; encrypted-media; picture-in-picture"
          allowFullScreen
          className="absolute inset-0 size-full border-0"
        />
      ) : (
        <button
          type="button"
          onClick={() => setPlaying(true)}
          aria-label={`Play “${short.title}” on YouTube`}
          className="group absolute inset-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- a remote YouTube thumbnail */}
          <img
            src={`https://i.ytimg.com/vi/${encodeURIComponent(short.id)}/oardefault.jpg`}
            alt=""
            loading="lazy"
            className="size-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
          <span className="absolute top-1/2 left-1/2 flex size-14 -translate-1/2 items-center justify-center rounded-full bg-black/45 text-white backdrop-blur-sm transition-transform group-hover:scale-110">
            <Play aria-hidden="true" className="size-6 fill-white" />
          </span>
        </button>
      )}
    </span>
  );
}
