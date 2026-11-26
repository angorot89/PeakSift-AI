import { Wand2 } from "lucide-react";
import { ButtonLink } from "@/components/ui/button-link";

export function ClosingCta() {
  return (
    <section id="get-started" className="scroll-mt-20 px-6 py-24">
      <div className="mx-auto max-w-6xl rounded-canvas bg-[radial-gradient(70%_80%_at_50%_0%,rgb(140_160_255/0.6),transparent_70%),linear-gradient(150deg,#3d5afe,#5b3dfe)] px-6 py-20 text-center sm:px-16">
        <h2 className="mx-auto max-w-3xl text-4xl font-extrabold tracking-tight text-balance text-white sm:text-6xl">
          Your next long video already has its best Shorts in it.
        </h2>
        <p className="mx-auto mt-5 max-w-xl text-lg text-pretty text-white/90">Drop it in and see what PeakSift finds.</p>
        <ButtonLink
          href="/register"
          size="lg"
          className="mt-9 bg-white !text-[#1b2a8f] shadow-[0_10px_30px_-10px_rgb(14_18_34/0.5)] hover:!bg-white/90"
        >
          <Wand2 aria-hidden="true" />
          Start clipping
        </ButtonLink>
      </div>
    </section>
  );
}
