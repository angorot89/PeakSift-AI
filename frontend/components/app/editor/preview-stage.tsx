"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { CaptionOverlay } from "@/components/app/editor/caption-sample";
import type { CaptionPosition, CaptionStyle, Layout } from "@/lib/edits";

/** The 9:16 device-like frame both the live preview and the rendered short sit in. */
export function NineBySixteenFrame({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div
      role="group"
      aria-label={label}
      // Sized by width with a locked 9:16 ratio, capped so the frame never exceeds
      // min(64vh, 600px) in height: it stays exactly 9:16 at every screen width.
      className="relative mx-auto aspect-[9/16] w-full max-w-[calc(min(64vh,600px)*0.5625)] overflow-hidden rounded-[22px] border border-white/12 bg-black shadow-[0_30px_80px_-30px_rgb(0_0_0/0.9)] ring-1 ring-black"
      style={{ containerType: "size" }}
    >
      {children}
    </div>
  );
}

type PreviewProps = {
  clipSrc: string;
  layout: Layout;
  captions: boolean;
  style: CaptionStyle;
  position: CaptionPosition;
  sampleText: string;
};

/**
 * A lightweight browser simulation of the chosen settings, played from the generated clip.
 * It shows layout and caption placement; it is labelled as a preview because the server's
 * FFmpeg render (blur strength, exact glyph shapes) is the authoritative result.
 */
export function PreviewStage({ clipSrc, layout, captions, style, position, sampleText }: PreviewProps) {
  const front = useRef<HTMLVideoElement>(null);
  const back = useRef<HTMLVideoElement>(null);

  // Keep the blurred backdrop in step with the playing foreground.
  useEffect(() => {
    const fg = front.current;
    const bg = back.current;
    if (!fg || !bg) return;
    const sync = () => {
      if (Math.abs(bg.currentTime - fg.currentTime) > 0.25) bg.currentTime = fg.currentTime;
    };
    const play = () => {
      sync();
      void bg.play().catch(() => {});
    };
    const pause = () => bg.pause();
    fg.addEventListener("play", play);
    fg.addEventListener("pause", pause);
    fg.addEventListener("seeked", sync);
    fg.addEventListener("timeupdate", sync);
    return () => {
      fg.removeEventListener("play", play);
      fg.removeEventListener("pause", pause);
      fg.removeEventListener("seeked", sync);
      fg.removeEventListener("timeupdate", sync);
    };
  }, [layout]);

  return (
    <NineBySixteenFrame label="Live preview of the edit settings">
      {layout === "blur_background" ? (
        <video
          ref={back}
          aria-hidden="true"
          tabIndex={-1}
          muted
          playsInline
          preload="metadata"
          src={`${clipSrc}#t=0.1`}
          className="absolute inset-0 size-full scale-110 object-cover blur-xl"
        />
      ) : null}
      {layout === "fit" ? <div aria-hidden="true" className="absolute inset-0 bg-[#111113]" /> : null}
      <video
        ref={front}
        controls
        playsInline
        preload="metadata"
        src={`${clipSrc}#t=0.1`}
        aria-label="Preview playback"
        className={`absolute inset-0 size-full ${layout === "center_crop" ? "object-cover" : "object-contain"}`}
      />
      {captions ? <CaptionOverlay text={sampleText} style={style} position={position} /> : null}
    </NineBySixteenFrame>
  );
}
