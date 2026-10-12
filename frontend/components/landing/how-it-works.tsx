import { SectionHeading } from "@/components/ui/section-heading";

const steps = [
  {
    title: "Bring your long-form content",
    description:
      "Start from a stream, podcast, interview, or any long recording.",
  },
  {
    title: "Surface the strongest moments",
    description:
      "AI analyzes what was said and how it landed, then ranks the moments most worth clipping.",
  },
  {
    title: "Shape every clip",
    description:
      "Reframe for vertical and refine with captions, hooks, and sound effects.",
  },
  {
    title: "Publish where short-form lives",
    description:
      "Export clips ready for YouTube Shorts, TikTok, and Instagram Reels.",
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-20 border-t border-border py-24">
      <div className="mx-auto max-w-6xl px-6">
        <SectionHeading
          eyebrow="How it works"
          title="From long recording to ready-to-post clip"
          description="One workflow that takes you from hours of footage to short-form clips worth posting."
        />

        <ol className="mt-16 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((step, i) => (
            <li
              key={step.title}
              className="rounded-2xl border border-border bg-surface p-6 transition-colors hover:border-white/15"
            >
              <span className="font-mono text-sm text-accent-soft">
                {String(i + 1).padStart(2, "0")}
              </span>
              <h3 className="mt-4 font-medium text-foreground">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{step.description}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
