import type { ReactNode } from "react";
import { SectionHeading } from "@/components/ui/section-heading";

function Icon({ children }: { children: ReactNode }) {
  return (
    <span className="flex size-10 items-center justify-center rounded-lg border border-border bg-white/[0.03] text-accent-soft">
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="size-5"
        aria-hidden="true"
      >
        {children}
      </svg>
    </span>
  );
}

const features = [
  {
    title: "Moment detection",
    description: "AI reads your content to find the highlights, punchlines, and turning points.",
    icon: <path d="M3 17l5-6 4 4 4-7 5 9" />,
  },
  {
    title: "Clip ranking",
    description: "Candidates are ordered so the strongest moments are the first ones you see.",
    icon: <path d="M6 20V10M12 20V4M18 20v-6" />,
  },
  {
    title: "Vertical reframing",
    description: "Turn widescreen footage into clean 9:16 clips for mobile feeds.",
    icon: (
      <>
        <rect x="7" y="3" width="10" height="18" rx="2" />
        <path d="M10 18h4" />
      </>
    ),
  },
  {
    title: "Captions & hooks",
    description: "Readable captions and openers that give viewers a reason to stay.",
    icon: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="M7 13h4M13 13h4M7 16h7" />
      </>
    ),
  },
  {
    title: "Sound & creator assets",
    description: "Sound effects and creator assets to give every clip more energy.",
    icon: (
      <>
        <path d="M9 18V6l10-2v12" />
        <circle cx="6.5" cy="18" r="2.5" />
        <circle cx="16.5" cy="16" r="2.5" />
      </>
    ),
  },
  {
    title: "Platform-ready export",
    description: "Export clips sized and ready for YouTube Shorts, TikTok, and Instagram Reels.",
    icon: <path d="M12 15V3m0 0l-4 4m4-4l4 4M5 14v5a2 2 0 002 2h10a2 2 0 002-2v-5" />,
  },
];

export function PlatformFeatures() {
  return (
    <section id="platform" className="scroll-mt-20 border-t border-border py-24">
      <div className="mx-auto max-w-6xl px-6">
        <SectionHeading
          eyebrow="The platform"
          title="More than a timestamp finder"
          description="PeakSift is being built as a complete short-form creation platform — from finding the moment to shipping the clip."
        />

        <ul className="mt-16 grid gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
          {features.map((feature) => (
            <li key={feature.title} className="bg-background p-8">
              <Icon>{feature.icon}</Icon>
              <h3 className="mt-5 font-medium text-foreground">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{feature.description}</p>
            </li>
          ))}
        </ul>

        <p className="mt-6 text-center text-sm text-subtle">
          PeakSift is in active development. The capabilities above describe the
          platform we&apos;re building.
        </p>
      </div>
    </section>
  );
}
