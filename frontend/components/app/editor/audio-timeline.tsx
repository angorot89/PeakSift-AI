"use client";

import { useEffect, useRef, type KeyboardEvent, type PointerEvent } from "react";
import { formatClock, musicPositionAt, type MusicRequest } from "@/lib/audio-mix";
import { setMediaTime } from "@/lib/use-audio-preview";

/**
 * A compact waveform drawn on a canvas from bounded peaks (never PCM, never thousands of DOM
 * nodes). `peaks` are 0-100 % of full scale; the drawing is scaled to the loudest peak so a
 * quiet file still shows its shape. Colour comes from the element's `color` (Tailwind text-*).
 */
export function Waveform({ peaks, className = "" }: { peaks: readonly number[]; className?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const draw = () => {
      const ratio = window.devicePixelRatio || 1;
      const width = Math.max(1, Math.round(element.clientWidth * ratio));
      const height = Math.max(1, Math.round(element.clientHeight * ratio));
      element.width = width;
      element.height = height;
      const context = element.getContext("2d");
      if (!context || peaks.length === 0) return;
      context.clearRect(0, 0, width, height);
      context.fillStyle = getComputedStyle(element).color;
      const bar = Math.max(1, Math.round(2 * ratio));
      const gap = Math.max(1, Math.round(ratio));
      const count = Math.max(1, Math.floor(width / (bar + gap)));
      const top = Math.max(1, ...peaks);
      for (let i = 0; i < count; i++) {
        const from = Math.floor((i * peaks.length) / count);
        const to = Math.max(from + 1, Math.floor(((i + 1) * peaks.length) / count));
        let peak = 0;
        for (let k = from; k < to && k < peaks.length; k++) peak = Math.max(peak, peaks[k]);
        const h = Math.max(ratio, (peak / top) * height);
        context.fillRect(i * (bar + gap), (height - h) / 2, bar, h);
      }
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(element);
    return () => observer.disconnect();
  }, [peaks]);
  return <canvas ref={canvas} aria-hidden="true" className={`block h-full w-full ${className}`} />;
}

/** The peaks heard over the short: the track mapped through its start point and loops. */
export function heardPeaks(
  peaks: readonly number[],
  music: Omit<MusicRequest, "asset_id">,
  trackSeconds: number,
  duration: number,
  samples = 240,
): number[] {
  if (!peaks.length || trackSeconds <= 0 || duration <= 0) return [];
  return Array.from({ length: samples }, (_, i) => {
    const position = musicPositionAt((i / samples) * duration, music, trackSeconds, duration);
    if (position == null) return 0;
    return peaks[Math.min(peaks.length - 1, Math.floor((position / trackSeconds) * peaks.length))];
  });
}

export type TimelineCue = { key: string; label: string; at: number };

/**
 * A lightweight audio strip tied to the short's duration: the music heard (waveform), the
 * playhead (following the preview video) and sound-effect markers. Not a multitrack editor.
 *
 * The strip is a slider over the short (click or arrow keys seek the preview); each marker is
 * a slider too (drag with a pointer, or arrow keys ±0.1 s, Shift ±1 s), so placement never
 * depends on dragging — the cue list also has a time field.
 */
