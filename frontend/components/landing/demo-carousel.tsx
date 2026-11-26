"use client";

import { ArrowRight, Captions, CheckCircle2, Crop, Pause, Play, Search, Sparkles, Wand2, type LucideIcon } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Backdrop, Cursor, delay, Person, PlatformBadge, ShortFrame } from "@/components/landing/scene-parts";

const SLIDE_MS = 7000;

/** The reduced-motion preference, live (no autoplay when it is set). */
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

// ---- Scene 1: a long video in, moments out ---------------------------------------------------

const BARS = 64;
const MARKS: [number, number][] = [
  [9, 14],
  [30, 36],
  [49, 53],
];
const marked = (i: number) => MARKS.findIndex(([a, b]) => i >= a && i <= b);
const barHeight = (i: number) => Math.min(1, 0.25 + 0.18 * Math.abs(Math.sin(i * 0.9) * Math.sin(i * 0.31)) + (marked(i) >= 0 ? 0.45 : 0.12 * Math.abs(Math.sin(i * 2.3))));

function MomentsScene() {
  return (
    <div className="absolute inset-0">
      <Backdrop from="#2a2fd6" to="#5b22c9" glow="rgb(160 175 255 / 0.35)" />
      {/* The drop box */}
      <div className="absolute top-[12%] left-1/2 flex w-[64%] -translate-x-1/2 items-center gap-[1.5cqw] rounded-[1.2cqw] border border-white/25 bg-white/15 p-[1cqw] pl-[1.8cqw] text-[1.7cqw] text-white backdrop-blur">
        <Search aria-hidden="true" className="size-[2cqw] shrink-0 opacity-80" />
        <span className="lp-type min-w-0 flex-1 truncate" style={delay(300)}>
          founder-interview-full-episode.mp4
        </span>
        <span className="lp-press rounded-[0.8cqw] bg-white px-[1.6cqw] py-[0.7cqw] font-semibold text-[#2232c8]" style={delay(1700)}>
          Find moments
        </span>
        <Cursor className="right-[3%] -bottom-[40%]" style={delay(900)} />
      </div>
      {/* The waveform, with the moments lighting up */}
      <div className="absolute top-[30%] left-1/2 flex h-[18%] w-[64%] -translate-x-1/2 items-center gap-[0.3cqw]">
        {Array.from({ length: BARS }, (_, i) => (
          <span
            key={i}
            className={`flex-1 rounded-full bg-white/30 ${marked(i) >= 0 ? "lp-glow" : ""}`}
            style={{ height: `${(barHeight(i) * 100).toFixed(2)}%`, ...(marked(i) >= 0 ? delay(2100 + marked(i) * 300) : {}) }}
          />
        ))}
      </div>
      {/* The moments, as Shorts for each platform */}
      <div className="absolute bottom-[7%] left-1/2 flex h-[42%] -translate-x-1/2 items-end gap-[2cqw]">
        <span className="lp-pop relative block aspect-video h-[78%] overflow-hidden rounded-[1cqw] ring-1 ring-white/20" style={delay(3100)}>
          <Backdrop from="#ffb86b" to="#ff6b6b" />
          <Person tone="#5c3a21" shirt="#1d2a6b" className="bottom-0 left-[14%] w-[30%]" />
          <Person tone="#f1c27d" shirt="#0f766e" className="right-[14%] bottom-0 w-[30%]" />
          <span className="absolute top-[6%] left-[5%] rounded-[0.6cqw] bg-black/50 px-[0.8cqw] text-[1.2cqw] text-white">04:12 – 04:41</span>
        </span>
        {(["youtube", "instagram", "tiktok"] as const).map((platform, i) => (
          <ShortFrame
            key={platform}
            platform={platform}
            className="lp-pop h-full"
            style={delay(3400 + i * 220)}
            caption={["nobody tells you this", "we lost everything", "do this first"][i]}
          >
            <Backdrop from={["#ff9a6b", "#6b8cff", "#3ddc97"][i]} to={["#c2185b", "#3d1a8f", "#0f5b4a"][i]} />
            <Person tone={["#5c3a21", "#f1c27d", "#c68642"][i]} shirt={["#1d2a6b", "#0f766e", "#7c2d12"][i]} className="bottom-0 -left-[15%] w-[130%]" />
          </ShortFrame>
        ))}
      </div>
    </div>
  );
}

