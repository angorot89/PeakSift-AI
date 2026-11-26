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
  ShieldCheck,
  Sparkles,
  Wand2,
  type LucideIcon,
} from "lucide-react";
import { Reveal } from "@/components/landing/reveal";

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
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-4xl font-extrabold tracking-tight text-balance sm:text-5xl">Everything in one workspace</h2>
          <p className="mt-4 text-lg text-pretty text-muted">Every tool you need to turn long videos into Shorts — no exporting between apps.</p>
        </Reveal>
        <ul className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {TOOLS.map((tool) => (
            <li
              key={tool.title}
              className="group rounded-card border border-border bg-background p-6 transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-1 hover:border-accent/30 hover:shadow-[0_18px_40px_-20px_rgb(14_18_34/0.35)]"
            >
              <span className={`flex size-11 items-center justify-center rounded-block transition-transform duration-200 group-hover:scale-110 ${tool.tint}`}>
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

const PRINCIPLES: { title: string; text: string; icon: LucideIcon }[] = [
  { title: "Every pick has a reason", text: "See why a moment made the list — the line it opens on, the turn in the story.", icon: Sparkles },
  { title: "Your words, never invented", text: "Captions, hooks and search results come from your own transcript.", icon: Captions },
  { title: "Private by default", text: "Your media stays in your workspace. Nothing is posted without your click.", icon: ShieldCheck },
  { title: "No fake numbers", text: "Analytics show only what the platforms report — never predictions.", icon: BarChart3 },
];

/** Why PeakSift: the promises behind the product, in plain statements (no invented figures). */
export function WhyPeakSift() {
  return (
    <section className="px-6 pb-24">
      <Reveal className="mx-auto grid max-w-6xl gap-10 rounded-canvas border border-border bg-surface p-8 sm:p-12 lg:grid-cols-[1fr_1.3fr] lg:items-center">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight text-balance sm:text-5xl">Built to explain itself</h2>
          <p className="mt-4 text-lg text-pretty text-muted">
            PeakSift suggests; you decide. Every choice it makes comes with the reason, and nothing happens to your
            channel without you.
          </p>
        </div>
        <ul className="grid gap-4 sm:grid-cols-2">
          {PRINCIPLES.map((principle) => (
            <li key={principle.title} className="rounded-card bg-background p-5">
              <principle.icon aria-hidden="true" className="size-6 text-accent-soft" />
              <p className="mt-3 font-display text-lg font-bold">{principle.title}</p>
              <p className="mt-1 text-muted">{principle.text}</p>
            </li>
          ))}
        </ul>
      </Reveal>
    </section>
  );
}
