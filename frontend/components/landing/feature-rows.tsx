import { Check, MessageCircle, Search, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { Reveal } from "@/components/landing/reveal";
import { Backdrop, delay, Person, PlatformBadge } from "@/components/landing/scene-parts";
import { ButtonLink } from "@/components/ui/button-link";

/** A dark panel in the workspace's look that holds one illustration (never real data). */
function Panel({ children }: { children: ReactNode }) {
  return (
    <div className="theme-dark relative overflow-hidden rounded-canvas border border-white/10 p-5 shadow-[0_30px_60px_-30px_rgb(14_18_34/0.55)] sm:p-7">
      {children}
      <span className="absolute right-4 bottom-3 text-caption text-subtle">Illustration</span>
    </div>
  );
}

function FindArt() {
  return (
    <Panel>
      <div className="flex items-center gap-2 rounded-control border border-border-strong bg-background px-3 py-2.5 text-sm text-muted">
        <Search aria-hidden="true" className="size-4 text-subtle" />
        <span className="lp-type" style={delay(300)}>
          the part where I explain pricing
        </span>
      </div>
      <ul className="mt-4 space-y-2">
        {[
          ["12:40", "“So here's how we price it — and why it's not per seat.”"],
          ["31:02", "“Pricing was the hardest call we made all year.”"],
        ].map(([at, line], i) => (
          <li key={at} className="lp-pop flex gap-3 rounded-block border border-border bg-surface p-3" style={delay(1500 + i * 250)}>
            <span className="tabular h-fit rounded-full bg-accent/20 px-2 py-0.5 text-caption font-semibold text-accent-soft">{at}</span>
            <span className="text-sm text-foreground">{line}</span>
          </li>
        ))}
      </ul>
      <p className="mt-4 mb-4 text-small text-subtle">Real lines from your transcript, with where they were said.</p>
    </Panel>
  );
}

function EditArt() {
  return (
    <Panel>
      <div className="flex items-center justify-center gap-5">
        <div className="relative aspect-[9/16] w-40 overflow-hidden rounded-block border border-border-strong sm:w-44">
          <Backdrop from="#6b8cff" to="#3d1a8f" />
          <span aria-hidden="true" className="absolute bottom-0 -left-[15%] w-[130%]">
            <Person tone="#c68642" shirt="#7c2d12" className="relative w-full" />
          </span>
          <p className="absolute inset-x-3 bottom-[20%] flex flex-wrap justify-center gap-x-1.5 text-center font-display text-lg leading-tight font-extrabold text-white uppercase [text-shadow:0_2px_6px_rgb(0_0_0/0.6)]">
            {["this", "is", "the", "price"].map((word, i) => (
              <span key={word} className={`lp-word ${i >= 2 ? "text-[#ffd84d]" : ""}`} style={delay(400 + i * 380)}>
                {word}
              </span>
            ))}
          </p>
        </div>
        <ul className="space-y-2 text-sm">
          {["Smart reframe", "Word-by-word captions", "Your brand", "Music & ducking"].map((item, i) => (
            <li key={item} className="lp-pop flex items-center gap-2 rounded-control border border-border bg-surface px-3 py-2 text-foreground" style={delay(1800 + i * 200)}>
              <Check aria-hidden="true" className="size-4 text-success" />
              {item}
            </li>
          ))}
        </ul>
      </div>
      <div className="h-6" />
    </Panel>
  );
}

function PublishArt() {
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri"];
  const posts: Record<string, [string, string, "youtube" | "tiktok" | "instagram", number]> = {
    Tue: ["YouTube", "bg-danger/20 text-rose-200", "youtube", 0],
    Thu: ["TikTok", "bg-info/20 text-sky-200", "tiktok", 1],
    Fri: ["Reels", "bg-violet/20 text-violet-200", "instagram", 2],
  };
  return (
    <Panel>
      <p className="text-title">This week</p>
      <ul className="mt-4 grid grid-cols-5 gap-2">
        {days.map((day) => (
          <li key={day} className="flex min-h-32 flex-col gap-2 rounded-block border border-border bg-surface p-2">
            <span className="text-caption text-subtle">{day}</span>
            {posts[day] ? (
              <span className={`lp-pop rounded-control px-1.5 py-1 text-caption font-medium ${posts[day][1]}`} style={delay(500 + posts[day][3] * 450)}>
                <PlatformBadge platform={posts[day][2]} className="mb-1 size-4" />
                7:00 PM
                <span className="block font-semibold">{posts[day][0]}</span>
              </span>
            ) : (
              <span className="rounded-control border border-dashed border-border-strong px-1.5 py-1 text-caption text-subtle">Free slot</span>
            )}
          </li>
        ))}
      </ul>
      <div className="h-6" />
    </Panel>
  );
}

function LearnArt() {
  const bars = [38, 52, 44, 71, 63, 88];
  return (
    <Panel>
      <p className="text-title">How your Shorts are doing</p>
      <div className="mt-4 flex h-32 items-end gap-2" aria-hidden="true">
        {bars.map((height, index) => (
          <span
            key={index}
            className={`lp-grow flex-1 rounded-t-md ${index === bars.length - 1 ? "bg-accent" : "bg-surface-3"}`}
            style={{ height: `${height}%`, ...delay(200 + index * 140) }}
          />
        ))}
      </div>
      <div className="lp-pop mt-5 flex gap-3 rounded-block border border-border bg-surface p-3" style={delay(1400)}>
        <MessageCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-accent-soft" />
        <p className="text-sm text-foreground">
          <span className="font-semibold">Ask PeakSift:</span> “Which of my moments should I post next?”
        </p>
      </div>
      <div className="h-6" />
    </Panel>
  );
}

const ROWS: { id: string; tag: string; title: string; text: string; points: string[]; art: ReactNode }[] = [
  {
    id: "find",
    tag: "AI moments",
    title: "Turn a long recording into clips in minutes",
    text: "PeakSift reads what was said and ranks the moments worth clipping — and tells you why each one made the list. Looking for something specific? Ask for it in your own words.",
    points: ["Ranked moments with the reason for each", "Find Clips: search your video in plain language", "Works with streams, podcasts, interviews and talks"],
    art: <FindArt />,
  },
  {
    id: "edit",
    tag: "Editing",
    title: "Vertical, captioned and on-brand in a few clicks",
    text: "Smart reframe keeps faces in the frame, captions follow every word, and your colours, logo and templates go on every Short. Or let Auto Edit make the first cut for you.",
    points: ["Smart reframe instead of black bars", "Word-by-word captions and an opening hook", "Brand Studio templates, B-roll, music and sound"],
    art: <EditArt />,
  },
  {
    id: "publish",
    tag: "Publishing",
    title: "Post to YouTube, TikTok and Instagram from one place",
    text: "Publish now or schedule it. Set your posting times once and PeakSift fills the next free slot — nothing goes out before its time.",
    points: ["YouTube Shorts, TikTok and Instagram Reels", "A calendar with your weekly posting slots", "Every Short and its status in one library"],
    art: <PublishArt />,
  },
  {
    id: "learn",
    tag: "Analytics",
    title: "See which Shorts work — and what to make next",
    text: "Views and watch time for every Short you published, compared with your own recent uploads. Ask PeakSift what to post next and it answers from your projects.",
    points: ["Performance for every published Short", "Patterns from your own recent uploads", "Ask PeakSift for your next step"],
    art: <LearnArt />,
  },
];

/** What PeakSift does, one feature per row: words on one side, a picture on the other. */
export function FeatureRows() {
  return (
    <section id="features" className="scroll-mt-24 px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-4xl font-extrabold tracking-tight text-balance sm:text-5xl">From one long video to a week of Shorts</h2>
          <p className="mt-4 text-lg text-pretty text-muted">You already made the content. PeakSift makes sure people see the best of it.</p>
        </Reveal>
        <div className="mt-20 space-y-24">
          {ROWS.map((row, index) => (
            <article id={row.id} key={row.id} className="grid scroll-mt-28 items-center gap-10 lg:grid-cols-2 lg:gap-16">
              <Reveal className={index % 2 ? "lg:order-2" : ""}>
                <span className="inline-flex rounded-full border border-accent/30 bg-accent/10 px-3 py-1 text-small font-semibold text-accent-soft">
                  {row.tag}
                </span>
                <h3 className="mt-4 font-display text-3xl leading-tight font-extrabold tracking-tight text-balance sm:text-4xl">{row.title}</h3>
                <p className="mt-4 text-lg leading-relaxed text-pretty text-muted">{row.text}</p>
                <ul className="mt-6 space-y-2.5">
                  {row.points.map((point) => (
                    <li key={point} className="flex items-start gap-2.5 text-foreground">
                      <Check aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-accent-soft" />
                      {point}
                    </li>
                  ))}
                </ul>
                <ButtonLink href="/register" variant="secondary" className="mt-8">
                  <Sparkles aria-hidden="true" />
                  Try it
                </ButtonLink>
              </Reveal>
              <Reveal scene delay={120} className={index % 2 ? "lg:order-1" : ""}>
                {row.art}
              </Reveal>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
