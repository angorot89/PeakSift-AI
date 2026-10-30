"use client";

import { Film, type LucideIcon } from "lucide-react";
import { createContext, useContext, useEffect, useId, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { setMediaTime } from "@/lib/use-audio-preview";
import {
  canvasWidth,
  filmFrameCount,
  filmFrameTimes,
  fractionAt,
  rulerLabel,
  seekForKey,
  tickStep,
  ticks,
  timeAtFraction,
  timecode,
} from "@/lib/timeline";

/** Shared with the tracks: the scale (seconds ↔ pixels) and seeking. */
type Scale = { duration: number; width: number; seek: (seconds: number) => void };
const ScaleContext = createContext<Scale | null>(null);
export function useTimelineScale(): Scale {
  const scale = useContext(ScaleContext);
  if (!scale) throw new Error("useTimelineScale outside the timeline");
  return scale;
}

const LABEL_WIDTH = 104; // px: the sticky track-name column

/** Runs `onTime` on every animation frame while the video plays, and on seeks and pauses —
 * DOM updates only, never a React render per frame. */
export function useVideoClock(video: HTMLVideoElement | null, onTime: (seconds: number) => void) {
  const callback = useRef(onTime);
  useEffect(() => {
    callback.current = onTime;
  });
  useEffect(() => {
    if (!video) return;
    let frame = 0;
    const tick = () => callback.current(video.currentTime);
    const loop = () => {
      tick();
      frame = requestAnimationFrame(loop);
    };
    const start = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(loop);
    };
    const stop = () => {
      cancelAnimationFrame(frame);
      tick();
    };
    tick();
    video.addEventListener("play", start);
    video.addEventListener("pause", stop);
    video.addEventListener("seeked", tick);
    video.addEventListener("timeupdate", tick);
    video.addEventListener("loadedmetadata", tick);
    if (!video.paused) start();
    return () => {
      cancelAnimationFrame(frame);
      video.removeEventListener("play", start);
      video.removeEventListener("pause", stop);
      video.removeEventListener("seeked", tick);
      video.removeEventListener("timeupdate", tick);
      video.removeEventListener("loadedmetadata", tick);
    };
  }, [video]);
}

/** One track: its name (sticky while the canvas scrolls) and its lane(s) of items. */
export function TimelineTrack({
  label,
  icon: Icon,
  tall = false,
  children,
}: {
  label: string;
  icon: LucideIcon;
  tall?: boolean;
  children?: ReactNode;
}) {
  return (
    <div role="group" aria-label={label} className="flex border-t border-border/70">
      <div
        className="sticky left-0 z-20 flex shrink-0 items-center gap-2 border-r border-border/70 bg-surface px-3 text-caption font-medium text-muted"
        style={{ width: LABEL_WIDTH }}
      >
        <Icon aria-hidden="true" className="size-3.5 shrink-0 text-subtle" />
        <span className="truncate">{label}</span>
      </div>
      <div className={`relative grow ${tall ? "h-[4.25rem]" : "h-11"}`}>{children}</div>
    </div>
  );
}