// ---- Scene 2: smart reframe ------------------------------------------------------------------

function ReframeScene() {
  return (
    <div className="absolute inset-0">
      <Backdrop from="#1b1f4a" to="#3d1a8f" glow="rgb(120 140 255 / 0.3)" />
      <div className="absolute top-1/2 left-[6%] aspect-video w-[54%] -translate-y-1/2 overflow-hidden rounded-[1.2cqw] ring-1 ring-white/20">
        <Backdrop from="#f6d365" to="#fda085" />
        <Person tone="#5c3a21" shirt="#1d2a6b" className="bottom-0 left-[14%] w-[26%]" />
        <Person tone="#f1c27d" shirt="#0f766e" className="bottom-0 left-[56%] w-[26%]" />
        {/* The face the crop follows */}
        <span className="lp-track absolute h-[24%] w-[14%] rounded-[0.6cqw] border-2 border-[#7dffb0]">
          <span className="absolute -top-[46%] left-1/2 -translate-x-1/2 rounded-full bg-[#7dffb0] px-[0.8cqw] text-[1.1cqw] font-bold text-[#0d2a1a]">
            Face
          </span>
        </span>
        {/* The 9:16 window that becomes the Short */}
        <span className="lp-crop absolute inset-y-0 w-[36%] border-2 border-white shadow-[0_0_0_200cqw_rgb(13_15_28/0.45)]" />
      </div>
      <ArrowRight aria-hidden="true" className="absolute top-1/2 left-[63%] size-[3.5cqw] -translate-y-1/2 text-white/80" />
      <ShortFrame className="absolute top-1/2 right-[9%] h-[78%] -translate-y-1/2" caption="smart reframe" platform="tiktok">
        <span className="lp-crop-view absolute inset-y-0 left-0 w-[200%]">
          <Backdrop from="#f6d365" to="#fda085" />
          <Person tone="#5c3a21" shirt="#1d2a6b" className="bottom-0 left-[6%] w-[38%]" />
          <Person tone="#f1c27d" shirt="#0f766e" className="bottom-0 left-[56%] w-[38%]" />
        </span>
      </ShortFrame>
    </div>
  );
}

// ---- Scene 3: word-by-word captions ----------------------------------------------------------

const WORDS = ["here's", "the", "one", "thing", "nobody", "tells", "you"];
const STYLES = ["Bold", "Clean", "Karaoke", "Boxed"];

function CaptionsScene() {
  return (
    <div className="absolute inset-0">
      <Backdrop from="#0f3d3e" to="#1b1f4a" glow="rgb(61 220 151 / 0.25)" />
      <ShortFrame className="absolute top-1/2 left-[22%] h-[86%] -translate-y-1/2" platform="instagram">
        <Backdrop from="#6b8cff" to="#3d1a8f" />
        <Person tone="#c68642" shirt="#7c2d12" className="bottom-0 -left-[15%] w-[130%]" />
        <span className="absolute inset-x-[6%] bottom-[18%] flex flex-wrap justify-center gap-x-[2.5cqw] font-display text-[10cqw] leading-tight font-extrabold text-white uppercase [text-shadow:0_2px_6px_rgb(0_0_0/0.6)]">
          {WORDS.map((word, i) => (
            <span key={word} className="lp-word" style={delay(500 + i * 420)}>
              <span className={i === 4 ? "text-[#ffd84d]" : ""}>{word}</span>
            </span>
          ))}
        </span>
      </ShortFrame>
      <div className="absolute top-1/2 left-[52%] w-[30%] -translate-y-1/2 space-y-[1.2cqw]">
        <p className="text-[1.6cqw] font-semibold text-white/80">Caption style</p>
        {STYLES.map((style, i) => (
          <span
            key={style}
            className={`lp-pop flex items-center justify-between rounded-[1cqw] border px-[1.6cqw] py-[1.1cqw] text-[1.8cqw] font-semibold ${
              i === 0 ? "border-[#ffd84d] bg-[#ffd84d]/15 text-white" : "border-white/20 bg-white/10 text-white/80"
            }`}
            style={delay(200 + i * 120)}
          >
            {style}
            {i === 0 ? <CheckCircle2 aria-hidden="true" className="size-[2cqw] text-[#ffd84d]" /> : null}
          </span>
        ))}
      </div>
    </div>
  );
}

