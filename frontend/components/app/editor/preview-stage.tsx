"use client";

import { Pause, Play } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { VideoClockContext } from "@/components/app/editor/caption-layer";
import type { Layout } from "@/lib/edits";
import { clampedCenter, cropCenterAt, cropGeometry, type CropKeyframe } from "@/lib/reframe";

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
  /** Text layers (captions, hook, safe-area guide) in output-frame coordinates. */
  overlay?: ReactNode;
};

/**
 * A lightweight browser simulation of the chosen settings, played from the generated clip.
 * It shows layout and caption placement; it is labelled as a preview because the server's
 * FFmpeg render (blur strength, exact glyph shapes) is the authoritative result.
 */
export function PreviewStage({ clipSrc, layout, overlay }: PreviewProps) {
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
      <VideoClockContext.Provider value={front}>{overlay}</VideoClockContext.Provider>
    </NineBySixteenFrame>
  );
}

export type Framing =
  | { kind: "path"; keyframes: CropKeyframe[] }
  | { kind: "focus"; x: number; y: number }
  | { kind: "center" };

function formatClock(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

type VideoWithFrameCallback = HTMLVideoElement & {
  requestVideoFrameCallback?: (cb: (now: number, meta: { mediaTime: number }) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

/**
 * Preview of a crop-based framing (smart path, manual focal point or centre): the real clip
 * is positioned inside the 9:16 frame with a CSS transform computed from the same crop path
 * the renderer uses, updated on every decoded frame (requestVideoFrameCallback, with a
 * requestAnimationFrame fallback). The rendered MP4 remains the authoritative output.
 */
export function ReframedPreview({
  clipSrc,
  sourceWidth,
  sourceHeight,
  framing,
  overlay,
  badge,
}: {
  clipSrc: string;
  sourceWidth: number;
  sourceHeight: number;
  framing: Framing;
  /** Text layers in output-frame coordinates: they never move with the crop. */
  overlay?: ReactNode;
  badge?: ReactNode;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const geometry = cropGeometry(sourceWidth, sourceHeight);
  const horizontal = geometry.axis !== "y";

  const centerAt = useCallback(
    (t: number) => {
      if (framing.kind === "path") return cropCenterAt(framing.keyframes, t);
      if (framing.kind === "focus") return clampedCenter(sourceWidth, sourceHeight, framing.x, framing.y);
      return { x: 0.5, y: 0.5 };
    },
    [framing, sourceWidth, sourceHeight],
  );

  useEffect(() => {
    const element = video.current as VideoWithFrameCallback | null;
    if (!element) return;
    const apply = (t: number) => {
      const c = centerAt(t);
      element.style.transform = horizontal ? `translateX(${-c.x * 100}%)` : `translateY(${-c.y * 100}%)`;
    };
    apply(element.currentTime || 0);
    let handle = 0;
    let raf = 0;
    if (element.requestVideoFrameCallback) {
      const loop = (_now: number, meta: { mediaTime: number }) => {
        apply(meta.mediaTime);
        handle = element.requestVideoFrameCallback!(loop);
      };
      handle = element.requestVideoFrameCallback(loop);
    } else {
      const tick = () => {
        apply(element.currentTime);
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    }
    const sync = () => apply(element.currentTime);
    element.addEventListener("seeked", sync);
    element.addEventListener("loadeddata", sync);
    return () => {
      if (handle && element.cancelVideoFrameCallback) element.cancelVideoFrameCallback(handle);
      if (raf) cancelAnimationFrame(raf);
      element.removeEventListener("seeked", sync);
      element.removeEventListener("loadeddata", sync);
    };
  }, [centerAt, horizontal]);

  function toggle() {
    const element = video.current;
    if (!element) return;
    if (element.paused) void element.play().catch(() => {});
    else element.pause();
  }

  return (
    <div className="space-y-2">
      <NineBySixteenFrame label="Live preview of the edit settings">
        <video
          ref={video}
          playsInline
          preload="metadata"
          src={`${clipSrc}#t=0.1`}
          aria-label="Preview playback"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 0)}
          onClick={toggle}
          className="absolute max-w-none cursor-pointer"
          style={
            horizontal
              ? { top: 0, left: "50%", height: "100%", aspectRatio: `${sourceWidth} / ${sourceHeight}` }
              : { left: 0, top: "50%", width: "100%", aspectRatio: `${sourceWidth} / ${sourceHeight}` }
          }
        />
        <VideoClockContext.Provider value={video}>{overlay}</VideoClockContext.Provider>
        {badge ? <div className="absolute top-2.5 left-2.5 max-w-[calc(100%-1.25rem)]">{badge}</div> : null}
      </NineBySixteenFrame>
      <div className="mx-auto flex max-w-[calc(min(64vh,600px)*0.5625)] items-center gap-2.5">
        <button
          type="button"
          onClick={toggle}
          aria-label={playing ? "Pause preview" : "Play preview"}
          className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-3 text-foreground transition-colors hover:bg-white/15 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          {playing ? <Pause aria-hidden="true" className="size-3.5" /> : <Play aria-hidden="true" className="size-3.5" />}
        </button>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.05}
          value={Math.min(time, duration || 0)}
          aria-label="Seek preview"
          onChange={(e) => {
            const element = video.current;
            if (element) element.currentTime = Number(e.target.value);
            setTime(Number(e.target.value));
          }}
          className="h-1.5 min-w-0 flex-1 cursor-pointer accent-[var(--accent)]"
        />
        <span className="tabular shrink-0 text-xs text-subtle">
          {formatClock(time)} / {formatClock(duration)}
        </span>
      </div>
    </div>
  );
}
