import {
  AudioLines,
  BarChart3,
  CalendarClock,
  Captions,
  Crop,
  Image as ImageIcon,
  Languages,
  MessageCircle,
  Palette,
  Search,
  Sparkles,
  Wand2,
  type LucideIcon,
} from "lucide-react";

const TOOLS: { title: string; text: string; icon: LucideIcon; tint: string }[] = [
  { title: "AI moments", text: "The strongest moments of a long video, ranked, with the reason for each.", icon: Sparkles, tint: "bg-[#3d5afe]/10 text-[#2f4ae0]" },
  { title: "Find Clips", text: "Describe a moment in your own words and jump to where it was said.", icon: Search, tint: "bg-[#3d5afe]/10 text-[#2f4ae0]" },
  { title: "Auto Edit", text: "A first cut made for you: framing, captions, hook and visuals.", icon: Wand2, tint: "bg-violet-500/10 text-violet-700" },
  { title: "Smart reframe", text: "Follows faces to turn widescreen footage into clean 9:16.", icon: Crop, tint: "bg-violet-500/10 text-violet-700" },
  { title: "Dynamic captions", text: "Word-by-word captions with the spoken word highlighted.", icon: Captions, tint: "bg-amber-500/15 text-amber-800" },
  { title: "B-roll & visuals", text: "Your own images and clips, matched to what is being said.", icon: ImageIcon, tint: "bg-amber-500/15 text-amber-800" },
  { title: "Music & sound", text: "Your music under the voice, ducking, effects and loudness.", icon: AudioLines, tint: "bg-rose-500/10 text-rose-700" },
  { title: "Brand Studio", text: "Your colours, logo and templates on every Short.", icon: Palette, tint: "bg-rose-500/10 text-rose-700" },
  { title: "Schedule & publish", text: "YouTube Shorts, TikTok and Instagram Reels, now or later.", icon: CalendarClock, tint: "bg-emerald-500/10 text-emerald-700" },
  { title: "Analytics", text: "How every published Short is doing, compared with your own uploads.", icon: BarChart3, tint: "bg-emerald-500/10 text-emerald-700" },
  { title: "Ask PeakSift", text: "An assistant that answers from your projects, not from guesswork.", icon: MessageCircle, tint: "bg-sky-500/10 text-sky-700" },
  { title: "Morocco Mode", text: "Darija-aware hooks and Moroccan formats, on top of everything else.", icon: Languages, tint: "bg-sky-500/10 text-sky-700" },
];

/** Every tool, one card each. */
export function Toolkit() {
  return (
    <section id="toolkit" className="scroll-mt-24 border-t border-border bg-surface px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-4xl font-extrabold tracking-tight text-balance sm:text-5xl">Everything in one workspace</h2>
          <p className="mt-4 text-lg text-pretty text-muted">Every tool you need to turn long videos into Shorts — no exporting between apps.</p>
        </div>
        <ul className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {TOOLS.map((tool) => (
            <li key={tool.title} className="rounded-card border border-border bg-background p-6">
              <span className={`flex size-11 items-center justify-center rounded-block ${tool.tint}`}>
                <tool.icon aria-hidden="true" className="size-5" />
              </span>
              <h3 className="mt-4 font-display text-lg font-bold">{tool.title}</h3>
              <p className="mt-1.5 text-muted">{tool.text}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/** Why PeakSift, as a bento of plain statements (no invented figures). */
export function WhyPeakSift() {
  return (
    <section className="px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <h2 className="mx-auto max-w-2xl text-center text-4xl font-extrabold tracking-tight text-balance sm:text-5xl">
          Built to explain itself
        </h2>
        <div className="mt-14 grid gap-4 lg:grid-cols-[1.5fr_1fr_1fr] lg:grid-rows-2">
          <div className="flex flex-col justify-end rounded-canvas bg-[linear-gradient(150deg,#3d5afe,#6f4bff)] p-8 text-white lg:row-span-2">
            <p className="font-display text-4xl leading-tight font-extrabold sm:text-5xl">Every pick comes with a reason.</p>
            <p className="mt-4 max-w-md text-lg text-white/90">
              PeakSift shows why a moment made the list — the line it opens on, the turn in the story — so you decide, not a
              score.
            </p>
          </div>
          <div className="flex flex-col justify-end rounded-canvas bg-[#e3f25c] p-7 text-[#15170a] lg:row-span-2">
            <p className="font-display text-3xl leading-tight font-extrabold">Your words, never invented.</p>
            <p className="mt-3 text-[#15170a]/80">Captions, hooks and search results come from your own transcript.</p>
          </div>
          <div className="rounded-canvas bg-[#141833] p-7 text-white">
            <p className="font-display text-2xl font-extrabold">Private by default</p>
            <p className="mt-2 text-white/75">Your media stays in your workspace. Nothing is published without your click.</p>
          </div>
          <div className="rounded-canvas border border-accent/20 bg-accent/10 p-7">
            <p className="font-display text-2xl font-extrabold text-accent-soft">No fake numbers</p>
            <p className="mt-2 text-muted">Analytics show only what the platforms report — never predictions.</p>
          </div>
        </div>
      </div>
    </section>
  );
}
