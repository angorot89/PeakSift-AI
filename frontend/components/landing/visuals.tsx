"use client";

import { Check, Globe, Languages, MessageCircle, Music2, Sparkles } from "lucide-react";
import { AutoEditScene, CaptionsScene, MomentsScene, ReframeScene } from "@/components/landing/demo-carousel";
import { EditArt, FindArt, LearnArt, Panel, PublishArt } from "@/components/landing/feature-rows";
import { Reveal } from "@/components/landing/reveal";
import { Backdrop, delay, Person, ShortFrame } from "@/components/landing/scene-parts";

function AudioArt() {
  const voice = Array.from({ length: 40 }, (_, i) => 30 + 60 * Math.abs(Math.sin(i * 0.7) * Math.sin(i * 0.23)));
  return (
    <Panel>
      <p className="text-title">Sound</p>
      {[
        { label: "Voice", color: "bg-[#6b8cff]", bars: voice, dip: false },
        { label: "Music", color: "bg-[#c084fc]", bars: voice.map((_, i) => 55 + 10 * Math.sin(i * 0.4)), dip: true },
      ].map((track, row) => (
        <div key={track.label} className="mt-4">
          <p className="mb-1.5 flex items-center gap-1.5 text-small text-subtle">
            {row ? <Music2 aria-hidden="true" className="size-3.5" /> : null}
            {track.label}
            {track.dip ? <span className="ml-auto rounded-full bg-violet/20 px-2 text-caption text-violet-200">Ducks under the voice</span> : null}
          </p>
          <div className="flex h-16 items-center gap-[3px] rounded-block bg-surface px-2">
            {track.bars.map((height, i) => (
              <span
                key={i}
                className={`lp-grow flex-1 rounded-full ${track.color}`}
                style={{ height: `${(track.dip && i > 8 && i < 30 ? height * 0.35 : height).toFixed(1)}%`, ...delay(150 + i * 25 + row * 300) }}
              />
            ))}
          </div>
        </div>
      ))}
      <p className="lp-pop mt-4 mb-4 inline-flex rounded-full bg-success/15 px-3 py-1 text-small font-medium text-emerald-200" style={delay(1600)}>
        Mixed to −14 LUFS
      </p>
    </Panel>
  );
}

function BrandArt() {
  const colours = ["#3d5afe", "#ffd84d", "#0d0f1c"];
  return (
    <Panel>
      <div className="flex items-center gap-6">
        <ShortFrame className="w-36 shrink-0 sm:w-40" caption="your brand, every time">
          <Backdrop from="#3d5afe" to="#0d0f1c" />
          <span aria-hidden="true" className="absolute bottom-0 -left-[15%] w-[130%]">
            <Person tone="#c68642" shirt="#ffd84d" className="relative w-full" />
          </span>
          <span className="lp-pop absolute top-[4%] left-[6%] rounded-md bg-white px-2 py-0.5 font-display text-[11cqw] font-extrabold text-[#3d5afe]" style={delay(900)}>
            LOGO
          </span>
        </ShortFrame>
        <div className="min-w-0 flex-1 space-y-3">
          <p className="text-small text-subtle">Brand colours</p>
          <div className="flex gap-2">
            {colours.map((colour, i) => (
              <span key={colour} className="lp-pop size-10 rounded-full ring-2 ring-white/20" style={{ background: colour, ...delay(200 + i * 150) }} />
            ))}
          </div>
          <p className="pt-2 text-small text-subtle">Templates</p>
          {["Interview template", "Tips template"].map((name, i) => (
            <span key={name} className="lp-pop flex items-center gap-2 rounded-control border border-border bg-surface px-3 py-2 text-sm text-foreground" style={delay(700 + i * 200)}>
              <Check aria-hidden="true" className="size-4 text-success" />
              {name}
            </span>
          ))}
        </div>
      </div>
      <div className="h-6" />
    </Panel>
  );
}