/** Real frames from the clip, drawn once into a canvas from one hidden video (bounded count). */
export function FilmStrip({ src, times }: { src: string; times: number[] }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [ready, setReady] = useState(false);
  const key = times.join(",");
  useEffect(() => {
    const element = canvas.current;
    if (!element || !times.length) return;
    let cancelled = false;
    const video = document.createElement("video");
    video.muted = true;
    video.preload = "auto";
    video.playsInline = true;
    video.src = src;
    const context = element.getContext("2d");
    let index = 0;
    const draw = () => {
      if (cancelled || !context) return;
      const ratio = window.devicePixelRatio || 1;
      if (index === 0) {
        element.width = Math.max(1, Math.round(element.clientWidth * ratio));
        element.height = Math.max(1, Math.round(element.clientHeight * ratio));
      }
      const slot = element.width / times.length;
      const scale = Math.max(slot / (video.videoWidth || 1), element.height / (video.videoHeight || 1));
      const w = (video.videoWidth || 1) * scale;
      const h = (video.videoHeight || 1) * scale;
      context.save();
      context.beginPath();
      context.rect(index * slot, 0, slot - ratio, element.height);
      context.clip();
      context.drawImage(video, index * slot + (slot - w) / 2, (element.height - h) / 2, w, h);
      context.restore();
      index += 1;
      if (index < times.length) video.currentTime = times[index];
      else {
        setReady(true);
        video.removeAttribute("src");
        video.load();
      }
    };
    video.addEventListener("seeked", draw);
    video.addEventListener("loadedmetadata", () => {
      if (!cancelled) video.currentTime = times[0];
    });
    return () => {
      cancelled = true;
      video.removeEventListener("seeked", draw);
      video.removeAttribute("src");
      video.load();
    };
    // `key` stands for `times` (a new array every render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, key]);
  return (
    <canvas
      ref={canvas}
      aria-hidden="true"
      className={`absolute inset-y-1 left-0 h-[calc(100%-0.5rem)] w-full rounded-control bg-surface-3 transition-opacity duration-300 ${ready ? "opacity-90" : "opacity-40"}`}
    />
  );
}

/**
 * The visual map of the Short: a ruler, a playhead that follows the preview, and the tracks.
 * Clicking or dragging anywhere on the canvas seeks the preview; the playhead is a slider
 * (arrow keys ±1 s, Shift ±5 s, Home, End), so seeking never depends on a pointer.
 */
export function EditorTimeline({
  duration,
  video,
  footer,
  children,
}: {
  duration: number;
  video: HTMLVideoElement | null;
  /** Under the tracks (e.g. what the timeline does not show). */
  footer?: ReactNode;
  children: ReactNode;
}) {
  const id = useId();
  const scroller = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const playhead = useRef<HTMLDivElement>(null);
  const handle = useRef<HTMLDivElement>(null);
  const readout = useRef<HTMLSpanElement>(null);
  const [container, setContainer] = useState(0);
  const safe = Math.max(0.1, duration);
  const width = canvasWidth(safe, container);

  useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const measure = () => setContainer(Math.max(0, element.clientWidth - LABEL_WIDTH));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useVideoClock(video, (t) => {
    const x = fractionAt(t, safe) * width;
    if (playhead.current) playhead.current.style.transform = `translateX(${x}px)`;
    if (readout.current) readout.current.textContent = timecode(t);
    if (handle.current) {
      handle.current.setAttribute("aria-valuenow", t.toFixed(1));
      handle.current.setAttribute("aria-valuetext", `${timecode(t)} of ${timecode(safe)}`);
    }
  });

  const seek = (seconds: number) => {
    if (video) setMediaTime(video, Math.min(safe, Math.max(0, seconds)));
  };
  const timeAt = (clientX: number) => {
    const box = canvasRef.current?.getBoundingClientRect();
    if (!box || box.width === 0) return 0;
    return timeAtFraction((clientX - box.left) / box.width, safe);
  };

  // Seeking by pointer: press anywhere on the canvas, drag to scrub. Items stop propagation
  // for their own gestures.
  const scrubbing = useRef(false);
  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !video) return;
    scrubbing.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    seek(timeAt(event.clientX));
  }
  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (scrubbing.current) seek(timeAt(event.clientX));
  }
  function onPointerUp(event: PointerEvent<HTMLDivElement>) {
    scrubbing.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  const step = tickStep(safe, width);
  return (
    <ScaleContext.Provider value={{ duration: safe, width, seek }}>
      <section aria-labelledby={`${id}-title`} className="rounded-card border border-border bg-surface shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-5">
          <h2 id={`${id}-title`} className="text-title">
            Timeline
          </h2>
          <p className="tabular text-small text-muted" aria-hidden="true">
            <span ref={readout}>0:00.0</span>
            <span className="text-subtle"> / {timecode(safe)}</span>
          </p>
        </div>
        <div ref={scroller} className="overflow-x-auto overscroll-x-contain rounded-b-card [scrollbar-width:thin]">
          <div className="relative" style={{ width: LABEL_WIDTH + width }}>
            {/* Ruler */}
            <div className="flex">
              <div className="sticky left-0 z-20 shrink-0 border-r border-border/70 bg-surface" style={{ width: LABEL_WIDTH }} />
              <div
                className="relative h-8 cursor-pointer touch-none select-none"
                style={{ width }}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
              >
                {ticks(safe, step).map((t) => (
                  <span
                    key={t}
                    className="tabular absolute top-0 flex h-full items-end pb-1.5 pl-1 text-[0.6875rem] text-subtle"
                    style={{ left: `${fractionAt(t, safe) * 100}%` }}
                  >
                    <span aria-hidden="true" className="absolute top-0 left-0 h-2 w-px bg-white/15" />
                    {rulerLabel(t)}
                  </span>
                ))}
              </div>
            </div>
            {/* Tracks */}
            <div
              ref={canvasRef}
              className="absolute top-0 bottom-0"
              style={{ left: LABEL_WIDTH, width }}
              aria-hidden="true"
            />
            <div
              className="relative touch-pan-x"
              onPointerDown={(event) => {
                // Only empty canvas seeks (not the labels, not items).
                if ((event.target as HTMLElement).closest("[data-timeline-item], [data-track-label]")) return;
                if ((event.target as HTMLElement).closest(".sticky")) return;
                onPointerDown(event);
              }}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
            >
              {children}
            </div>
            {/* Playhead: a line across every track, and a handle on the ruler. */}
            <div
              className="pointer-events-none absolute top-0 bottom-0 z-30"
              style={{ left: LABEL_WIDTH, width: 0 }}
            >
              <div ref={playhead} className="absolute top-0 bottom-0 will-change-transform">
                <div className="absolute top-0 bottom-0 -left-px w-0.5 bg-accent shadow-[0_0_8px_rgb(249_115_22/0.6)]" />
                <div
                  ref={handle}
                  role="slider"
                  tabIndex={0}
                  aria-label="Playhead"
                  aria-valuemin={0}
                  aria-valuemax={Number(safe.toFixed(1))}
                  aria-valuenow={0}
                  aria-valuetext={`0:00.0 of ${timecode(safe)}`}
                  onKeyDown={(event) => {
                    if (!video) return;
                    const next = seekForKey(event.key, event.shiftKey, video.currentTime, safe);
                    if (next === null) return;
                    event.preventDefault();
                    seek(next);
                  }}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    onPointerDown(event);
                  }}
                  onPointerMove={onPointerMove}
                  onPointerUp={onPointerUp}
                  className="pointer-events-auto absolute top-0 -left-[22px] flex h-11 w-11 cursor-grab touch-none items-start justify-center rounded-full outline-none focus-visible:[&>span]:ring-2 focus-visible:[&>span]:ring-accent focus-visible:[&>span]:ring-offset-2 focus-visible:[&>span]:ring-offset-surface"
                >
                  <span aria-hidden="true" className="mt-0.5 block h-3.5 w-3 rounded-b-[4px] rounded-t-[2px] bg-accent" />
                </div>
              </div>
            </div>
          </div>
        </div>
        {footer ? <div className="border-t border-border/70 px-4 py-2.5 text-caption text-subtle sm:px-5">{footer}</div> : null}
      </section>
    </ScaleContext.Provider>
  );
}

/** The clip itself, across the whole Short, as a strip of real frames. */
export function VideoTrack({ src }: { src: string }) {
  const { duration, width } = useTimelineScale();
  return (
    <TimelineTrack label="Video" icon={Film}>
      <FilmStrip src={src} times={filmFrameTimes(duration, filmFrameCount(width))} />
    </TimelineTrack>
  );
}
