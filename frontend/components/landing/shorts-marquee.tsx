import { ClipVideo } from "@/components/landing/clip-video";
import { MIN_REAL_CLIPS, REAL_CLIPS } from "@/components/landing/clips";
import { Backdrop, Person, type Platform, ShortFrame } from "@/components/landing/scene-parts";
import { Reveal } from "@/components/landing/reveal";

type Example = {
  kind: string;
  caption: string;
  platform: Platform;
  from: string;
  to: string;
  people: { tone: string; shirt: string; x: string; w: string }[];
};

/** Drawn example Shorts, one per kind of long video (illustrations, not real creators' clips). */
const EXAMPLES: Example[] = [
  { kind: "Podcast", caption: "the one thing nobody tells you", platform: "youtube", from: "#ff9a6b", to: "#c2185b", people: [{ tone: "#5c3a21", shirt: "#1d2a6b", x: "-15%", w: "130%" }] },
  { kind: "Gaming stream", caption: "I did NOT see that coming", platform: "tiktok", from: "#6b8cff", to: "#3d1a8f", people: [{ tone: "#f1c27d", shirt: "#0f766e", x: "-15%", w: "130%" }] },
  { kind: "Interview", caption: "we lost every customer in a week", platform: "instagram", from: "#f6d365", to: "#fda085", people: [{ tone: "#c68642", shirt: "#7c2d12", x: "-4%", w: "62%" }, { tone: "#f1c27d", shirt: "#1d2a6b", x: "44%", w: "62%" }] },
  { kind: "Lesson", caption: "remember this one rule", platform: "youtube", from: "#3ddc97", to: "#0f5b4a", people: [{ tone: "#8d5524", shirt: "#3d5afe", x: "-15%", w: "130%" }] },
  { kind: "Cooking show", caption: "never skip this step", platform: "tiktok", from: "#ffd84d", to: "#e65100", people: [{ tone: "#f1c27d", shirt: "#7c2d12", x: "-15%", w: "130%" }] },
  { kind: "Talk", caption: "this changed how I work", platform: "instagram", from: "#9aabff", to: "#1b1f4a", people: [{ tone: "#5c3a21", shirt: "#b91c1c", x: "-15%", w: "130%" }] },
  { kind: "Coaching call", caption: "say this instead", platform: "youtube", from: "#f48fb1", to: "#6a1b9a", people: [{ tone: "#c68642", shirt: "#0f766e", x: "-15%", w: "130%" }] },
  { kind: "Webinar", caption: "the numbers surprised us", platform: "tiktok", from: "#80deea", to: "#00695c", people: [{ tone: "#f1c27d", shirt: "#1d2a6b", x: "-15%", w: "130%" }] },
];

function ExampleCard({ example, copy }: { example: Example; copy: boolean }) {
  return (
    // The second copy only makes the loop seamless; assistive technology hears the list once.
    <li aria-hidden={copy || undefined} className="w-44 shrink-0 sm:w-52">
      <ShortFrame platform={example.platform} caption={example.caption} play className="w-full">
        <Backdrop from={example.from} to={example.to} />
        {example.people.map((person, i) => (
          <span key={`p${i}`} aria-hidden="true" className="absolute bottom-0" style={{ left: person.x, width: person.w }}>
            <Person tone={person.tone} shirt={person.shirt} className="relative bottom-0 w-full" />
          </span>
        ))}
      </ShortFrame>
      <p className="mt-3 font-display font-bold text-foreground">{example.kind}</p>
    </li>
  );
}

/**
 * "Made for": every kind of long video, shown as a slow, endless row of drawn example Shorts
 * (it pauses under the pointer or keyboard focus, and stands still under reduced motion).
 */
export function ShortsMarquee() {
  const real = REAL_CLIPS.length >= MIN_REAL_CLIPS;
  return (
    <section id="made-for" className="scroll-mt-24 overflow-hidden py-24">
      <Reveal className="mx-auto max-w-3xl px-6 text-center">
        <h2 className="text-4xl font-extrabold tracking-tight text-balance sm:text-5xl">
          Made for every kind of long video
        </h2>
        <p className="mt-4 text-lg text-pretty text-muted">
          Podcasts, streams, interviews, lessons, talks — if people are speaking, PeakSift can find the moments worth a Short.
        </p>
      </Reveal>
      <div className="relative mt-14 [mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)]">
        {real ? (
          <ul aria-label="Shorts made with PeakSift" className="lp-marquee flex w-max gap-5">
            {[...REAL_CLIPS, ...REAL_CLIPS].map((clip, i) => (
              <li key={`${clip.src}-${i}`} aria-hidden={i >= REAL_CLIPS.length || undefined} className="w-44 shrink-0 sm:w-52">
                <ClipVideo clip={clip} />
                <p className="mt-3 font-display font-bold text-foreground">{clip.kind}</p>
              </li>
            ))}
          </ul>
        ) : (
          <ul aria-label="Example Shorts (illustrations)" className="lp-marquee flex w-max gap-5">
            {[...EXAMPLES, ...EXAMPLES].map((example, i) => (
              <ExampleCard key={`${example.kind}-${i}`} example={example} copy={i >= EXAMPLES.length} />
            ))}
          </ul>
        )}
      </div>
      <p className="mt-6 text-center text-small text-subtle">
        {real ? "Real Shorts made with PeakSift." : "Illustrations of the kinds of Shorts PeakSift makes."}
      </p>
    </section>
  );
}
