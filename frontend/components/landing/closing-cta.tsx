import { ButtonLink } from "@/components/ui/button-link";

export function ClosingCta() {
  return (
    <section id="get-started" className="scroll-mt-20 border-t border-border py-24">
      <div className="mx-auto max-w-6xl px-6">
        <div className="relative overflow-hidden rounded-3xl border border-border bg-surface px-6 py-16 text-center sm:px-16">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_60%_80%_at_50%_100%,rgb(249_115_22/0.18),transparent_70%)]"
          />
          <div className="relative">
            <h2 className="mx-auto max-w-2xl text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
              Your next long-form video already has its best clips in it.
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-pretty text-muted sm:text-lg">
              PeakSift is in early development. Video upload and AI clip
              detection are next on the roadmap.
            </p>
            <div className="mt-8 flex justify-center">
              <ButtonLink href="#how-it-works" variant="secondary" size="lg">
                See How It Works
              </ButtonLink>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