function AskArt() {
  return (
    <Panel>
      <p className="flex items-center gap-2 text-title">
        <Sparkles aria-hidden="true" className="size-4 text-accent-soft" />
        Ask PeakSift
      </p>
      <div className="mt-4 space-y-3">
        <p className="lp-pop ml-auto w-fit max-w-[80%] rounded-card rounded-br-md bg-accent-fill px-4 py-2.5 text-sm text-white" style={delay(200)}>
          What should I post next?
        </p>
        <div className="lp-pop max-w-[88%] rounded-card rounded-bl-md border border-border bg-surface px-4 py-3 text-sm text-foreground" style={delay(1100)}>
          Your top pick in “Founder interview” is ready to edit: it opens on a clear question. Want to make it a Short?
          <span className="mt-3 flex gap-2">
            <span className="rounded-control bg-accent-fill px-3 py-1.5 text-small font-semibold text-white">Create Short</span>
            <span className="rounded-control border border-border px-3 py-1.5 text-small text-muted">Open moments</span>
          </span>
        </div>
      </div>
      <p className="mt-4 mb-4 flex items-center gap-1.5 text-small text-subtle">
        <MessageCircle aria-hidden="true" className="size-3.5" />
        Answers come from your own projects.
      </p>
    </Panel>
  );
}

function MoroccoArt() {
  return (
    <Panel>
      <div className="inline-flex rounded-control border border-border bg-surface p-1 text-sm">
        <span className="flex items-center gap-1.5 rounded-[0.375rem] px-3 py-1.5 text-muted">
          <Globe aria-hidden="true" className="size-4" />
          Global
        </span>
        <span className="lp-pop flex items-center gap-1.5 rounded-[0.375rem] bg-background px-3 py-1.5 font-medium text-foreground ring-1 ring-border-strong" style={delay(300)}>
          <Languages aria-hidden="true" className="size-4" />
          Morocco Mode
        </span>
      </div>
      <ul className="mt-5 space-y-2">
        {[
          "Hook ideas from your own words, across scripts",
          "Curated Moroccan formats on top of every Global tool",
          "Your local visuals and sounds first, Global kept",
        ].map((line, i) => (
          <li key={line} className="lp-pop flex items-center gap-2 rounded-control border border-border bg-surface px-3 py-2.5 text-sm text-foreground" style={delay(700 + i * 250)}>
            <Check aria-hidden="true" className="size-4 shrink-0 text-success" />
            {line}
          </li>
        ))}
      </ul>
      <div className="h-6" />
    </Panel>
  );
}

const SCENES = { moments: MomentsScene, reframe: ReframeScene, captions: CaptionsScene, "auto-edit": AutoEditScene };
const ARTS = { find: FindArt, edit: EditArt, publish: PublishArt, learn: LearnArt, audio: AudioArt, brand: BrandArt, ask: AskArt, morocco: MoroccoArt };

export type VisualName = keyof typeof SCENES | keyof typeof ARTS;

/**
 * One of the website's drawn illustrations by name: a full demo scene (in a 16:9 frame) or a
 * panel. It plays when it scrolls into view.
 */
export function Visual({ name, className = "" }: { name: VisualName; className?: string }) {
  if (name in SCENES) {
    const Scene = SCENES[name as keyof typeof SCENES];
    return (
      <Reveal scene className={className}>
        <div className="@container relative aspect-[4/3] overflow-hidden rounded-canvas shadow-[0_40px_80px_-30px_rgb(14_18_34/0.6)] ring-1 ring-white/10 sm:aspect-video">
          <Scene />
          <span className="absolute right-[2%] bottom-[3%] text-[1.3cqw] text-white/60">Illustration</span>
        </div>
      </Reveal>
    );
  }
  const Art = ARTS[name as keyof typeof ARTS];
  return (
    <Reveal scene className={className}>
      <Art />
    </Reveal>
  );
}