// ---- Scene 4: Auto Edit, then publish --------------------------------------------------------

const TRACKS: { label: string; blocks: [number, number, string][] }[] = [
  { label: "Video", blocks: [[0, 100, "bg-[#6b8cff]"]] },
  { label: "Captions", blocks: [[4, 30, "bg-[#ffd84d]"], [34, 62, "bg-[#ffd84d]"], [66, 96, "bg-[#ffd84d]"]] },
  { label: "Visuals", blocks: [[22, 42, "bg-[#3ddc97]"], [70, 88, "bg-[#3ddc97]"]] },
  { label: "Music", blocks: [[0, 100, "bg-[#c084fc]"]] },
];

function AutoEditScene() {
  return (
    <div className="absolute inset-0">
      <Backdrop from="#2a2fd6" to="#1b1f4a" glow="rgb(160 175 255 / 0.3)" />
      <div className="absolute top-[12%] left-[6%] w-[56%] rounded-[1.4cqw] border border-white/15 bg-[#0d0f1c]/80 p-[2cqw] backdrop-blur">
        <p className="flex items-center gap-[1cqw] text-[1.8cqw] font-semibold text-white">
          <Wand2 aria-hidden="true" className="size-[2.2cqw] text-[#9aabff]" />
          Auto Edit
          <span className="lp-fade ml-auto rounded-full bg-[#3ddc97]/20 px-[1.2cqw] text-[1.4cqw] text-[#7dffb0]" style={delay(4200)}>
            Ready
          </span>
        </p>
        <div className="relative mt-[2cqw] space-y-[1cqw]">
          {TRACKS.map((track, row) => (
            <div key={track.label} className="flex items-center gap-[1.2cqw]">
              <span className="w-[16%] text-[1.3cqw] text-white/60">{track.label}</span>
              <span className="relative h-[2.6cqw] flex-1 rounded-[0.5cqw] bg-white/5">
                {track.blocks.map(([from, to, color], i) => (
                  <span
                    key={i}
                    className={`lp-grow-x absolute inset-y-[12%] rounded-[0.4cqw] ${color}`}
                    style={{ left: `${from}%`, width: `${to - from}%`, ...delay(300 + row * 450 + i * 180) }}
                  />
                ))}
              </span>
            </div>
          ))}
          <span className="lp-playhead absolute -top-[4%] -bottom-[4%] ml-[17.5%] w-[0.25cqw] bg-white" style={delay(2200)} />
        </div>
      </div>
      <ShortFrame className="lp-pop absolute top-[12%] right-[8%] h-[76%]" style={delay(4300)} caption="do this first">
        <Backdrop from="#3ddc97" to="#0f5b4a" />
        <Person tone="#f1c27d" shirt="#1d2a6b" className="bottom-0 -left-[15%] w-[130%]" />
      </ShortFrame>
      <div className="absolute bottom-[10%] left-[6%] flex gap-[1.5cqw]">
        {(["youtube", "tiktok", "instagram"] as const).map((platform, i) => (
          <span
            key={platform}
            className="lp-pop flex items-center gap-[1cqw] rounded-[1cqw] border border-white/15 bg-white/10 py-[0.8cqw] pr-[1.6cqw] pl-[0.8cqw] text-[1.5cqw] font-medium text-white backdrop-blur"
            style={delay(4700 + i * 250)}
          >
            <PlatformBadge platform={platform} className="size-[3cqw]" />
            {["Fri 7:00 PM", "Sat 6:30 PM", "Sun 12:00 PM"][i]}
          </span>
        ))}
      </div>
    </div>
  );
}

