"use client";

import { useEffect, useRef } from "react";
import { musicPositionAt, type MusicRequest } from "@/lib/audio-mix";

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
