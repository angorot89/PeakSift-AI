import { Music2, Play } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

/**
 * Small drawn pieces the website's illustrations are made of. Everything is drawn with CSS — no
 * photographs or other people's footage — and every scene is labelled as an illustration.
 */

export const delay = (ms: number): CSSProperties => ({ animationDelay: `${ms}ms` });

/** A simple person (head and shoulders) in a colour, sized by its container. */
export function Person({ tone = "#ffb86b", shirt = "#3d5afe", className = "" }: { tone?: string; shirt?: string; className?: string }) {
  return (
    <span aria-hidden="true" className={`${className.includes("relative") ? "" : "absolute"} flex flex-col items-center ${className}`}>
      <span className="aspect-square w-[42%] rounded-full" style={{ background: tone }} />
      <span className="-mt-[6%] aspect-[2/1] w-full rounded-t-full" style={{ background: shirt }} />
    </span>
  );
}

/** A scene backdrop: a soft gradient "room" with a lamp-like glow. */
export function Backdrop({ from, to, glow = "rgb(255 255 255 / 0.18)" }: { from: string; to: string; glow?: string }) {
  return (
    <span
      aria-hidden="true"
      className="absolute inset-0"
      style={{ background: `radial-gradient(60% 50% at 70% 20%, ${glow}, transparent 70%), linear-gradient(160deg, ${from}, ${to})` }}
    />
  );
}

export type Platform = "youtube" | "tiktok" | "instagram";

/** Plain glyphs that say which platform (a play button, a note, a camera) — not the brands' logos. */
function PlayGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className}>
      <path d="M9 7.5v9l7.5-4.5z" fill="currentColor" />
    </svg>
  );
}
function CameraGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className={className}>
      <rect x="4" y="4" width="16" height="16" rx="5" />
      <circle cx="12" cy="12" r="3.6" />
      <circle cx="17" cy="7" r="0.6" fill="currentColor" />
    </svg>
  );
}

const PLATFORM: Record<Platform, { label: string; className: string; icon: (props: { className?: string }) => ReactNode }> = {
  youtube: { label: "YouTube Shorts", className: "bg-[#ff3b3b] text-white", icon: PlayGlyph },
  tiktok: { label: "TikTok", className: "bg-black text-white ring-1 ring-white/20", icon: Music2 },
  instagram: { label: "Instagram Reels", className: "bg-[linear-gradient(45deg,#f9a825,#e91e63,#7b1fa2)] text-white", icon: CameraGlyph },
};

/** A platform's badge (icon only, named for assistive technology by the label). */
export function PlatformBadge({ platform, className = "" }: { platform: Platform; className?: string }) {
  const p = PLATFORM[platform];
  return (
    <span title={p.label} className={`inline-flex items-center justify-center rounded-md ${p.className} ${className}`}>
      <p.icon className="size-[62%]" />
      <span className="sr-only">{p.label}</span>
    </span>
  );
}

/** A vertical Short: a scene, a caption and an optional platform badge on top. */
export function ShortFrame({
  children,
  caption,
  platform,
  className = "",
  style,
  play = false,
}: {
  children?: ReactNode;
  caption?: ReactNode;
  platform?: Platform;
  className?: string;
  style?: CSSProperties;
  play?: boolean;
}) {
  return (
    <span style={style} className={`@container ${className.includes("absolute") ? "" : "relative"} block aspect-[9/16] overflow-hidden rounded-[8%/4.5%] bg-[#0d0f1c] shadow-[0_18px_40px_-18px_rgb(0_0_0/0.7)] ring-1 ring-white/10 ${className}`}>
      {children}
      {play ? (
        <span aria-hidden="true" className="absolute top-1/2 left-1/2 flex size-[26cqw] -translate-1/2 items-center justify-center rounded-full bg-black/35 backdrop-blur-sm">
          <Play className="size-[45%] fill-white text-white" />
        </span>
      ) : null}
      {caption ? (
        <span className="absolute inset-x-[6%] bottom-[16%] text-center font-display text-[9cqw] leading-tight font-extrabold text-white [text-shadow:0_2px_6px_rgb(0_0_0/0.6)]">
          {caption}
        </span>
      ) : null}
      {platform ? <PlatformBadge platform={platform} className="absolute top-[4%] right-[5%] size-[16cqw]" /> : null}
    </span>
  );
}

/** A mouse pointer that glides in and presses. */
export function Cursor({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" style={style} className={`lp-cursor absolute size-[3.2cqw] min-h-4 min-w-4 drop-shadow ${className}`}>
      <path d="M4 2l15 9-6.5 1.5L16 20l-3 1.5-3.5-7.5L4 18z" fill="white" stroke="#0d0f1c" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}
