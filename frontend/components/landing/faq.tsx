import { ChevronDown } from "lucide-react";

const QUESTIONS: { q: string; a: string }[] = [
  {
    q: "Is PeakSift free?",
    a: "There is a Free plan, and paid plans from $12 a month. During early access every account has every tool for free — see Pricing.",
  },
  {
    q: "Which platforms can I post to?",
    a: "YouTube Shorts, TikTok and Instagram Reels. You connect each account yourself, and nothing is posted without your click.",
  },
  {
    q: "What kind of videos work?",
    a: "Any long recording with speech: streams, podcasts, interviews, talks and lessons. Upload MP4, MOV or WebM.",
  },
  {
    q: "How does PeakSift find the moments?",
    a: "It transcribes your video, reads what was said and ranks the moments worth clipping, with the reason for each. The ranking is editorial judgement, not a prediction of views.",
  },
  {
    q: "Do I need editing experience?",
    a: "No. Auto Edit makes a first cut for you, and every setting — framing, captions, visuals, sound, brand — is one click to change.",
  },
  {
    q: "Can I schedule posts?",
    a: "Yes. Pick a time, or set your weekly posting slots once and PeakSift fills the next free one. You can move or cancel a post until it goes out.",
  },
  {
    q: "Does it work in other languages?",
    a: "Transcription and captions work in many languages, including Arabic. Morocco Mode adds Darija-aware hooks and Moroccan formats on top of everything else.",
  },
];

/** Frequently asked questions, each one a native disclosure (keyboard and screen readers for free). */
export function Faq() {
  return (
    <section id="faq" className="scroll-mt-24 border-t border-border bg-surface px-6 py-24">
      <div className="mx-auto max-w-3xl">
        <h2 className="text-center text-4xl font-extrabold tracking-tight sm:text-5xl">Frequently asked questions</h2>
        <div className="mt-12 divide-y divide-border rounded-canvas border border-border bg-background">
          {QUESTIONS.map(({ q, a }) => (
            <details key={q} className="group px-6">
              <summary className="flex min-h-16 cursor-pointer list-none items-center justify-between gap-4 py-4 font-display text-lg font-bold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden">
                {q}
                <ChevronDown aria-hidden="true" className="size-5 shrink-0 text-subtle transition-transform group-open:rotate-180" />
              </summary>
              <p className="pb-5 leading-relaxed text-muted">{a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
