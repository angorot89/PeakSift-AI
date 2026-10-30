"use client";

import type { LucideIcon } from "lucide-react";
import { Film } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

/**
 * A real still from one of the creator's own videos (a source, a clip or a Short) at a given
 * second. Nothing loads until the frame scrolls into view; the box keeps its ratio from the start
 * (no layout shift) and shows a quiet placeholder until a frame paints — some phones only draw
 * video frames on playback. Decorative: the surrounding card names what it shows.
 */
export function VideoFrame({
  src,
  at = 0.5,
  ratio = "video",
  icon: Icon = Film,
  className = "",
  children,
}: {
  /** An owner-checked media URL (`videoContentUrl`, `clipContentUrl`, `editContentUrl`). */
  src: string | null;
  /** The second to show. */
  at?: number;
  ratio?: "video" | "vertical" | "square";
  icon?: LucideIcon;
  className?: string;
  /** Overlays: badges, a duration, a play mark. */
  children?: ReactNode;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(false);
  const [painted, setPainted] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || !src) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: "200px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [src]);
  const aspect = ratio === "vertical" ? "aspect-[9/16]" : ratio === "square" ? "aspect-square" : "aspect-video";
  return (
    <span
      ref={ref}
      className={`relative block overflow-hidden bg-[radial-gradient(120%_90%_at_30%_20%,var(--surface-3),var(--background))] ${aspect} ${className}`}
    >
      <span aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-subtle/70">
        <Icon className="size-6" />
      </span>
      {visible && src ? (
        <video
          src={`${src}#t=${Math.max(0, at).toFixed(2)}`}
          preload="metadata"
          muted
          playsInline
          aria-hidden="true"
          tabIndex={-1}
          onLoadedData={() => setPainted(true)}
          className={`relative size-full object-cover transition-opacity duration-300 ${painted ? "opacity-100" : "opacity-0"}`}
        />
      ) : null}
      {/* A soft floor so overlay text stays readable on any frame. */}
      {children ? (
        <>
          <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/70 to-transparent" />
          {children}
        </>
      ) : null}
    </span>
  );
}

/** A small label on a thumbnail (a duration, a time range). */
export function FrameTag({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span className={`tabular absolute rounded-md bg-black/70 px-1.5 py-0.5 text-caption font-medium text-white backdrop-blur-sm ${className}`}>
      {children}
    </span>
  );
}
