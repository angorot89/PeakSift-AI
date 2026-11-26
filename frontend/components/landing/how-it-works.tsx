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
          title="From long recording to ready-to-post clip"
          description="One workflow that takes you from hours of footage to short-form clips worth posting."
        />

        {/* A real sequence: each step sits on one continuous line, like clips on a track. */}
        <ol className="mt-16 grid gap-x-6 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((step, i) => (
            <li key={step.title} className="border-t-2 border-border-strong pt-5 first:border-accent">
              <span className="tabular text-sm text-subtle">Step {i + 1}</span>
              <h3 className="mt-2 text-lg font-semibold text-foreground">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{step.description}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
