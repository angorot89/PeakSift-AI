"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { VideoClockContext } from "@/components/app/editor/caption-layer";
import { PreviewControls } from "@/components/app/editor/preview-controls";
import type { Layout } from "@/lib/edits";
import { clampedCenter, cropCenterAt, cropGeometry, type CropKeyframe } from "@/lib/reframe";

/** The 9:16 frame both the live preview and the rendered short sit in. */
export function NineBySixteenFrame({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div
      role="group"
      aria-label={label}
      // Sized by width with a locked 9:16 ratio, capped so the frame never exceeds
      // min(64vh, 600px) in height (on desktop, what is left below the header, so the controls
      // stay on screen): it stays exactly 9:16 at every width, and fills the screen in full screen.
      className="relative mx-auto aspect-[9/16] w-full max-w-[calc(min(64vh,600px)*0.5625)] overflow-hidden lg:max-w-[calc(min(max(100dvh-25rem,22rem),600px)*0.5625)] rounded-[22px] border border-white/12 bg-black shadow-[0_30px_80px_-30px_rgb(0_0_0/0.9)] ring-1 ring-black [:fullscreen_&]:max-w-[calc((100dvh-5rem)*0.5625)]"
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
  /** Receives the playing preview video (the editor's audio preview follows its clock). */
  onVideo?: (video: HTMLVideoElement | null) => void;
};

/**
 * A lightweight browser simulation of the chosen settings, played from the generated clip.
 * It shows layout and caption placement; it is labelled as a preview because the server's
 * FFmpeg render (blur strength, exact glyph shapes) is the authoritative result.
 */
/** The frame plus its controls; this is what goes full screen, so overlays come along. */
function PreviewShell({ video, children }: { video: HTMLVideoElement | null; children: ReactNode }) {
  const [shell, setShell] = useState<HTMLDivElement | null>(null);
  return (
    <div
      ref={setShell}
      className="space-y-2 [&:fullscreen]:flex [&:fullscreen]:flex-col [&:fullscreen]:items-center [&:fullscreen]:justify-center [&:fullscreen]:bg-black [&:fullscreen]:p-4"
    >
      {children}
      <PreviewControls video={video} fullscreenTarget={shell} />
    </div>
  );
}

function togglePlayback(element: HTMLVideoElement | null) {
  if (!element) return;
  if (element.paused || element.ended) void element.play().catch(() => {});
  else element.pause();
}

export function PreviewStage({ clipSrc, layout, overlay, onVideo }: PreviewProps) {
  const front = useRef<HTMLVideoElement | null>(null);
  const back = useRef<HTMLVideoElement>(null);
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const frontRef = useCallback((node: HTMLVideoElement | null) => {
    front.current = node;
    setVideo(node);
  }, []);
  useEffect(() => {
    onVideo?.(front.current);
    return () => onVideo?.(null);
  }, [onVideo]);

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
    <PreviewShell video={video}>
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
        ref={frontRef}
        playsInline
        preload="metadata"
        src={`${clipSrc}#t=0.1`}
        aria-label="Preview playback"
        onClick={() => togglePlayback(front.current)}
        className={`absolute inset-0 size-full cursor-pointer ${layout === "center_crop" ? "object-cover" : "object-contain"}`}
      />
      <VideoClockContext.Provider value={front}>{overlay}</VideoClockContext.Provider>
    </NineBySixteenFrame>
    </PreviewShell>
  );
}

export type Framing =
  | { kind: "path"; keyframes: CropKeyframe[] }
  | { kind: "focus"; x: number; y: number }
  | { kind: "center" };

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
  onVideo,
}: {
  clipSrc: string;
  sourceWidth: number;
  sourceHeight: number;
  framing: Framing;
  /** Text layers in output-frame coordinates: they never move with the crop. */
  overlay?: ReactNode;
  badge?: ReactNode;
  onVideo?: (video: HTMLVideoElement | null) => void;
}) {
  const video = useRef<HTMLVideoElement | null>(null);
  const [element, setElement] = useState<HTMLVideoElement | null>(null);
  const videoRef = useCallback((node: HTMLVideoElement | null) => {
    video.current = node;
    setElement(node);
  }, []);
  useEffect(() => {
    onVideo?.(video.current);
    return () => onVideo?.(null);
  }, [onVideo]);
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

  return (
    <PreviewShell video={element}>
      <NineBySixteenFrame label="Live preview of the edit settings">
        <video
          ref={videoRef}
          playsInline
          preload="metadata"
          src={`${clipSrc}#t=0.1`}
          aria-label="Preview playback"
          onClick={() => togglePlayback(video.current)}
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
    </PreviewShell>
  );
}