const SLIDES: { key: string; label: string; icon: LucideIcon; Scene: () => React.ReactNode }[] = [
  { key: "moments", label: "AI moments", icon: Sparkles, Scene: MomentsScene },
  { key: "reframe", label: "Smart reframe", icon: Crop, Scene: ReframeScene },
  { key: "captions", label: "Captions", icon: Captions, Scene: CaptionsScene },
  { key: "auto-edit", label: "Auto Edit & publish", icon: Wand2, Scene: AutoEditScene },
];

/**
 * The hero's product demo: four short animated scenes (drawn, not filmed), one per feature, that
 * advance by themselves with the next one peeking in. Tabs below choose a scene; the button
 * top-left pauses. Under reduced motion nothing advances on its own.
 */
export function DemoCarousel() {
  const reduced = useReducedMotion();
  const [index, setIndex] = useState(0);
  const [cycle, setCycle] = useState(0);
  const [paused, setPaused] = useState(false);
  const playing = !paused && !reduced;

  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(() => {
      setIndex((i) => (i + 1) % SLIDES.length);
      setCycle((c) => c + 1);
    }, SLIDE_MS);
    return () => window.clearTimeout(timer);
  }, [playing, index, cycle]);

  function show(next: number) {
    setIndex((next + SLIDES.length) % SLIDES.length);
    setCycle((c) => c + 1);
  }

  return (
    <div className="mx-auto mt-14 max-w-5xl">
      <div className="relative">
        <div
          className="flex gap-4 transition-transform duration-700 ease-out-soft"
          style={{ transform: `translateX(calc(${-index} * (100% + 1rem)))` }}
        >
          {SLIDES.map((slide, i) => (
            <div
              key={slide.key}
              aria-hidden={i !== index}
              className={`@container relative aspect-[4/3] w-full shrink-0 overflow-hidden rounded-canvas shadow-[0_40px_80px_-30px_rgb(14_18_34/0.6)] ring-1 ring-white/10 transition-opacity duration-500 sm:aspect-[16/9] ${
                i === index ? "" : "opacity-60"
              }`}
            >
              {i === index ? <slide.Scene key={cycle} /> : <slide.Scene />}
              <span className="absolute right-[2%] bottom-[3%] text-[1.3cqw] text-white/60">Illustration</span>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setPaused((p) => !p)}
          aria-label={playing ? "Pause the demo" : "Play the demo"}
          className="absolute top-3 left-3 flex size-9 items-center justify-center rounded-full bg-black/40 text-white backdrop-blur transition-colors hover:bg-black/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
        >
          {playing ? <Pause aria-hidden="true" className="size-4" /> : <Play aria-hidden="true" className="size-4" />}
        </button>
        <button
          type="button"
          onClick={() => show(index + 1)}
          aria-label="Next scene"
          className="absolute top-1/2 -right-4 flex size-11 -translate-y-1/2 items-center justify-center rounded-full bg-[#0d0f1c] text-white shadow-lg ring-1 ring-white/20 transition-transform hover:scale-105 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white sm:-right-5"
        >
          <ArrowRight aria-hidden="true" className="size-5" />
        </button>
      </div>

      <div role="group" aria-label="Demo scenes" className="mt-6 flex flex-wrap justify-center gap-2">
        {SLIDES.map((slide, i) => {
          const active = i === index;
          return (
            <button
              key={slide.key}
              type="button"
              aria-pressed={active}
              onClick={() => show(i)}
              className={`relative inline-flex min-h-10 items-center gap-2 overflow-hidden rounded-control border px-3 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                active ? "border-accent bg-accent text-white" : "border-border bg-surface text-foreground hover:border-accent/50"
              }`}
            >
              {active && playing ? (
                <span
                  key={cycle}
                  aria-hidden="true"
                  className="lp-progress absolute inset-x-0 bottom-0 h-0.5 bg-white/80"
                  style={{ animationDuration: `${SLIDE_MS}ms` }}
                />
              ) : null}
              <slide.icon aria-hidden="true" className="size-4" />
              {slide.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