export function AudioTimeline({
  duration,
  video,
  musicPeaks,
  cues,
  onMoveCue,
}: {
  duration: number;
  video: HTMLVideoElement | null;
  musicPeaks: number[] | null;
  cues: TimelineCue[];
  onMoveCue: (index: number, at: number) => void;
}) {
  const strip = useRef<HTMLDivElement>(null);
  const playhead = useRef<HTMLDivElement>(null);
  const safeDuration = Math.max(0.1, duration);

  useEffect(() => {
    // Moves the playhead without re-rendering React on every frame.
    if (!video) return;
    let frame = 0;
    const place = () => {
      if (playhead.current) {
        playhead.current.style.left = `${Math.min(100, (video.currentTime / safeDuration) * 100)}%`;
      }
    };
    const loop = () => {
      place();
      frame = requestAnimationFrame(loop);
    };
    const start = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(loop);
    };
    const stop = () => {
      cancelAnimationFrame(frame);
      place();
    };
    place();
    video.addEventListener("play", start);
    video.addEventListener("pause", stop);
    video.addEventListener("seeked", place);
    video.addEventListener("timeupdate", place);
    if (!video.paused) start();
    return () => {
      cancelAnimationFrame(frame);
      video.removeEventListener("play", start);
      video.removeEventListener("pause", stop);
      video.removeEventListener("seeked", place);
      video.removeEventListener("timeupdate", place);
    };
  }, [video, safeDuration]);

  const timeAt = (clientX: number) => {
    const box = strip.current?.getBoundingClientRect();
    if (!box || box.width === 0) return 0;
    return Math.min(safeDuration, Math.max(0, ((clientX - box.left) / box.width) * safeDuration));
  };
  const seek = (t: number) => {
    if (video) setMediaTime(video, Math.min(safeDuration, Math.max(0, t)));
  };

  function onStripKey(event: KeyboardEvent<HTMLDivElement>) {
    if (!video) return;
    const step = event.shiftKey ? 5 : 1;
    const moves: Record<string, number> = { ArrowLeft: -step, ArrowRight: step, ArrowDown: -step, ArrowUp: step };
    if (event.key in moves) seek(video.currentTime + moves[event.key]);
    else if (event.key === "Home") seek(0);
    else if (event.key === "End") seek(safeDuration);
    else return;
    event.preventDefault();
  }

  function onMarkerKey(event: KeyboardEvent<HTMLButtonElement>, index: number, at: number) {
    const step = event.shiftKey ? 1 : 0.1;
    const moves: Record<string, number> = { ArrowLeft: -step, ArrowRight: step, ArrowDown: -step, ArrowUp: step };
    if (event.key in moves) onMoveCue(index, Math.round((at + moves[event.key]) * 100) / 100);
    else if (event.key === "Home") onMoveCue(index, 0);
    else if (event.key === "End") onMoveCue(index, safeDuration);
    else return;
    event.preventDefault();
    event.stopPropagation();
  }

  function onMarkerPointer(event: PointerEvent<HTMLButtonElement>, index: number) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    const move = (e: globalThis.PointerEvent) => onMoveCue(index, Math.round(timeAt(e.clientX) * 100) / 100);
    const end = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", end);
      target.removeEventListener("pointercancel", end);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", end);
    target.addEventListener("pointercancel", end);
  }

  return (
    <div className="space-y-1.5">
      <div
        ref={strip}
        role="slider"
        tabIndex={0}
        aria-label="Audio timeline playhead"
        aria-valuemin={0}
        aria-valuemax={Math.round(safeDuration * 10) / 10}
        aria-valuenow={video ? Math.round(video.currentTime * 10) / 10 : 0}
        aria-valuetext={video ? `${formatClock(video.currentTime)} of ${formatClock(safeDuration)}` : undefined}
        onPointerDown={(event) => {
          if (event.button === 0) seek(timeAt(event.clientX));
        }}
        onKeyDown={onStripKey}
        className="relative h-[4.5rem] cursor-pointer touch-none overflow-hidden rounded-lg border border-border bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent"
      >
        <div className="absolute inset-x-0 top-2 h-7 px-0.5 text-accent/70">
          {musicPeaks && musicPeaks.length ? (
            <Waveform peaks={musicPeaks} />
          ) : (
            <div className="flex h-full items-center px-2 text-[11px] text-subtle">No music</div>
          )}
        </div>
        <div className="absolute inset-x-0 bottom-0 h-7 border-t border-border/70">
          {cues.map((cue, index) => (
            <button
              key={cue.key}
              type="button"
              role="slider"
              aria-label={`Sound effect ${index + 1}: ${cue.label}`}
              aria-valuemin={0}
              aria-valuemax={Math.round(safeDuration * 100) / 100}
              aria-valuenow={cue.at}
              aria-valuetext={`${cue.label} at ${formatClock(cue.at)}`}
              onPointerDown={(event) => onMarkerPointer(event, index)}
              onKeyDown={(event) => onMarkerKey(event, index, cue.at)}
              // Clamped so a marker at the very start or end stays fully visible.
              style={{ left: `clamp(12px, ${(cue.at / safeDuration) * 100}%, calc(100% - 12px))` }}
              className="absolute top-0.5 flex h-6 min-w-6 -translate-x-1/2 cursor-grab touch-none items-center justify-center rounded-md border border-emerald-300/70 bg-emerald-400/20 px-1 text-[10px] font-semibold text-emerald-100 active:cursor-grabbing focus-visible:outline-2 focus-visible:outline-accent"
            >
              {index + 1}
            </button>
          ))}
        </div>
        <div
          ref={playhead}
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 w-px -translate-x-1/2 bg-white/90 shadow-[0_0_0_1px_rgb(0_0_0/0.35)]"
          style={{ left: "0%" }}
        />
      </div>
      <div className="tabular flex justify-between text-[11px] text-subtle">
        <span>0:00.0</span>
        <span>{formatClock(safeDuration)}</span>
      </div>
    </div>
  );
}
