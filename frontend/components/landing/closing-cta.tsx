import { ButtonLink } from "@/components/ui/button-link";

export function ClosingCta() {
  return (
    <section id="get-started" className="scroll-mt-20 border-t border-border py-24">
      <div className="mx-auto max-w-6xl px-6">
        <div className="relative overflow-hidden rounded-card border border-border bg-surface px-6 py-16 sm:px-16">
          <div className="relative">
            <h2 className="max-w-2xl text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
              Your next long-form video already has its best clips in it.
            </h2>
            <p className="mt-4 max-w-xl text-base leading-relaxed text-pretty text-muted sm:text-lg">
              Upload a recording, get a timestamped transcript, let AI rank
              the moments worth clipping, then render them as vertical shorts
              with captions — all in one workspace.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <ButtonLink href="/register" size="lg" className="w-full sm:w-auto">
                Get started
              </ButtonLink>
              <ButtonLink
                href="#how-it-works"
                variant="secondary"
                size="lg"
                className="w-full sm:w-auto"
              >
                See how it works
              </ButtonLink>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
